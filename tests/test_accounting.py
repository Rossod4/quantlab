"""Tests for backtest/accounting.py's `Ledger` - pure, deterministic
cash+positions bookkeeping (no I/O, no provider access)."""

from __future__ import annotations

import pytest

from quantlab.backtest.accounting import Ledger
from quantlab.core.types import TargetWeights


def _targets(weights: dict[str, float]) -> TargetWeights:
    return TargetWeights(asof="2020-01-31", weights=weights, strategy_id="test-0000000000")


def test_initial_capital_is_all_cash_no_positions():
    ledger = Ledger(1000.0)
    assert ledger.cash == pytest.approx(1000.0)
    assert ledger.holdings() == {}


def test_rejects_non_positive_initial_capital():
    with pytest.raises(ValueError):
        Ledger(0.0)
    with pytest.raises(ValueError):
        Ledger(-100.0)


def test_rebalance_to_long_only_invests_all_capital_no_cost():
    ledger = Ledger(1000.0)
    ledger.rebalance_to(_targets({"A": 0.5, "B": 0.5}), {"A": 10.0, "B": 20.0}, cost_fraction=0.0)

    assert ledger.holdings()["A"] == pytest.approx(50.0)  # $500 / $10
    assert ledger.holdings()["B"] == pytest.approx(25.0)  # $500 / $20
    assert ledger.cash == pytest.approx(0.0, abs=1e-9)
    assert ledger.equity({"A": 10.0, "B": 20.0}) == pytest.approx(1000.0)


def test_rebalance_to_deducts_cost_before_sizing_positions():
    ledger = Ledger(1000.0)
    ledger.rebalance_to(_targets({"A": 1.0}), {"A": 10.0}, cost_fraction=0.01)

    # 1% of $1000 = $10 cost; $990 invested in A.
    assert ledger.holdings()["A"] == pytest.approx(99.0)
    assert ledger.cash == pytest.approx(0.0, abs=1e-9)
    assert ledger.equity({"A": 10.0}) == pytest.approx(990.0)


def test_rebalance_to_long_short_leaves_uninvested_fraction_in_cash():
    # Dollar-neutral book: sum(weights) == 0, so ALL equity sits in cash by
    # this Ledger's convention (no margin/financing modeled - see docstring).
    ledger = Ledger(1000.0)
    ledger.rebalance_to(_targets({"A": 1.0, "B": -1.0}), {"A": 10.0, "B": 20.0}, cost_fraction=0.0)

    assert ledger.holdings()["A"] == pytest.approx(100.0)
    assert ledger.holdings()["B"] == pytest.approx(-50.0)
    assert ledger.cash == pytest.approx(1000.0)
    assert ledger.equity({"A": 10.0, "B": 20.0}) == pytest.approx(1000.0)


def test_rebalance_to_replaces_the_book_entirely():
    ledger = Ledger(1000.0)
    ledger.rebalance_to(_targets({"A": 1.0}), {"A": 10.0}, cost_fraction=0.0)
    ledger.rebalance_to(_targets({"B": 1.0}), {"A": 11.0, "B": 5.0}, cost_fraction=0.0)

    assert "A" not in ledger.holdings()
    assert ledger.holdings()["B"] == pytest.approx(1100.0 / 5.0)


def test_rebalance_to_rejects_negative_cost_fraction():
    ledger = Ledger(1000.0)
    with pytest.raises(ValueError):
        ledger.rebalance_to(_targets({"A": 1.0}), {"A": 10.0}, cost_fraction=-0.01)


def test_rebalance_to_rejects_non_positive_fill_price():
    ledger = Ledger(1000.0)
    with pytest.raises(ValueError):
        ledger.rebalance_to(_targets({"A": 1.0}), {"A": 0.0}, cost_fraction=0.0)


def test_rebalance_to_missing_fill_price_raises_key_error():
    ledger = Ledger(1000.0)
    with pytest.raises(KeyError):
        ledger.rebalance_to(_targets({"A": 1.0}), {}, cost_fraction=0.0)


def test_equity_raises_key_error_for_held_ticker_missing_a_price():
    ledger = Ledger(1000.0)
    ledger.rebalance_to(_targets({"A": 1.0}), {"A": 10.0}, cost_fraction=0.0)
    with pytest.raises(KeyError):
        ledger.equity({})


