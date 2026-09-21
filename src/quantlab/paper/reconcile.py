"""`reconcile`: compare what the platform's own journal expects the account
to hold against what the broker actually reports, and refuse to trade on any
mismatch beyond tolerance.

This is the safety net between two `run_once` calls: if a human intervened
in the brokerage account, a fill was missed, or a prior run crashed
mid-settlement, the account the runner sees at the START of a new run may
not match what the journal's last entry expected. Trading on top of an
unexplained mismatch compounds the error silently - `reconcile` instead
raises `ReconcileError` (core/errors.py) and the runner refuses to trade
that day, exactly per the work packet: "any position or cash mismatch beyond
tolerance raises ReconcileError and the runner refuses to trade that day (a
human resolves)"."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from quantlab.core.errors import ReconcileError
from quantlab.core.types import Position, normalize_timestamp
from quantlab.paper.broker import AccountSnapshot


@dataclass(frozen=True)
class ReconcileTolerances:
    """Absolute tolerances, in the account's own units - a dollar amount for
    cash, a share count for quantity. Deliberately absolute, not relative:
    a relative tolerance would silently loosen as the account grows, which
    is the wrong direction for a check whose whole point is catching a
    fixed-size real-world discrepancy (e.g. one missed fill)."""

    cash_abs_tolerance: float = 1.0
    qty_abs_tolerance: float = 1e-6


@dataclass(frozen=True)
class PositionMismatch:
    ticker: str
    expected_qty: float
    actual_qty: float

    @property
    def diff(self) -> float:
        return self.actual_qty - self.expected_qty

    def to_json(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "expected_qty": self.expected_qty,
            "actual_qty": self.actual_qty,
            "diff": self.diff,
        }


@dataclass(frozen=True)
class ReconcileReport:
    ok: bool
    cash_expected: float
    cash_actual: float
    position_mismatches: tuple[PositionMismatch, ...] = field(default_factory=tuple)
    # quant-gate VERDICT.md M08 cycle-1 finding 1: every corporate-action
    # adjustment `roll_forward_expected` applied BEFORE this comparison was
    # made - carried on the report itself so the journal records what was
    # explained alongside the pass/fail outcome, not as a separate value the
    # caller has to remember to also store.
    applied_adjustments: tuple[AppliedAdjustment, ...] = field(default_factory=tuple)

    @property
    def cash_diff(self) -> float:
        return self.cash_actual - self.cash_expected

    def to_json(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "cash_expected": self.cash_expected,
            "cash_actual": self.cash_actual,
            "cash_diff": self.cash_diff,
            "position_mismatches": [m.to_json() for m in self.position_mismatches],
            "applied_adjustments": [a.to_json() for a in self.applied_adjustments],
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> ReconcileReport:
        return cls(
            ok=bool(data["ok"]),
            cash_expected=float(data["cash_expected"]),
            cash_actual=float(data["cash_actual"]),
            position_mismatches=tuple(
                PositionMismatch(m["ticker"], float(m["expected_qty"]), float(m["actual_qty"]))
                for m in data.get("position_mismatches", [])
            ),
            applied_adjustments=tuple(
                AppliedAdjustment.from_json(a) for a in data.get("applied_adjustments", [])
            ),
        )


@dataclass(frozen=True)
class AppliedAdjustment:
    """One corporate-action adjustment applied by `roll_forward_expected` -
    journaled verbatim (quant-gate VERDICT.md M08 cycle-1 finding 1: "journal
    that adjustment so a reader can see what was explained versus what was
    not") so a human reading `journal.jsonl` can see exactly which dividends/
    splits were used to explain a cash/quantity difference, rather than just
    a pass/fail reconcile outcome."""

    ticker: str
    action_type: str  # "dividend" | "split"
    date: str  # ISO date - the action's own EX-DATE (see module docstring)
    value: float  # the raw actions-frame value (per-share $ or split ratio)
    cash_credit: float = 0.0  # nonzero only for a dividend
    qty_factor: float = 1.0  # nonzero-meaningful only for a split

    def to_json(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "action_type": self.action_type,
            "date": self.date,
            "value": self.value,
            "cash_credit": self.cash_credit,
            "qty_factor": self.qty_factor,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> AppliedAdjustment:
        return cls(
            ticker=data["ticker"],
            action_type=data["action_type"],
            date=data["date"],
            value=float(data["value"]),
            cash_credit=float(data.get("cash_credit", 0.0)),
            qty_factor=float(data.get("qty_factor", 1.0)),
        )


def roll_forward_expected(
    expected: AccountSnapshot,
    actions_by_ticker: dict[str, pd.DataFrame],
    start: object,
    end: object,
) -> tuple[AccountSnapshot, list[AppliedAdjustment]]:
    """Roll `expected` (the prior traded run's own `account_after`) forward
    through every dividend/split with ex-date in `(start, end]` for each
    currently-held ticker, so an ORDINARY corporate action between two
    scheduled runs is EXPLAINED rather than read as an unexplained account
    mismatch (quant-gate VERDICT.md M08 cycle-1 finding 1 - as shipped in
    cycle 1, the first dividend paid inside a paper account bricked the
    schedule forever, since the frozen baseline never advanced and never
    accounted for the credit).

    Dividends (`action_type == "dividend"`, `value` = the per-share dividend
    amount - data/corporate_actions.py's `_normalize_actions`): credit
    `qty * value` to cash on the action's own EX-DATE - the actions frame
    carries no separate pay-date field, and a holder of record on the
    ex-date is who actually receives the distribution, so the ex-date is
    the economically correct date to attribute it to even though the cash
    typically arrives some days later. Uses the qty ALREADY in `expected`
    (this platform does not reconstruct an intra-window qty history) - a
    holding whose SIZE itself changed between two scheduled runs for a
    reason other than a split rolled forward here is a case this function
    cannot explain, and any resulting mismatch still correctly refuses.

    Splits (`action_type == "split"`, `value` = R, yfinance/
    data/adjustment.py convention: R new shares per old share):
    `qty *= R`, `avg_cost /= R` - the IDENTICAL restatement `data/pit.py`'s
    M03b share-terms logic already applies elsewhere in this platform.

    Multiple actions for the same ticker are applied in ex-date order. A
    ticker missing from `actions_by_ticker` (its fetch failed, or it has no
    actions) is left unadjusted - documented, not silently perfect: see
    `paper/runner.py`'s own caller for how a fetch failure here is handled.

    Returns `(rolled_expected, applied)` - `equity` is bumped by the total
    dividend credit only (a split leaves true equity unchanged by
    definition); `reconcile`/`build_reconcile_report` never compare `equity`
    directly, only `cash` and per-ticker `qty`, so this is informational."""
    start_ts, end_ts = normalize_timestamp(start), normalize_timestamp(end)
    positions = dict(expected.positions)
    cash = expected.cash
    dividend_total = 0.0
    applied: list[AppliedAdjustment] = []

    for ticker, position in expected.positions.items():
        actions = actions_by_ticker.get(ticker)
        if actions is None or actions.empty:
            continue
        window = actions.loc[(actions.index > start_ts) & (actions.index <= end_ts)].sort_index()
        if window.empty:
            continue
        qty, avg_cost = position.qty, position.avg_cost
        for date, row in window.iterrows():
            value = float(row["value"])
            date_str = str(pd.Timestamp(date).date())
            if row["action_type"] == "dividend":
                credit = qty * value
                cash += credit
                dividend_total += credit
                applied.append(
                    AppliedAdjustment(ticker, "dividend", date_str, value, cash_credit=credit)
                )
            elif row["action_type"] == "split" and value:
                qty *= value
                avg_cost /= value
                applied.append(
                    AppliedAdjustment(ticker, "split", date_str, value, qty_factor=value)
                )
        if (qty, avg_cost) != (position.qty, position.avg_cost):
            positions[ticker] = Position(ticker=ticker, qty=qty, avg_cost=avg_cost)

    rolled = AccountSnapshot(
        cash=cash, equity=expected.equity + dividend_total, positions=positions
    )
    return rolled, applied


def build_reconcile_report(
    journal_expected: AccountSnapshot,
    account_actual: AccountSnapshot,
    tolerances: ReconcileTolerances | None = None,
    applied_adjustments: tuple[AppliedAdjustment, ...] = (),
) -> ReconcileReport:
    """Pure comparison - never raises. `reconcile()` below is the raising
    wrapper the runner actually calls; this is exposed separately so a
    caller (or a test) can inspect a mismatch report without triggering the
    `ReconcileError` control-flow path. `journal_expected` should already be
    the OUTPUT of `roll_forward_expected` when corporate actions are in
    play - this function itself does no rolling, it only compares and
    carries `applied_adjustments` through onto the returned report for the
    journal."""
    tol = tolerances or ReconcileTolerances()

    tickers = sorted(set(journal_expected.positions) | set(account_actual.positions))
    mismatches = []
    for ticker in tickers:
        expected_qty = (
            journal_expected.positions[ticker].qty if ticker in journal_expected.positions else 0.0
        )
        actual_qty = (
            account_actual.positions[ticker].qty if ticker in account_actual.positions else 0.0
        )
        if abs(actual_qty - expected_qty) > tol.qty_abs_tolerance:
            mismatches.append(PositionMismatch(ticker, expected_qty, actual_qty))

    cash_ok = abs(account_actual.cash - journal_expected.cash) <= tol.cash_abs_tolerance
    ok = cash_ok and not mismatches
    return ReconcileReport(
        ok=ok,
        cash_expected=journal_expected.cash,
        cash_actual=account_actual.cash,
        position_mismatches=tuple(mismatches),
        applied_adjustments=applied_adjustments,
    )


def reconcile(
    journal_expected: AccountSnapshot,
    account_actual: AccountSnapshot,
    tolerances: ReconcileTolerances | None = None,
    applied_adjustments: tuple[AppliedAdjustment, ...] = (),
) -> ReconcileReport:
    """Raises `ReconcileError` (with the full `ReconcileReport` attached as
    `.report`) if `journal_expected` and `account_actual` disagree on cash or
    any position beyond `tolerances`; otherwise returns the (necessarily
    `ok=True`) report."""
    report = build_reconcile_report(
        journal_expected, account_actual, tolerances, applied_adjustments
    )
    if not report.ok:
        message = (
            f"reconcile failed: cash expected={report.cash_expected:.2f} "
            f"actual={report.cash_actual:.2f} (diff={report.cash_diff:.2f})"
        )
        if report.position_mismatches:
            mismatch_desc = ", ".join(
                f"{m.ticker}: expected {m.expected_qty} actual {m.actual_qty}"
                for m in report.position_mismatches
            )
            message += f"; position mismatches: [{mismatch_desc}]"
        raise ReconcileError(message, report=report)
    return report
