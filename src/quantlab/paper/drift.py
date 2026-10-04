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
- **Fill gaps, split into the modelled timing convention and execution**
  (quant-gate M09 cycle 1, finding 3). The paper runner decides at the
  previous completed session's close and fills at the NEXT session's open,
  about 1.5 sessions after the backtest's `close` convention. Comparing a
  fill with the decision-bar close would report that overnight offset as
  "drift". For every actual `Fill` this module therefore reports two
  numbers, both in basis points:
  `timing_gap_bps` = (open of `assumed_fill_session` - decision close) /
  decision close, the convention's own offset (the decision close is the
  raw close on the date `price_asof_by_ticker` recorded); and
  `execution_gap_bps` = (fill price - open of `assumed_fill_session`) /
  that open, the real execution slippage. `assumed_fill_session` (journaled
  by the runner) is what selects the open; a record without one, a ticker
  without a price-asof entry, or a missing/zero bar yields NO figure for
  that ticker and an entry in `gaps_not_computed` naming why - never 0.
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
    # ticker -> (open(assumed_fill_session) - decision close) / decision close
    # * 10_000: the paper timing convention's own offset (see module docstring).
    timing_gap_bps: dict[str, float] = field(default_factory=dict)
    # ticker -> (fill_price - open(assumed_fill_session)) / that open * 10_000.
    execution_gap_bps: dict[str, float] = field(default_factory=dict)
    # ticker -> why neither gap could be computed (never reported as 0).
    gaps_not_computed: dict[str, str] = field(default_factory=dict)
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
            "timing_gap_bps": self.timing_gap_bps,
            "execution_gap_bps": self.execution_gap_bps,
            "gaps_not_computed": self.gaps_not_computed,
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


def _price_on_date(
    price_provider, ticker: str, date: pd.Timestamp, column: str = "close"
) -> float | None:
    """The raw `column` (default close) for `ticker` on EXACTLY `date`, or
    `None` if the provider has no bar there (e.g. the sidecar has since been
    healed/re-fetched and no longer covers that exact session)."""
    window_start = date - pd.Timedelta(days=10)
    panel = price_provider.get_prices([ticker], window_start, date)
    panel = panel[(panel["ticker"] == ticker) & (panel.index == date)]
    if panel.empty:
        return None
    return float(panel[column].iloc[0])


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

        timing_gaps: dict[str, float] = {}
        execution_gaps: dict[str, float] = {}
        not_computed: dict[str, str] = {}
        fill_session_ts = (
            normalize_timestamp(assumed_fill_session) if assumed_fill_session else None
        )
        for result in r.get("results") or []:
            if "price" not in result or "ticker" not in result:
                continue  # an OrderAck (no fill yet), not a Fill
            ticker = result["ticker"]
            fill_price = result["price"]
            price_date_iso = price_asof_by_ticker.get(ticker)
            if price_date_iso is None:
                not_computed[ticker] = "no price_asof_by_ticker entry in the journal record"
                continue
            if fill_session_ts is None:
                not_computed[ticker] = "no assumed_fill_session in the journal record"
                continue
            decision_close = _price_on_date(
                providers.price, ticker, normalize_timestamp(price_date_iso), "close"
            )
            fill_open = _price_on_date(providers.price, ticker, fill_session_ts, "open")
            if not decision_close or not fill_open:
                not_computed[ticker] = (
                    "no usable decision-bar close or fill-session open in the price cache"
                )
                continue
            timing_gaps[ticker] = (fill_open - decision_close) / decision_close * 10_000.0
            execution_gaps[ticker] = (fill_price - fill_open) / fill_open * 10_000.0

        out.append(
            DriftRecord(
                asof=str(asof.date()),
                assumed_fill_session=assumed_fill_session,
                target_weight_agreement=agreement,
                max_abs_weight_diff=max_diff,
                tickers_only_in_journal=only_journal,
                tickers_only_in_recomputed=only_recomputed,
                timing_gap_bps=timing_gaps,
                execution_gap_bps=execution_gaps,
                gaps_not_computed=not_computed,
                price_asof_lag_sessions=price_asof_lag_sessions,
            )
        )

    return DriftReport(strategy_id=strategy.strategy_id, records=out)
