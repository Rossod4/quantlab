"""Tests for `paper/reconcile.py`."""

from __future__ import annotations

import pandas as pd
import pytest

from quantlab.core.errors import ReconcileError
from quantlab.core.types import Position
from quantlab.paper.broker import AccountSnapshot
from quantlab.paper.reconcile import (
    AppliedAdjustment,
    ReconcileTolerances,
    build_reconcile_report,
    reconcile,
    roll_forward_expected,
)


def test_matching_accounts_reconcile_cleanly():
    expected = AccountSnapshot(
        cash=1_000.0,
        equity=2_000.0,
        positions={"AAA": Position(ticker="AAA", qty=10.0, avg_cost=100.0)},
    )
    actual = AccountSnapshot(
        cash=1_000.0,
        equity=2_000.0,
        positions={"AAA": Position(ticker="AAA", qty=10.0, avg_cost=100.0)},
    )

    report = reconcile(expected, actual)

    assert report.ok
    assert report.position_mismatches == ()
    assert report.cash_diff == 0.0


def test_cash_mismatch_beyond_tolerance_raises():
    expected = AccountSnapshot(cash=1_000.0, equity=1_000.0, positions={})
    actual = AccountSnapshot(cash=990.0, equity=990.0, positions={})

    with pytest.raises(ReconcileError) as exc_info:
        reconcile(expected, actual, ReconcileTolerances(cash_abs_tolerance=1.0))

    assert exc_info.value.report is not None
    assert not exc_info.value.report.ok


def test_cash_mismatch_within_tolerance_does_not_raise():
    expected = AccountSnapshot(cash=1_000.0, equity=1_000.0, positions={})
    actual = AccountSnapshot(cash=999.5, equity=999.5, positions={})

    report = reconcile(expected, actual, ReconcileTolerances(cash_abs_tolerance=1.0))

    assert report.ok


def test_position_mismatch_beyond_tolerance_raises_and_names_the_ticker():
    expected = AccountSnapshot(
        cash=0.0,
        equity=1_000.0,
        positions={"AAA": Position(ticker="AAA", qty=10.0, avg_cost=100.0)},
    )
    actual = AccountSnapshot(
        cash=0.0, equity=1_000.0, positions={"AAA": Position(ticker="AAA", qty=8.0, avg_cost=100.0)}
    )

    with pytest.raises(ReconcileError) as exc_info:
        reconcile(expected, actual)

    report = exc_info.value.report
    assert not report.ok
    assert len(report.position_mismatches) == 1
    assert report.position_mismatches[0].ticker == "AAA"
    assert report.position_mismatches[0].diff == pytest.approx(-2.0)


def test_a_position_present_only_on_one_side_counts_as_a_mismatch():
    expected = AccountSnapshot(cash=0.0, equity=0.0, positions={})
    actual = AccountSnapshot(
        cash=0.0, equity=0.0, positions={"AAA": Position(ticker="AAA", qty=5.0, avg_cost=10.0)}
    )

    with pytest.raises(ReconcileError):
        reconcile(expected, actual)


def test_build_reconcile_report_never_raises():
    expected = AccountSnapshot(cash=1_000.0, equity=1_000.0, positions={})
    actual = AccountSnapshot(cash=0.0, equity=0.0, positions={})

    report = build_reconcile_report(expected, actual)

    assert not report.ok


def test_report_json_round_trips():
    expected = AccountSnapshot(
        cash=0.0,
        equity=1_000.0,
        positions={"AAA": Position(ticker="AAA", qty=10.0, avg_cost=100.0)},
    )
    actual = AccountSnapshot(
        cash=0.0, equity=1_000.0, positions={"AAA": Position(ticker="AAA", qty=8.0, avg_cost=100.0)}
    )
    report = build_reconcile_report(expected, actual)

    from quantlab.paper.reconcile import ReconcileReport

    round_tripped = ReconcileReport.from_json(report.to_json())

    assert round_tripped == report


# -- roll_forward_expected (quant-gate VERDICT.md M08 cycle-1 finding 1) ----


