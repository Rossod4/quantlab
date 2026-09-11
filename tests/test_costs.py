"""Tests for backtest/costs.py.

`apply_transaction_costs`/`corwin_schultz_spread`/`monthly_borrow_fee` are
verbatim ports - golden numbers here are the SAME ones the old repo's own
tests/test_costs.py and tests/test_long_short.py use (see each test's
docstring/comment), not independently re-derived, since the whole point is
proving the ported arithmetic didn't change."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantlab.backtest.costs import (
    apply_transaction_costs,
    borrow_fee_for_period,
    compute_turnover,
    corwin_schultz_spread,
    monthly_borrow_fee,
    transaction_cost_fraction,
    weight_deltas,
)

# -- compute_turnover (generalized) ------------------------------------------


def _equal_weights(tickers: list[str]) -> dict[str, float]:
    return dict.fromkeys(tickers, 1.0 / len(tickers)) if tickers else {}


@pytest.mark.parametrize(
    ("old_tickers", "new_tickers"),
    [
        (["A", "B", "C"], ["A", "B", "C"]),  # full overlap -> 0
        (["A", "B", "C"], ["D", "E", "F"]),  # no overlap -> 1
        (["A", "B", "C", "D"], ["A", "B", "E", "F"]),  # partial -> 0.5
    ],
)
def test_turnover_generalisation_matches_old_formula_on_equal_weights(old_tickers, new_tickers):
    """Proof (work packet acceptance criterion 3): for two EQUAL-WEIGHT
    ticker sets of the SAME size N, `0.5 * sum(|w_new - w_old|)` reduces
    algebraically to the old repo's set-based `1 - |old ∩ new| / N`.

    Let k = |old ∩ new|. Every overlapping name has |diff| = 0 (same
    weight, unchanged). Every old-only name has |diff| = 1/N (it had 1/N,
    now 0); every new-only name has |diff| = 1/N (it had 0, now 1/N). There
    are (N - k) of each, so sum(|diff|) = 2*(N-k)/N, and
    0.5 * sum(|diff|) = (N-k)/N = 1 - k/N - exactly the old formula.
    """
    old_weights = _equal_weights(old_tickers)
    new_weights = _equal_weights(new_tickers)
    n = len(new_tickers)
    overlap = len(set(old_tickers) & set(new_tickers))
    old_formula = 1 - (overlap / n)

    assert compute_turnover(old_weights, new_weights) == pytest.approx(old_formula, abs=1e-12)


def test_turnover_empty_old_portfolio_is_full_turnover():
    """Special case (not the general 0.5*sum(|delta|) formula - see
    compute_turnover's docstring): the very first rebalance of a run has no
    prior book to compare against, and the old repo hardcodes turnover=1.0
    here regardless of book size - required for 1e-10 parity on period 1."""
    new_weights = _equal_weights(["A", "B", "C"])
    assert compute_turnover({}, new_weights) == pytest.approx(1.0)


def test_turnover_empty_new_portfolio_is_zero():
    """Mirror special case: old repo's `top_n == len(new_portfolio) == 0`
    branch returns 0.0 regardless of the old book's size."""
    old_weights = _equal_weights(["A", "B", "C"])
    assert compute_turnover(old_weights, {}) == pytest.approx(0.0)


def test_turnover_is_zero_for_identical_weights():
    weights = {"A": 0.6, "B": -0.4}
    assert compute_turnover(weights, dict(weights)) == pytest.approx(0.0)


def test_weight_deltas_is_signed_new_minus_old_over_the_union():
    deltas = weight_deltas({"A": 1.0, "B": 0.5}, {"A": 0.5, "C": 0.5})
    assert deltas == pytest.approx({"A": -0.5, "B": -0.5, "C": 0.5})


def test_netted_book_turnover_is_lower_than_sum_of_per_sleeve_turnovers():
    """Work packet's "Carried from the M03 verdict" item 1 test: "a name
    long in one sleeve and short in the other" - here, momentum newly buys
    AAA (0 -> +0.6 within its own sleeve) in the SAME period value newly
    shorts it (0 -> -0.6), driven by unrelated signals. Blended (50/50),
    AAA's weight is 0 both before AND after (0.5*0.6 + 0.5*(-0.6) = 0 in
    both periods) - the ENGINE, which diffs consecutive already-blended
    `TargetWeights`, sees zero turnover for this name and charges nothing,
    while the OLD REPO's per-sleeve convention would charge both sleeves'
    real, independent 0.6-weight trades. This is the exact mechanism behind
    engine.py's documented divergence: netting is a real cost saving the
    engine now takes credit for, where the old repo did not."""
    momentum_old, momentum_new = {"AAA": 0.0}, {"AAA": 0.6}
    value_old, value_new = {"AAA": 0.0}, {"AAA": -0.6}
    blended_old = {"AAA": 0.5 * momentum_old["AAA"] + 0.5 * value_old["AAA"]}
    blended_new = {"AAA": 0.5 * momentum_new["AAA"] + 0.5 * value_new["AAA"]}

    netted_turnover = compute_turnover(blended_old, blended_new)
    momentum_turnover = compute_turnover(momentum_old, momentum_new)
    value_turnover = compute_turnover(value_old, value_new)
    per_sleeve_turnover = 0.5 * momentum_turnover + 0.5 * value_turnover

    assert netted_turnover == pytest.approx(0.0)
    assert per_sleeve_turnover == pytest.approx(0.30)
    assert netted_turnover < per_sleeve_turnover


# -- apply_transaction_costs (verbatim port) ---------------------------------


def test_apply_transaction_costs_exact_bps_subtraction():
    net = apply_transaction_costs(gross_return=0.05, turnover=1.0, one_way_cost_bps=10.0)
    assert net == pytest.approx(0.05 - 0.002)


def test_apply_transaction_costs_half_turnover():
    net = apply_transaction_costs(gross_return=0.02, turnover=0.5, one_way_cost_bps=10.0)
    assert net == pytest.approx(0.02 - 0.001)


def test_apply_transaction_costs_zero_turnover_no_cost():
    assert apply_transaction_costs(0.05, 0.0, 10.0) == pytest.approx(0.05)


# -- transaction_cost_fraction (generalization) ------------------------------


def test_transaction_cost_fraction_matches_apply_transaction_costs_for_flat_bps():
    old_weights = {"A": 0.5, "B": 0.5}
    new_weights = {"A": 0.5, "C": 0.5}
    turnover = compute_turnover(old_weights, new_weights)
    cost_via_apply = 0.10 - apply_transaction_costs(0.10, turnover, 10.0)

    cost_via_fraction = transaction_cost_fraction(old_weights, new_weights, 10.0)

    assert cost_via_fraction == pytest.approx(cost_via_apply, abs=1e-12)


def test_transaction_cost_fraction_supports_per_ticker_bps():
    old_weights = {"A": 1.0}
    new_weights = {"B": 1.0}
    per_ticker = {"A": 20.0, "B": 5.0}

    cost = transaction_cost_fraction(old_weights, new_weights, per_ticker)

    # Sell all of A (delta -1.0, 20bps) + buy all of B (delta +1.0, 5bps).
    expected = 1.0 * 20.0 / 10_000 + 1.0 * 5.0 / 10_000
    assert cost == pytest.approx(expected)


def test_transaction_cost_fraction_missing_ticker_in_per_ticker_dict_is_zero_cost():
    cost = transaction_cost_fraction({}, {"A": 1.0}, {})
    assert cost == pytest.approx(0.0)


# -- corwin_schultz_spread (verbatim port) -----------------------------------


def test_corwin_schultz_spread_is_zero_for_a_zero_range_series():
    """A ticker that never trades outside a single fixed price has zero
    high-low range every day, so the estimated spread is 0 (alpha floored
    at 0), not NaN or negative."""
    high = pd.Series([100.0] * 10)
    low = pd.Series([100.0] * 10)
    assert corwin_schultz_spread(high, low) == pytest.approx(0.0)


def test_corwin_schultz_spread_is_positive_for_a_widening_range():
    high = pd.Series([101.0, 102.0, 103.0, 104.0, 105.0])
    low = pd.Series([99.0, 97.0, 95.0, 93.0, 91.0])
    spread = corwin_schultz_spread(high, low)
    assert spread > 0
    assert np.isfinite(spread)


def test_corwin_schultz_spread_returns_nan_for_insufficient_history():
    assert np.isnan(corwin_schultz_spread(pd.Series([100.0]), pd.Series([99.0])))


# -- borrow fee (verbatim port + generalization) -----------------------------


def test_monthly_borrow_fee_matches_old_repo_dollar_neutral_example():
    # Old repo docstring example: dollar-neutral (short_exposure=1.0) at
    # 30bps/year pays 2.5bps of capital per month = 0.00025 as a fraction.
    assert monthly_borrow_fee(1.0, 30.0) == pytest.approx(0.00025)


def test_monthly_borrow_fee_matches_old_repo_130_30_example():
    # 130/30 book (short_exposure=0.3) at 30bps/year pays 0.75bps/month =
    # 0.000075 as a fraction.
    assert monthly_borrow_fee(0.3, 30.0) == pytest.approx(0.000075)


def test_borrow_fee_for_period_reduces_to_monthly_borrow_fee_at_12_periods_per_year():
    assert borrow_fee_for_period(1.0, 30.0, periods_per_year=12) == pytest.approx(
        monthly_borrow_fee(1.0, 30.0)
    )


def test_borrow_fee_for_period_scales_with_period_length():
    # A weekly rebalance (52/yr) charges 1/52 of the annual rate per period,
    # a smaller per-period charge than the monthly (1/12) convention.
    weekly = borrow_fee_for_period(1.0, 30.0, periods_per_year=52)
    monthly = borrow_fee_for_period(1.0, 30.0, periods_per_year=12)
    assert weekly < monthly
    assert weekly == pytest.approx(1.0 * 30.0 / 52 / 10_000)