def test_mark_prices_values_currently_held_book_separately_from_fill_prices():
    """The dual-price-dict design (engine.py's extreme-return cap): a
    currently-held name's `equity_before` valuation can differ from its
    entry price for a NEW target, in the same `rebalance_to` call."""
    ledger = Ledger(1000.0)
    ledger.rebalance_to(_targets({"A": 1.0}), {"A": 10.0}, cost_fraction=0.0)  # 100 shares of A

    # A's real market price is now 40.0 (a 4x "extreme" move, per the
    # caller's own guard) but the caller wants equity_before computed as if
    # A were still worth only 10.0 (capped at 0% return), while B (a BRAND
    # NEW target) enters at its real market price of 5.0.
    ledger.rebalance_to(
        _targets({"B": 1.0}),
        fill_prices={"A": 40.0, "B": 5.0},
        cost_fraction=0.0,
        mark_prices={"A": 10.0},
    )

    # equity_before was capped at 1000.0 (A valued at its entry price, not
    # the real 40.0), so B is sized off $1000, not off a spuriously-inflated
    # $4000.
    assert ledger.holdings()["B"] == pytest.approx(200.0)  # $1000 / $5


def test_force_exit_credits_cash_and_removes_the_position():
    ledger = Ledger(1000.0)
    ledger.rebalance_to(_targets({"A": 1.0}), {"A": 10.0}, cost_fraction=0.0)  # 100 shares

    proceeds = ledger.force_exit("A", last_price=8.0, haircut=0.0, reason="price_series_ended")

    assert proceeds == pytest.approx(800.0)
    assert "A" not in ledger.holdings()
    assert ledger.cash == pytest.approx(800.0)


def test_force_exit_applies_haircut_to_proceeds():
    ledger = Ledger(1000.0)
    ledger.rebalance_to(_targets({"A": 1.0}), {"A": 10.0}, cost_fraction=0.0)  # 100 shares

    proceeds = ledger.force_exit("A", last_price=8.0, haircut=0.25, reason="delisting")

    assert proceeds == pytest.approx(600.0)  # 100 * 8.0 * 0.75
    assert ledger.cash == pytest.approx(600.0)


def test_force_exit_unknown_ticker_raises_key_error():
    ledger = Ledger(1000.0)
    with pytest.raises(KeyError):
        ledger.force_exit("ZZZ", last_price=1.0, haircut=0.0, reason="x")


def test_force_exit_rejects_haircut_outside_unit_interval():
    ledger = Ledger(1000.0)
    ledger.rebalance_to(_targets({"A": 1.0}), {"A": 10.0}, cost_fraction=0.0)
    with pytest.raises(ValueError):
        ledger.force_exit("A", last_price=8.0, haircut=1.5, reason="x")


def test_force_exit_rejects_empty_reason():
    ledger = Ledger(1000.0)
    ledger.rebalance_to(_targets({"A": 1.0}), {"A": 10.0}, cost_fraction=0.0)
    with pytest.raises(ValueError):
        ledger.force_exit("A", last_price=8.0, haircut=0.0, reason="")


def test_entry_price_tracks_the_most_recent_fill():
    ledger = Ledger(1000.0)
    ledger.rebalance_to(_targets({"A": 1.0}), {"A": 10.0}, cost_fraction=0.0)
    assert ledger.entry_price("A") == pytest.approx(10.0)


def test_entry_price_unknown_ticker_raises_key_error():
    ledger = Ledger(1000.0)
    with pytest.raises(KeyError):
        ledger.entry_price("ZZZ")


def test_snapshot_reports_positions_cash_and_equity():
    ledger = Ledger(1000.0)
    ledger.rebalance_to(_targets({"A": 0.5, "B": 0.5}), {"A": 10.0, "B": 20.0}, cost_fraction=0.0)

    snap = ledger.snapshot("2020-01-31", {"A": 12.0, "B": 18.0})

    assert snap.cash == pytest.approx(0.0, abs=1e-9)
    assert snap.positions["A"].qty == pytest.approx(50.0)
    assert snap.positions["A"].avg_cost == pytest.approx(10.0)
    assert snap.equity == pytest.approx(50.0 * 12.0 + 25.0 * 18.0)


def test_mark_is_read_only_and_does_not_mutate_state():
    ledger = Ledger(1000.0)
    ledger.rebalance_to(_targets({"A": 1.0}), {"A": 10.0}, cost_fraction=0.0)

    ledger.mark("2020-01-31", {"A": 999.0})

    assert ledger.holdings()["A"] == pytest.approx(100.0)
    assert ledger.entry_price("A") == pytest.approx(10.0)


def test_holdings_returns_a_defensive_copy():
    ledger = Ledger(1000.0)
    ledger.rebalance_to(_targets({"A": 1.0}), {"A": 10.0}, cost_fraction=0.0)

    snapshot_dict = ledger.holdings()
    snapshot_dict["A"] = -12345.0

    assert ledger.holdings()["A"] == pytest.approx(100.0)