def test_roll_forward_credits_a_dividend_to_cash_using_held_qty():
    expected = AccountSnapshot(
        cash=1_000.0,
        equity=100_000.0,
        positions={"AAA": Position(ticker="AAA", qty=990.0, avg_cost=100.0)},
    )
    actions = {
        "AAA": pd.DataFrame(
            {"ticker": ["AAA"], "action_type": ["dividend"], "value": [0.25]},
            index=pd.DatetimeIndex(["2023-12-15"]),
        )
    }

    rolled, applied = roll_forward_expected(expected, actions, "2023-11-30", "2023-12-29")

    assert rolled.cash == pytest.approx(1_000.0 + 990.0 * 0.25)
    assert rolled.positions["AAA"].qty == 990.0  # unchanged - a dividend never changes qty
    assert len(applied) == 1
    assert applied[0] == AppliedAdjustment(
        "AAA", "dividend", "2023-12-15", 0.25, cash_credit=990.0 * 0.25
    )


def test_roll_forward_applies_a_split_to_qty_and_avg_cost():
    expected = AccountSnapshot(
        cash=0.0,
        equity=10_000.0,
        positions={"AAA": Position(ticker="AAA", qty=100.0, avg_cost=100.0)},
    )
    actions = {
        "AAA": pd.DataFrame(
            {"ticker": ["AAA"], "action_type": ["split"], "value": [2.0]},
            index=pd.DatetimeIndex(["2023-12-15"]),
        )
    }

    rolled, applied = roll_forward_expected(expected, actions, "2023-11-30", "2023-12-29")

    assert rolled.positions["AAA"].qty == pytest.approx(200.0)
    assert rolled.positions["AAA"].avg_cost == pytest.approx(50.0)
    assert rolled.cash == 0.0
    assert len(applied) == 1
    assert applied[0].action_type == "split"
    assert applied[0].qty_factor == 2.0


def test_roll_forward_ignores_actions_outside_the_window():
    expected = AccountSnapshot(
        cash=0.0,
        equity=10_000.0,
        positions={"AAA": Position(ticker="AAA", qty=100.0, avg_cost=100.0)},
    )
    actions = {
        "AAA": pd.DataFrame(
            {
                "ticker": ["AAA", "AAA"],
                "action_type": ["dividend", "dividend"],
                "value": [1.0, 2.0],
            },
            index=pd.DatetimeIndex(["2023-10-01", "2024-02-01"]),  # both outside the window
        )
    }

    rolled, applied = roll_forward_expected(expected, actions, "2023-11-30", "2023-12-29")

    assert rolled.cash == 0.0
    assert applied == []


def test_roll_forward_leaves_a_ticker_with_no_actions_data_unadjusted():
    expected = AccountSnapshot(
        cash=500.0,
        equity=10_000.0,
        positions={"AAA": Position(ticker="AAA", qty=100.0, avg_cost=100.0)},
    )

    rolled, applied = roll_forward_expected(expected, {}, "2023-11-30", "2023-12-29")

    assert rolled == expected
    assert applied == []


def test_reconcile_report_carries_applied_adjustments_through():
    expected_raw = AccountSnapshot(
        cash=1_000.0,
        equity=100_000.0,
        positions={"AAA": Position(ticker="AAA", qty=990.0, avg_cost=100.0)},
    )
    actions = {
        "AAA": pd.DataFrame(
            {"ticker": ["AAA"], "action_type": ["dividend"], "value": [0.25]},
            index=pd.DatetimeIndex(["2023-12-15"]),
        )
    }
    rolled, applied = roll_forward_expected(expected_raw, actions, "2023-11-30", "2023-12-29")
    actual = AccountSnapshot(cash=rolled.cash, equity=rolled.equity, positions=rolled.positions)

    report = build_reconcile_report(rolled, actual, applied_adjustments=tuple(applied))

    assert report.ok
    assert len(report.applied_adjustments) == 1
    round_tripped = report.__class__.from_json(report.to_json())
    assert round_tripped == report
