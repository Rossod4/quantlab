"""Append-only JSONL paper-trading journal: one record per `run_once` (or
`accept_broker_state`) call, under `reports_dir/paper/<strategy_id>/journal.jsonl`.

Append-only by construction (`append_journal` only ever opens in `"a"` mode
and never rewrites an existing line) so a run's record, once written, is a
permanent part of the history M09's forward-vs-backtest drift check reads -
`journal_to_frame()` is that reader's entry point."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from quantlab.core.types import normalize_timestamp

_JOURNAL_FILENAME = "journal.jsonl"


def journal_path(reports_dir: str | Path, strategy_id: str) -> Path:
    return Path(reports_dir) / "paper" / strategy_id / _JOURNAL_FILENAME


@dataclass(frozen=True)
class JournalRecord:
    """One `run_once`/`accept_broker_state` call's complete record.
    `targets`/`planned_orders`/`results`/`account_before`/`account_after`/
    `reconcile_report` are already JSON-safe dicts (each type's own
    `to_json`/`model_dump(mode="json")`) - this dataclass does not know
    about the richer objects they came from, so `journal.py` has no
    dependency on `paper/broker.py`'s types beyond what `runner.py` already
    resolved to plain data.

    `kind`: `"run"` (an ordinary scheduled `run_once` call, trading or
    refused) or `"rebaseline"` (`accept_broker_state` - a human-driven,
    explicitly-approved reset of the reconcile baseline, quant-gate
    VERDICT.md M08 cycle-1 finding 1). A reader must never mistake one for
    the other; `kind` makes that a field check, not an inference from which
    other fields happen to be populated.
    `refused_reason`: non-`None` exactly when a `"run"` record refused to
    trade (promotion gate, reconcile, a data-degradation abort, an
    exhausted actions-cache refresh, or a planning/submission failure) -
    `planned_orders`/`results` are then empty and `account_after` equals
    `account_before`. Always `None` for a `"rebaseline"` record (accepting
    the broker's state is not a refusal).
    `refreshed_actions_tickers`: tickers whose corporate-actions cache was
    refreshed this run under the M02b/M04-carried staleness-refresh policy.
    `dropped_tickers`/`dropped_fraction`: per quant-gate VERDICT.md M08
    cycle-1 finding 2 - tickers the shared decision-context's per-ticker
    data-availability probe dropped from the universe this run (never
    reaching the strategy), and that count as a fraction of the raw
    membership probed. `unscored_tickers`: `TargetWeights.unscored` (a
    ticker the strategy itself tried and failed to score, e.g. a missing
    lookback price) - both let M09 tell a data outage from a genuine signal
    change, neither of which the pre-cycle-2 journal recorded at all.
    `forced_exits`: ticker -> reason (e.g. "forced exit: no price /
    delisted", finding 3) for a held position priced out of `plan_orders`'
    normal sizing this run.
    `canceled_orders`: resting orders canceled at the START of this cycle,
    before planning (finding 4's `cancel_open_before_plan` policy) -
    `[{"client_order_id", "ticker", "qty"}, ...]`.
    `resting_orders`: `broker.open_orders()` taken immediately AFTER
    `submit()` this cycle (finding 4's "after submit, call open_orders();
    journal resting remainders") - a partial fill's unfilled remainder, so a
    reader (or M09) can see it was left open WITHOUT waiting for the next
    cycle's `canceled_orders` to reveal it retroactively.
    `price_asof_by_ticker`: ticker -> ISO date of the actual price bar used
    to size that ticker's order this run (carried, non-blocking item: the
    staleness ceiling only ever watched the benchmark; this is the
    per-ticker record M09 needs to tell a stale bar from a signal move).
    `assumed_fill_session`: ISO date of the session a market order submitted
    this run is assumed to fill at (`next_trading_day(asof)`) - documents
    the paper-trading timing convention (decide at the prior completed
    session's close, fill at the NEXT session's open) so M09's drift check
    can model the ~1.5-session lag against the backtest's `close`-mode
    convention (carried, non-blocking item)."""

    asof: str
    strategy_id: str
    data_semantics_version: str
    quantlab_git_sha: str
    dirty: bool | None
    targets: dict[str, Any] | None
    planned_orders: list[dict[str, Any]]
    results: list[dict[str, Any]]
    account_before: dict[str, Any]
    account_after: dict[str, Any]
    reconcile_report: dict[str, Any] | None
    promoting_report_card: str | None
    kind: str = "run"
    known_caveats: list[str] = field(default_factory=list)
    force_research: bool = False
    refused_reason: str | None = None
    refreshed_actions_tickers: list[str] = field(default_factory=list)
    dropped_tickers: list[str] = field(default_factory=list)
    dropped_fraction: float | None = None
    unscored_tickers: dict[str, str] = field(default_factory=dict)
    forced_exits: dict[str, str] = field(default_factory=dict)
    canceled_orders: list[dict[str, Any]] = field(default_factory=list)
    resting_orders: list[dict[str, Any]] = field(default_factory=list)
    price_asof_by_ticker: dict[str, str] = field(default_factory=dict)
    assumed_fill_session: str | None = None
    run_timestamp: str = field(default_factory=lambda: pd.Timestamp.now("UTC").isoformat())

    def to_json(self) -> dict[str, Any]:
        return {
            "asof": self.asof,
            "strategy_id": self.strategy_id,
            "data_semantics_version": self.data_semantics_version,
            "quantlab_git_sha": self.quantlab_git_sha,
            "dirty": self.dirty,
            "targets": self.targets,
            "planned_orders": self.planned_orders,
            "results": self.results,
            "account_before": self.account_before,
            "account_after": self.account_after,
            "reconcile_report": self.reconcile_report,
            "promoting_report_card": self.promoting_report_card,
            "kind": self.kind,
            "known_caveats": self.known_caveats,
            "force_research": self.force_research,
            "refused_reason": self.refused_reason,
            "refreshed_actions_tickers": self.refreshed_actions_tickers,
            "dropped_tickers": self.dropped_tickers,
            "dropped_fraction": self.dropped_fraction,
            "unscored_tickers": self.unscored_tickers,
            "forced_exits": self.forced_exits,
            "canceled_orders": self.canceled_orders,
            "resting_orders": self.resting_orders,
            "price_asof_by_ticker": self.price_asof_by_ticker,
            "assumed_fill_session": self.assumed_fill_session,
            "run_timestamp": self.run_timestamp,
        }


def append_journal(reports_dir: str | Path, record: JournalRecord) -> Path:
    """Append `record` as one JSON line. Creates the strategy's journal
    directory if needed. Returns the journal file's path."""
    path = journal_path(reports_dir, record.strategy_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record.to_json(), sort_keys=True))
        f.write("\n")
    return path


def read_journal(reports_dir: str | Path, strategy_id: str) -> list[dict[str, Any]]:
    """Every record for `strategy_id`, in the order they were appended (=
    chronological run order). `[]` if nothing has been journaled yet - never
    raises for a missing file."""
    path = journal_path(reports_dir, strategy_id)
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records


_FRAME_COLUMNS = [
    "asof",
    "strategy_id",
    "data_semantics_version",
    "quantlab_git_sha",
    "dirty",
    "kind",
    "n_planned_orders",
    "n_results",
    "cash_before",
    "equity_before",
    "cash_after",
    "equity_after",
    "reconciled_ok",
    "force_research",
    "refused_reason",
    "promoting_report_card",
    "known_caveats",
    "refreshed_actions_tickers",
    "dropped_tickers",
    "dropped_fraction",
    "unscored_tickers",
    "forced_exits",
    "n_canceled_orders",
    "n_resting_orders",
    "targets",
    "assumed_fill_session",
    "run_timestamp",
]


def journal_to_frame(reports_dir: str | Path, strategy_id: str) -> pd.DataFrame:
    """A tabular view of `strategy_id`'s journal for M09's forward-vs-backtest
    drift dashboard: one row per run, indexed by `asof` (a `pd.Timestamp`,
    NOT the run's wall-clock `run_timestamp`), with the full per-run detail
    still available in the underlying JSONL for anything this summary
    doesn't cover (e.g. the full `canceled_orders`/`resting_orders` order
    lists, `price_asof_by_ticker`, the full `reconcile_report` including
    `applied_adjustments` - this frame carries only `n_canceled_orders`/
    `n_resting_orders` counts). Widened (quant-gate
    VERDICT.md M08 cycle-1 carried item) to also carry `promoting_report_card`,
    `known_caveats`, `refreshed_actions_tickers`, and `targets` - previously
    present only in the raw JSONL. Empty (with the documented columns,
    `asof`-indexed) if nothing has been journaled yet - a caller can always
    assume this shape, never `None`/a missing file."""
    records = read_journal(reports_dir, strategy_id)
    if not records:
        empty = pd.DataFrame(columns=_FRAME_COLUMNS)
        empty.index = pd.DatetimeIndex([], name="asof")
        return empty.drop(columns=["asof"])

    rows = []
    for r in records:
        account_before = r.get("account_before") or {}
        account_after = r.get("account_after") or {}
        reconcile_report = r.get("reconcile_report")
        rows.append(
            {
                "asof": normalize_timestamp(r["asof"]),
                "strategy_id": r["strategy_id"],
                "data_semantics_version": r["data_semantics_version"],
                "quantlab_git_sha": r["quantlab_git_sha"],
                "dirty": r.get("dirty"),
                "kind": r.get("kind", "run"),
                "n_planned_orders": len(r.get("planned_orders") or []),
                "n_results": len(r.get("results") or []),
                "cash_before": account_before.get("cash"),
                "equity_before": account_before.get("equity"),
                "cash_after": account_after.get("cash"),
                "equity_after": account_after.get("equity"),
                "reconciled_ok": reconcile_report.get("ok") if reconcile_report else None,
                "force_research": r.get("force_research", False),
                "refused_reason": r.get("refused_reason"),
                "promoting_report_card": r.get("promoting_report_card"),
                "known_caveats": r.get("known_caveats") or [],
                "refreshed_actions_tickers": r.get("refreshed_actions_tickers") or [],
                "dropped_tickers": r.get("dropped_tickers") or [],
                "dropped_fraction": r.get("dropped_fraction"),
                "unscored_tickers": r.get("unscored_tickers") or {},
                "forced_exits": r.get("forced_exits") or {},
                "n_canceled_orders": len(r.get("canceled_orders") or []),
                "n_resting_orders": len(r.get("resting_orders") or []),
                "targets": r.get("targets"),
                "assumed_fill_session": r.get("assumed_fill_session"),
                "run_timestamp": r.get("run_timestamp"),
            }
        )
    frame = pd.DataFrame(rows).set_index("asof").sort_index()
    return frame[[c for c in _FRAME_COLUMNS if c != "asof"]]
