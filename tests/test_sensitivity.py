"""Unit tests for src/quantlab/validation/sensitivity.py, using a fake
injected runner - no real backtest runs offline (work packet requirement)."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import pytest

from quantlab.backtest.config import BacktestConfig
from quantlab.validation.sensitivity import sensitivity_grid


@dataclass
class _FakeResult:
    net_returns: pd.Series


def _backtest_config(
    rebalance_freq: str = "month_end", start: str = "2012-01-01", end: str = "2020-01-01"
) -> BacktestConfig:
    return BacktestConfig(
        start=start,
        end=end,
        strategy_config="configs/strategies/dummy.yaml",
        rebalance_freq=rebalance_freq,
    )


def _alternating(high: float, low: float, n: int = 12) -> pd.Series:
    values = [high if i % 2 == 0 else low for i in range(n)]
    return pd.Series(values, index=pd.date_range("2020-01-31", periods=n, freq="ME"))


def _two_point_returns_with_sharpe(
    target_sharpe: float, periods_per_year: int = 12, std: float = 0.05
) -> pd.Series:
    """A 2-observation return series whose `sharpe_ratio(..., periods_per_
    year=periods_per_year)` is exactly `target_sharpe` (up to floating
    point), for reproducing the quant-gate's exact planted-surface probe.
    Derivation: for two points, `pandas.Series.std()` (ddof=1) equals
    `abs(r1 - r2) / sqrt(2)`, so fixing that gap to `std * sqrt(2)` and the
    mean to `target_sharpe * std / sqrt(periods_per_year)` gives the
    desired ratio by construction."""
    mean = target_sharpe * std / (periods_per_year**0.5)
    half_gap = std * (2**0.5) / 2
    r1, r2 = mean + half_gap, mean - half_gap
    return pd.Series([r1, r2], index=pd.date_range("2020-01-31", periods=2, freq="ME"))


def test_sensitivity_grid_flat_surface_score_near_one():
    flat_returns = _alternating(0.02, 0.0)

    def runner(strategy_config, params, backtest_config):
        return _FakeResult(net_returns=flat_returns)

    result = sensitivity_grid(
        "configs/strategies/momentum.yaml",
        {"lookback_months": [9, 12, 15]},
        _backtest_config(),
        runner,
    )
    assert result.no_cliff_score == pytest.approx(1.0)
    assert len(result.trials) == 3
    assert len({t.strategy_id for t in result.trials}) == 3
    assert result.neighbourhood_size == 3
    assert result.neighbourhood_truncated is False


def test_sensitivity_grid_planted_cliff_score_is_low():
    def runner(strategy_config, params, backtest_config):
        lookback = params["lookback_months"]
        if lookback == 15:
            return _FakeResult(net_returns=_alternating(-0.02, 0.0))  # negative sharpe
        return _FakeResult(net_returns=_alternating(0.02, 0.0))  # positive sharpe

    result = sensitivity_grid(
        "configs/strategies/momentum.yaml",
        {"lookback_months": [9, 12, 15]},
        _backtest_config(),
        runner,
        base_point={"lookback_months": 12},
    )
    assert result.no_cliff_score < 0.5


def test_sensitivity_grid_base_point_defaults_to_middle_value():
    seen_params = []

    def runner(strategy_config, params, backtest_config):
        seen_params.append(dict(params))
        return _FakeResult(net_returns=_alternating(0.01, 0.0))

    result = sensitivity_grid(
        "configs/strategies/momentum.yaml",
        {"n_long": [30, 50, 70]},
        _backtest_config(),
        runner,
    )
    assert result.base_point == {"n_long": 50}


def test_sensitivity_grid_two_axes_covers_full_cartesian_product():
    def runner(strategy_config, params, backtest_config):
        return _FakeResult(net_returns=_alternating(0.01, 0.0))

    # n_long=[30, 50] is even-length, so base_point must be given explicitly
    # (quant-gate VERDICT.md cycle-1 finding 2) - see the even-length tests
    # below for the case where it's omitted.
    axes = {"lookback_months": [9, 12, 15], "n_long": [30, 50]}
    result = sensitivity_grid(
        "configs/strategies/momentum.yaml",
        axes,
        _backtest_config(),
        runner,
        base_point={"lookback_months": 12, "n_long": 30},
    )
    assert len(result.trials) == 3 * 2
    assert result.base_point == {"lookback_months": 12, "n_long": 30}


def test_sensitivity_grid_even_length_axis_requires_explicit_base_point():
    def runner(strategy_config, params, backtest_config):
        return _FakeResult(net_returns=_alternating(0.01, 0.0))

    with pytest.raises(ValueError):
        sensitivity_grid(
            "configs/strategies/momentum.yaml", {"n_long": [30, 50]}, _backtest_config(), runner
        )


def test_sensitivity_grid_even_length_axis_works_with_explicit_base_point():
    def runner(strategy_config, params, backtest_config):
        return _FakeResult(net_returns=_alternating(0.01, 0.0))

    result = sensitivity_grid(
        "configs/strategies/momentum.yaml",
        {"n_long": [30, 50]},
        _backtest_config(),
        runner,
        base_point={"n_long": 30},
    )
    assert result.base_point == {"n_long": 30}
    # A 2-element axis is always an edge - both remaining points fall in
    # the neighbourhood, and it is truncated (no 3-point interior exists).
    assert result.neighbourhood_size == 2
    assert result.neighbourhood_truncated is True


def test_sensitivity_grid_rejects_more_than_two_axes():
    def runner(strategy_config, params, backtest_config):
        return _FakeResult(net_returns=_alternating(0.01, 0.0))

    axes = {"a": [1, 2], "b": [1, 2], "c": [1, 2]}
    with pytest.raises(ValueError):
        sensitivity_grid("configs/strategies/momentum.yaml", axes, _backtest_config(), runner)


def test_sensitivity_grid_edge_base_point_is_marked_truncated():
    # Regression for quant-gate VERDICT.md cycle-1 finding 2's exact probe:
    # a fixed Sharpe surface over lookback_months in [6, 9, 12, 15, 18],
    # varying only which value is the base point.
    target_sharpes = {6: 0.10, 9: 0.90, 12: 1.00, 15: 1.05, 18: 1.02}

    def runner(strategy_config, params, backtest_config):
        lookback = params["lookback_months"]
        return _FakeResult(net_returns=_two_point_returns_with_sharpe(target_sharpes[lookback]))

    axes = {"lookback_months": [6, 9, 12, 15, 18]}

    edge_low = sensitivity_grid(
        "configs/strategies/momentum.yaml",
        axes,
        _backtest_config(),
        runner,
        base_point={"lookback_months": 6},
    )
    assert edge_low.neighbourhood_size == 2
    assert edge_low.neighbourhood_truncated is True
    assert edge_low.no_cliff_score == pytest.approx(-0.6, abs=1e-6)

    interior = sensitivity_grid(
        "configs/strategies/momentum.yaml",
        axes,
        _backtest_config(),
        runner,
        base_point={"lookback_months": 12},
    )
    assert interior.neighbourhood_size == 3
    assert interior.neighbourhood_truncated is False
    assert interior.no_cliff_score == pytest.approx(0.85, abs=1e-6)

    edge_high = sensitivity_grid(
        "configs/strategies/momentum.yaml",
        axes,
        _backtest_config(),
        runner,
        base_point={"lookback_months": 18},
    )
    assert edge_high.neighbourhood_size == 2
    assert edge_high.neighbourhood_truncated is True
    assert edge_high.no_cliff_score == pytest.approx(0.9710144927536232, abs=1e-6)


def test_sensitivity_grid_trial_id_differs_across_backtest_windows():
    # Quant-gate carried item 7: the SAME params grid rerun over a
    # DIFFERENT backtest window must get a DIFFERENT trial id, or M06's
    # trials registry would treat two genuinely different runs as repeats.
    def runner(strategy_config, params, backtest_config):
        return _FakeResult(net_returns=_alternating(0.01, 0.0))

    axes = {"lookback_months": [9, 12, 15]}
    result_a = sensitivity_grid(
        "configs/strategies/momentum.yaml",
        axes,
        _backtest_config(start="2012-01-01", end="2020-01-01"),
        runner,
    )
    result_b = sensitivity_grid(
        "configs/strategies/momentum.yaml",
        axes,
        _backtest_config(start="2015-01-01", end="2023-01-01"),
        runner,
    )
    ids_a = {t.params["lookback_months"]: t.strategy_id for t in result_a.trials}
    ids_b = {t.params["lookback_months"]: t.strategy_id for t in result_b.trials}
    for lookback in axes["lookback_months"]:
        assert ids_a[lookback] != ids_b[lookback]


def test_sensitivity_grid_trial_id_stable_for_the_same_window():
    def runner(strategy_config, params, backtest_config):
        return _FakeResult(net_returns=_alternating(0.01, 0.0))

    axes = {"lookback_months": [9, 12, 15]}
    config = _backtest_config(start="2012-01-01", end="2020-01-01")
    result_a = sensitivity_grid("configs/strategies/momentum.yaml", axes, config, runner)
    result_b = sensitivity_grid(
        "configs/strategies/momentum.yaml",
        axes,
        _backtest_config(start="2012-01-01", end="2020-01-01"),
        runner,
    )
    ids_a = {t.params["lookback_months"]: t.strategy_id for t in result_a.trials}
    ids_b = {t.params["lookback_months"]: t.strategy_id for t in result_b.trials}
    assert ids_a == ids_b


def test_sensitivity_grid_nan_neighbour_excluded_regardless_of_enumeration_order():
    # Quant-gate carried item 8: builtin max/min keep a NaN encountered
    # FIRST but skip one encountered LATER, so the pre-fix score depended
    # on which order the grid was enumerated in. Same value-to-Sharpe
    # mapping, axis order reversed (same neighbour SET, different
    # accumulation order) must give the identical score post-fix.
    target_sharpes = {9: float("nan"), 12: 1.0, 15: 0.5}
    zero_vol_returns = pd.Series(
        [0.01, 0.01], index=pd.date_range("2020-01-31", periods=2, freq="ME")
    )

    def runner(strategy_config, params, backtest_config):
        lookback = params["lookback_months"]
        if lookback == 9:
            return _FakeResult(net_returns=zero_vol_returns)  # NaN Sharpe
        return _FakeResult(net_returns=_two_point_returns_with_sharpe(target_sharpes[lookback]))

    ascending = sensitivity_grid(
        "configs/strategies/momentum.yaml",
        {"lookback_months": [9, 12, 15]},
        _backtest_config(),
        runner,
        base_point={"lookback_months": 12},
    )
    descending = sensitivity_grid(
        "configs/strategies/momentum.yaml",
        {"lookback_months": [15, 12, 9]},
        _backtest_config(),
        runner,
        base_point={"lookback_months": 12},
    )

    assert ascending.nan_points == 1
    assert descending.nan_points == 1
    assert ascending.neighbourhood_size == 3  # includes the NaN point itself
    # median([0.5, 1.0]) = 0.75, spread = 0.5 -> 1 - 0.5/0.75
    expected_score = 1 - 0.5 / 0.75
    assert ascending.no_cliff_score == pytest.approx(expected_score, abs=1e-9)
    assert descending.no_cliff_score == pytest.approx(expected_score, abs=1e-9)
    assert ascending.no_cliff_score == pytest.approx(descending.no_cliff_score, abs=1e-12)


def test_sensitivity_grid_trials_record_params_and_sharpe():
    def runner(strategy_config, params, backtest_config):
        return _FakeResult(net_returns=_alternating(0.02, 0.0))

    result = sensitivity_grid(
        "configs/strategies/momentum.yaml",
        {"lookback_months": [9, 12, 15]},
        _backtest_config(),
        runner,
    )
    lookbacks = sorted(t.params["lookback_months"] for t in result.trials)
    assert lookbacks == [9, 12, 15]
    for trial in result.trials:
        assert trial.net_sharpe == pytest.approx(result.trials[0].net_sharpe)
