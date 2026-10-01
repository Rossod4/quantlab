"""`quantlab paper drift`: the forward-vs-backtest drift check (M09, carried
from the M08 verdict - "must-fix before any forward-vs-backtest number is
quoted").

Timing convention (docs/paper-trading.md section 7, `runner.py`'s own
`JournalRecord.assumed_fill_session`): the paper runner DECIDES using the
last completed session's close and its market orders are ASSUMED to fill at
the NEXT session's open - roughly one and a half sessions after the
backtest's own `close`-mode convention, which both decides AND fills at the
SAME session's close for the same nominal rebalance date. This module models
that lag EXPLICITLY (the orchestrator's second option, rather than actually
running a parallel `next_open`-mode backtest for every journaled date - a
single real backtest over the shipped 2012-2026 window measured in the
hours on this platform's data, see plans/state/M09/HANDOFF.md, so re-running
one per journaled cycle is not a viable per-check cost):

- **Target-weight agreement**: `strategy.generate_targets` is called AGAIN
  at each journaled `asof`, through the IDENTICAL shared
  `backtest.context.build_decision_context` both `run_backtest` and
  `run_once` call (docs/paper-trading.md's own "Guarantees" section) - on
  whatever the price/fundamentals/actions cache holds TODAY. A cache that
  has moved on since the journal entry (a later corporate action, a
  refreshed price, a healed quarantine) will show up here as genuine,
  disclosed drift, not a bug in this check - `cache_changed_since_journal`
  is not tracked separately because the whole point of a point-in-time
  platform is that a `PITDataContext` at a FIXED `asof` should be
  reproducible regardless of when it is rebuilt, so a mismatch here is
  itself the finding.
- **Fill-vs-model price gap**: for every actual `Fill` in the journaled
  record's `results`, the ticker's raw close on the EXACT date
  `price_asof_by_ticker` recorded (the bar the runner's own sizing actually
  used that day - `runner._last_prices_with_dates`) is re-fetched and
  compared to the fill price, in basis points.
- **Per-ticker data-asof lag**: trading SESSIONS between `asof` and each
  ticker's own `price_asof_by_ticker` entry - a stale/lagging per-ticker
  data sync (0 is a same-session bar; the benchmark-only staleness ceiling
  this replaces could not see this at all, `journal.py`'s own docstring).

Offline and deterministic: this module never runs a backtest and never talks
to a broker - it only re-derives DECISIONS from the shared cache and reads
the already-journaled record of what actually happened.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from quantlab.backtest.context import DecisionProviders, build_decision_context
from quantlab.backtest.engine import BacktestProviders
from quantlab.core.calendar import trading_days
from quantlab.core.types import normalize_timestamp
from quantlab.paper.journal import read_journal
from quantlab.strategies.base import Strategy


@dataclass(frozen=True)
class DriftRecord:
    """One journaled trading cycle's drift measurement, or (`error` set) why
    it could not be recomputed - a recompute failure (e.g. the actions cache
    has since gone stale past this `asof`) is reported per-record, never
    silently skipped or allowed to crash the whole check."""

    asof: str
    assumed_fill_session: str | None
    error: str | None = None
    # Target-weight agreement: 1.0 - (L1 distance between the journaled and
    # freshly-recomputed weight vectors) / 2 - the fraction of the book that
    # would NOT need to be re-traded to reconcile the two decisions. 1.0 is
    # perfect agreement; None when either side has no scoreable weights.
    target_weight_agreement: float | None = None
    max_abs_weight_diff: float | None = None
    tickers_only_in_journal: list[str] = field(default_factory=list)
    tickers_only_in_recomputed: list[str] = field(default_factory=list)
    # ticker -> (fill_price - model_price) / model_price * 10_000.
    fill_vs_model_price_gap_bps: dict[str, float] = field(default_factory=dict)
    # ticker -> trading sessions between `asof` and that ticker's own
    # `price_asof_by_ticker` entry (0 = same-session bar).
    price_asof_lag_sessions: dict[str, int] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "asof": self.asof,
            "assumed_fill_session": self.assumed_fill_session,
            "error": self.error,
            "target_weight_agreement": self.target_weight_agreement,
            "max_abs_weight_diff": self.max_abs_weight_diff,
            "tickers_only_in_journal": self.tickers_only_in_journal,
            "tickers_only_in_recomputed": self.tickers_only_in_recomputed,
            "fill_vs_model_price_gap_bps": self.fill_vs_model_price_gap_bps,
            "price_asof_lag_sessions": self.price_asof_lag_sessions,
        }


@dataclass(frozen=True)
class DriftReport:
    strategy_id: str
    records: list[DriftRecord]

    def to_json(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "records": [r.to_json() for r in self.records],
        }


def _weight_agreement(
    journaled: dict[str, float], recomputed: dict[str, float]
) -> tuple[float | None, float | None, list[str], list[str]]:
    only_journal = sorted(set(journaled) - set(recomputed))
    only_recomputed = sorted(set(recomputed) - set(journaled))
    tickers = set(journaled) | set(recomputed)
    if not tickers:
        return None, None, only_journal, only_recomputed
    diffs = [abs(journaled.get(t, 0.0) - recomputed.get(t, 0.0)) for t in tickers]
    l1 = sum(diffs)
    return 1.0 - l1 / 2.0, max(diffs), only_journal, only_recomputed


def _price_on_date(price_provider, ticker: str, date: pd.Timestamp) -> float | None:
    """The raw close for `ticker` on EXACTLY `date`, or `None` if the
    provider has no bar there (e.g. the sidecar has since been
    healed/re-fetched and no longer covers that exact session)."""
    window_start = date - pd.Timedelta(days=10)
    panel = price_provider.get_prices([ticker], window_start, date)
    panel = panel[(panel["ticker"] == ticker) & (panel.index == date)]
    if panel.empty:
        return None
    return float(panel["close"].iloc[0])


def compute_drift(
    reports_dir: str | Path,
    strategy: Strategy,
    providers: BacktestProviders,
    *,
    max_records: int | None = None,
) -> DriftReport:
    """Compute a `DriftReport` for `strategy` from its journal under
    `reports_dir`. Only `kind="run"` records with `refused_reason is None`
    and a non-empty `targets` are compared - a refusal or a rebaseline never
    traded, so there is nothing to compare against. `max_records` (most
    recent first) bounds an expensive-cache-refetch run over a long
    history; omitted, every eligible record is checked."""
    records = read_journal(reports_dir, strategy.strategy_id)
    trading_records = [
        r
        for r in records
        if r.get("kind", "run") == "run" and r.get("refused_reason") is None and r.get("targets")
    ]
    if max_records is not None:
        trading_records = trading_records[-max_records:]

    decision_providers = DecisionProviders(
        price=providers.price,
        constituents=providers.constituents,
        fundamentals=providers.fundamentals,
        corporate_actions=providers.corporate_actions,
    )

    out: list[DriftRecord] = []
    for r in trading_records:
        asof = normalize_timestamp(r["asof"])
        assumed_fill_session = r.get("assumed_fill_session")

        def _on_drop(_ticker: str, _exc: Exception) -> None:
            return None

        def _context_factory(reqs, _asof=asof):
            return build_decision_context(
                asof=_asof,
                requirements=reqs,
                providers=decision_providers,
                # A recompute is a READ-ONLY diagnostic, not a live trading
                # decision - never abort the whole check over a data gap
                # that would (correctly) abort a real run; a dropped ticker
                # simply cannot appear in `tickers_recomputed` below.
                max_dropped_fraction=1.0,
                on_drop=_on_drop,
            )

        try:
            ctx = _context_factory(strategy.requires())
            if hasattr(strategy, "set_context_factory"):
                strategy.set_context_factory(_context_factory)
            recomputed_targets = strategy.generate_targets(ctx, asof)
        except Exception as exc:  # noqa: BLE001 - report per-record, never crash the check
            out.append(
                DriftRecord(
                    asof=str(asof.date()),
                    assumed_fill_session=assumed_fill_session,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
            continue

        journaled_weights = dict((r.get("targets") or {}).get("weights") or {})
        recomputed_weights = dict(recomputed_targets.weights)
        agreement, max_diff, only_journal, only_recomputed = _weight_agreement(
            journaled_weights, recomputed_weights
        )

        price_asof_by_ticker = r.get("price_asof_by_ticker") or {}
        price_asof_lag_sessions: dict[str, int] = {}
        for ticker, iso_date in price_asof_by_ticker.items():
            price_date = normalize_timestamp(iso_date)
            price_asof_lag_sessions[ticker] = len(trading_days(price_date, asof)) - 1

        fill_gaps: dict[str, float] = {}
        for result in r.get("results") or []:
            if "price" not in result or "ticker" not in result:
                continue  # an OrderAck (no fill yet), not a Fill
            ticker = result["ticker"]
            fill_price = result["price"]
            price_date_iso = price_asof_by_ticker.get(ticker)
            if price_date_iso is None:
                continue
            model_price = _price_on_date(
                providers.price, ticker, normalize_timestamp(price_date_iso)
            )
            if model_price is None or model_price == 0:
                continue
            fill_gaps[ticker] = (fill_price - model_price) / model_price * 10_000.0

        out.append(
            DriftRecord(
                asof=str(asof.date()),
                assumed_fill_session=assumed_fill_session,
                target_weight_agreement=agreement,
                max_abs_weight_diff=max_diff,
                tickers_only_in_journal=only_journal,
                tickers_only_in_recomputed=only_recomputed,
                fill_vs_model_price_gap_bps=fill_gaps,
                price_asof_lag_sessions=price_asof_lag_sessions,
            )
        )

    return DriftReport(strategy_id=strategy.strategy_id, records=out)
