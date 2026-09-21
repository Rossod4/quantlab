"""Unit tests for src/quantlab/validation/walk_forward.py's own behavior
(the N-sleeve generalization). 2-sleeve numeric parity against the old
repo's `walk_forward_blend` lives in tests/parity/test_walk_forward_parity.py.
"""

from __future__ import annotations

import pandas as pd
import pytest

from quantlab.validation.walk_forward import (
    RankingAgreementResult,
    compound_to,
    compound_to_quarterly,
    walk_forward_blend,
    walk_forward_ranking_agreement,
)


def quarterly_dates(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2012-03-31", periods=n, freq="QE")


def alternating_series(n: int, high: float, low: float) -> pd.Series:
    values = [high if i % 2 == 0 else low for i in range(n)]
    return pd.Series(values, index=quarterly_dates(n))


# --- compound_to / compound_to_quarterly ---


def test_compound_to_quarterly_hand_computed():
    dates = pd.date_range("2020-01-31", periods=6, freq="ME")
    monthly = pd.Series([0.01, 0.02, 0.03, -0.01, 0.00, 0.02], index=dates)
    quarterly = compound_to_quarterly(monthly)
    assert quarterly.loc["2020-03-31"] == pytest.approx(1.01 * 1.02 * 1.03 - 1)
    assert quarterly.loc["2020-06-30"] == pytest.approx(0.99 * 1.00 * 1.02 - 1)


def test_compound_to_generalizes_to_other_frequencies():
    dates = pd.date_range("2020-01-31", periods=6, freq="ME")
    monthly = pd.Series([0.01, 0.02, 0.03, -0.01, 0.00, 0.02], index=dates)
    annual = compound_to(monthly, "YE")
    expected = (1.01 * 1.02 * 1.03 * 0.99 * 1.00 * 1.02) - 1
    assert annual.iloc[0] == pytest.approx(expected)


# --- N-sleeve walk_forward_blend (3 sleeves - the new generalization) ---


def test_walk_forward_three_sleeves_picks_dominant():
    n = 32
    dominant = alternating_series(n, 0.04, 0.0)
    weak_a = alternating_series(n, 0.01, -0.01)
    weak_b = alternating_series(n, -0.01, 0.01)

    weight_grid = [
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
        (0.5, 0.25, 0.25),
    ]
    result = walk_forward_blend(
        [dominant, weak_a, weak_b],
        weight_grid=weight_grid,
        train_years=5,
        test_years=1,
        periods_per_year=4,
        child_labels=("dominant", "weak_a", "weak_b"),
    )

    assert (result.chosen_weights["dominant"] == 1.0).all()
    assert (result.chosen_weights["weak_a"] == 0.0).all()
    assert (result.chosen_weights["weak_b"] == 0.0).all()
    pd.testing.assert_series_equal(result.oos_returns, dominant.iloc[20:])


def test_walk_forward_rejects_weight_grid_not_summing_to_one():
    n = 32
    a = alternating_series(n, 0.04, 0.0)
    b = alternating_series(n, 0.01, -0.01)
    with pytest.raises(ValueError):
        walk_forward_blend(
            [a, b], weight_grid=[(0.5, 0.6)], train_years=5, test_years=1, periods_per_year=4
        )


def test_walk_forward_rejects_weight_grid_wrong_arity():
    n = 32
    a = alternating_series(n, 0.04, 0.0)
    b = alternating_series(n, 0.01, -0.01)
    with pytest.raises(ValueError):
        walk_forward_blend(
            [a, b], weight_grid=[(1.0, 0.0, 0.0)], train_years=5, test_years=1, periods_per_year=4
        )


def test_walk_forward_keeps_partial_final_test_block():
    n = 23
    momentum = alternating_series(n, 0.04, 0.0)
    value = alternating_series(n, 0.01, -0.01)
    result = walk_forward_blend(
        [momentum, value],
        weight_grid=[(w, 1 - w) for w in (1.0, 0.75, 0.5, 0.25, 0.0)],
        train_years=5,
        test_years=1,
        periods_per_year=4,
    )
    assert len(result.oos_returns) == 3
    assert result.oos_returns.index[-1] == momentum.index[-1]


def test_walk_forward_too_few_periods_raises():
    n = 20
    momentum = alternating_series(n, 0.04, 0.0)
    value = alternating_series(n, 0.01, -0.01)
    with pytest.raises(ValueError):
        walk_forward_blend(
            [momentum, value],
            weight_grid=[(1.0, 0.0), (0.0, 1.0)],
            train_years=5,
            test_years=1,
            periods_per_year=4,
        )


def test_walk_forward_uses_only_common_dates():
    n = 32
    momentum = alternating_series(n, 0.04, 0.0)
    value = alternating_series(n, 0.01, -0.01).iloc[4:]
    result = walk_forward_blend(
        [momentum, value],
        weight_grid=[(w, 1 - w) for w in (1.0, 0.75, 0.5, 0.25, 0.0)],
        train_years=5,
        test_years=1,
        periods_per_year=4,
    )
    assert len(result.oos_returns) == 8
    pd.testing.assert_series_equal(result.oos_returns, momentum.iloc[24:])


def test_walk_forward_comparison_table_has_walk_forward_and_grid_columns():
    n = 32
    momentum = alternating_series(n, 0.04, 0.0)
    value = alternating_series(n, 0.01, -0.01)
    weight_grid = [(w, 1 - w) for w in (1.0, 0.75, 0.5, 0.25, 0.0)]
    result = walk_forward_blend(
        [momentum, value], weight_grid=weight_grid, train_years=5, test_years=1, periods_per_year=4
    )
    assert "Walk-Forward" in result.comparison.columns
    assert len(result.comparison.columns) == 1 + len(weight_grid)
    pd.testing.assert_series_equal(
        result.comparison["Walk-Forward"],
        result.comparison[result.comparison.columns[1]],
        check_names=False,
    )


# --- M09: per-step training Sharpes retained --------------------------------


def test_training_sharpes_retained_for_every_grid_point_and_step():
    n = 32
    momentum = alternating_series(n, 0.04, 0.0)
    value = alternating_series(n, 0.01, -0.01)
    weight_grid = [(w, 1 - w) for w in (1.0, 0.75, 0.5, 0.25, 0.0)]
    result = walk_forward_blend(
        [momentum, value],
        weight_grid=weight_grid,
        train_years=5,
        test_years=1,
        periods_per_year=4,
        child_labels=("momentum", "value"),
    )
    labels = [f"Fixed {w:.0%} momentum/{(1 - w):.0%} value" for w in (1.0, 0.75, 0.5, 0.25, 0.0)]

    assert list(result.training_sharpes.index) == list(result.chosen_weights.index)
    assert sorted(result.training_sharpes.columns) == sorted(labels)
    # The chosen weight at every step must be the ARGMAX of that step's own
    # training Sharpes among the grid (mirrors the tie-break the main loop
    # already applies) - this is the exact invariant
    # `no_chosen_step_has_nan_training_sharpe` and the ranking-agreement
    # check both depend on being real, not fabricated.
    for date, w in zip(result.chosen_weights.index, result.chosen_weights["momentum"], strict=True):
        chosen_label = f"Fixed {w:.0%} momentum/{(1 - w):.0%} value"
        row = result.training_sharpes.loc[date]
        assert row[chosen_label] == pytest.approx(row.max())


def test_no_chosen_step_has_nan_training_sharpe_true_on_a_clean_result():
    n = 32
    momentum = alternating_series(n, 0.04, 0.0)
    value = alternating_series(n, 0.01, -0.01)
    result = walk_forward_blend(
        [momentum, value],
        weight_grid=[(w, 1 - w) for w in (1.0, 0.75, 0.5, 0.25, 0.0)],
        train_years=5,
        test_years=1,
        periods_per_year=4,
    )
    assert result.no_chosen_step_has_nan_training_sharpe() is True


def test_no_chosen_step_has_nan_training_sharpe_none_when_field_absent():
    n = 32
    momentum = alternating_series(n, 0.04, 0.0)
    value = alternating_series(n, 0.01, -0.01)
    result = walk_forward_blend(
        [momentum, value],
        weight_grid=[(w, 1 - w) for w in (1.0, 0.75, 0.5, 0.25, 0.0)],
        train_years=5,
        test_years=1,
        periods_per_year=4,
    )
    stripped = result.__class__(
        oos_returns=result.oos_returns,
        chosen_weights=result.chosen_weights,
        comparison=result.comparison,
        child_labels=result.child_labels,
    )
    assert stripped.no_chosen_step_has_nan_training_sharpe() is None


def test_no_chosen_step_has_nan_training_sharpe_detects_a_zero_vol_first_grid_point():
    # A zero-return (zero-vol) FIRST grid point has a NaN training Sharpe
    # (std=0) and, per the module's own documented hazard, is seeded as
    # `best_sharpe` before any comparison runs - `s > NaN` is always False,
    # so it is NEVER beaten and stays "chosen" at every step regardless of
    # the other grid points' real performance.
    n = 32
    momentum = alternating_series(n, 0.04, 0.0)
    zero = pd.Series(0.0, index=momentum.index)
    result = walk_forward_blend(
        [zero, momentum],
        weight_grid=[(1.0, 0.0), (0.0, 1.0)],
        train_years=5,
        test_years=1,
        periods_per_year=4,
    )
    assert (result.chosen_weights["sleeve_0"] == 1.0).all()
    assert result.no_chosen_step_has_nan_training_sharpe() is False


# --- M09: ranking agreement under both cost conventions ---------------------


def test_ranking_agreement_perfect_when_netted_book_matches_blend_of_net():
    n = 32
    momentum = alternating_series(n, 0.04, 0.0)
    value = alternating_series(n, 0.01, -0.01)
    weight_grid = [(w, 1 - w) for w in (1.0, 0.75, 0.5, 0.25, 0.0)]
    result = walk_forward_blend(
        [momentum, value], weight_grid=weight_grid, train_years=5, test_years=1, periods_per_year=4
    )
    # A netted-book Sharpe series that agrees EXACTLY with comparison's own
    # blend-of-net Sharpe ranking (read straight off the fixture) - the
    # "both conventions agree" case.
    blend_of_net_sharpes = result.comparison.loc["Sharpe Ratio"]
    netted_book_sharpes = {
        w: blend_of_net_sharpes[f"Fixed {w[0]:.0%} sleeve_0/{w[1]:.0%} sleeve_1"]
        for w in weight_grid
    }

    agreement = walk_forward_ranking_agreement(result, netted_book_sharpes)

    assert isinstance(agreement, RankingAgreementResult)
    assert agreement.n_points == len(weight_grid)
    assert agreement.kendall_tau == pytest.approx(1.0)
    assert agreement.top_choice_agrees is True
    assert agreement.blend_of_net_ranking == agreement.netted_book_ranking


def test_ranking_agreement_detects_a_reversed_top_choice():
    n = 32
    momentum = alternating_series(n, 0.04, 0.0)
    value = alternating_series(n, 0.01, -0.01)
    weight_grid = [(w, 1 - w) for w in (1.0, 0.75, 0.5, 0.25, 0.0)]
    result = walk_forward_blend(
        [momentum, value], weight_grid=weight_grid, train_years=5, test_years=1, periods_per_year=4
    )
    blend_of_net_sharpes = result.comparison.loc["Sharpe Ratio"]
    ranking = blend_of_net_sharpes.drop("Walk-Forward").sort_values()
    # Reverse the ranking entirely: assign the WORST blend-of-net label's
    # rank position to the netted-book Sharpe of the BEST label, and so on.
    reversed_values = list(ranking.to_numpy())
    netted_by_label = dict(zip(ranking.index, reversed(reversed_values), strict=True))
    netted_book_sharpes = {
        w: netted_by_label[f"Fixed {w[0]:.0%} sleeve_0/{w[1]:.0%} sleeve_1"] for w in weight_grid
    }

    agreement = walk_forward_ranking_agreement(result, netted_book_sharpes)

    assert agreement.kendall_tau < 0
    assert agreement.top_choice_agrees is False


def test_ranking_agreement_raises_on_a_mismatched_grid():
    n = 32
    momentum = alternating_series(n, 0.04, 0.0)
    value = alternating_series(n, 0.01, -0.01)
    weight_grid = [(1.0, 0.0), (0.5, 0.5), (0.0, 1.0)]
    result = walk_forward_blend(
        [momentum, value], weight_grid=weight_grid, train_years=5, test_years=1, periods_per_year=4
    )
    incomplete = {(1.0, 0.0): 1.0}  # missing (0.5, 0.5) and (0.0, 1.0)

    with pytest.raises(ValueError):
        walk_forward_ranking_agreement(result, incomplete)
