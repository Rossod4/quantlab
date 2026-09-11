"""Unit tests for src/quantlab/validation/rolling.py."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantlab.validation.rolling import (
    first_second_half_splits,
    rolling_window_metrics,
    subperiod_table,
)

# --- rolling_window_metrics (ported; parity fixtures also in
# tests/parity/test_metrics_parity.py) ---


def test_rolling_windows_count_and_index():
    returns = pd.Series(0.01, index=pd.date_range("2020-01-31", periods=24, freq="ME"))
    table = rolling_window_metrics(returns, window_years=1, periods_per_year=12)
    assert len(table) == 13
    assert table.index[0] == returns.index[11]
    assert table.index[-1] == returns.index[-1]


def test_rolling_window_metrics_values():
    returns = pd.Series(0.01, index=pd.date_range("2020-01-31", periods=24, freq="ME"))
    table = rolling_window_metrics(returns, window_years=1, periods_per_year=12)
    expected_growth = 1.01**11
    days = (table.index[0] - returns.index[0]).days
    expected_cagr = expected_growth ** (365.25 / days) - 1
    assert np.isclose(table["CAGR"].iloc[0], expected_cagr)
    assert (table["Max Drawdown"] == 0).all()
    assert np.allclose(table["Annualized Volatility"], 0, atol=1e-12)


def test_rolling_window_too_short_raises():
    returns = pd.Series(0.01, index=pd.date_range("2020-01-31", periods=10, freq="ME"))
    with pytest.raises(ValueError):
        rolling_window_metrics(returns, window_years=1, periods_per_year=12)


# --- first_second_half_splits ---


def test_first_second_half_splits_even_length():
    index = pd.date_range("2020-01-31", periods=10, freq="ME")
    splits = first_second_half_splits(index)
    assert splits["first_half"] == (index[0], index[4])
    assert splits["second_half"] == (index[5], index[9])


def test_first_second_half_splits_odd_length_puts_middle_in_second_half():
    index = pd.date_range("2020-01-31", periods=7, freq="ME")
    splits = first_second_half_splits(index)
    assert splits["first_half"] == (index[0], index[2])
    assert splits["second_half"] == (index[3], index[6])


def test_first_second_half_splits_too_short_raises():
    index = pd.date_range("2020-01-31", periods=1, freq="ME")
    with pytest.raises(ValueError):
        first_second_half_splits(index)


# --- subperiod_table ---


def _equity(returns: pd.Series) -> pd.Series:
    """Mirrors `BacktestResult`'s own convention (result.py docstring /
    `backtest/engine.py`'s `_equity_with_start`): a synthetic 1.0 point
    before the first return."""
    start_date = returns.index[0] - pd.Timedelta(days=1)
    equity = (1 + returns).cumprod()
    return pd.concat([pd.Series([1.0], index=[start_date]), equity])


def test_subperiod_table_growth_product_matches_full_period():
    # Acceptance criterion 4, fixed per quant-gate VERDICT.md cycle-1
    # finding 1(c): checked on the TABLE's own Growth column, not by
    # recomputing from the raw returns (which would pass even if
    # subperiod_table returned garbage elsewhere).
    returns = pd.Series(
        [0.02, -0.01, 0.03, 0.01, -0.02, 0.04, 0.0, 0.015],
        index=pd.date_range("2020-01-31", periods=8, freq="ME"),
    )
    equity = _equity(returns)
    splits = first_second_half_splits(returns.index)
    table = subperiod_table(returns, equity, splits, periods_per_year=12)

    total_growth = (1 + returns).prod()
    assert table.loc["first_half", "Growth"] * table.loc["second_half", "Growth"] == pytest.approx(
        total_growth, abs=1e-10
    )
    assert list(table.index) == ["first_half", "second_half"]
    assert not table["CAGR"].isna().any()


def test_subperiod_table_out_of_range_split_is_nan_not_error():
    returns = pd.Series(0.01, index=pd.date_range("2020-01-31", periods=6, freq="ME"))
    equity = _equity(returns)
    splits = {"future_regime": (pd.Timestamp("2030-01-01"), pd.Timestamp("2030-12-31"))}
    table = subperiod_table(returns, equity, splits, periods_per_year=12)
    assert table.loc["future_regime"].isna().all()


def test_subperiod_table_sees_the_subperiods_first_return_in_mdd():
    # Regression, quant-gate VERDICT.md cycle-1 finding 1's degenerate case:
    # a sub-period that opens with a -50% return must show -50% Max
    # Drawdown, not 0% (which `metrics.standard_metrics`'s
    # `(1 + returns).cumprod()`, with no leading 1.0, would report, since
    # r_0 then IS the curve's starting point and no peak precedes it).
    dates = pd.date_range("2020-01-31", periods=4, freq="ME")
    full_returns = pd.Series([0.0, -0.50, 0.10, 0.10], index=dates)
    equity = _equity(full_returns)
    # The sub-period under test is dates[1:] == [-0.50, 0.10, 0.10].
    splits = {"crash_window": (dates[1], dates[3])}
    table = subperiod_table(full_returns, equity, splits, periods_per_year=12)
    assert table.loc["crash_window", "Max Drawdown"] == pytest.approx(-0.50)


def test_subperiod_table_sees_the_subperiods_first_return_in_cagr():
    # Same shape, checking CAGR isn't blind to r_0 either (r_0 cancels out
    # of `equity[-1] / equity[0]` when equity has no leading 1.0 point).
    dates = pd.date_range("2020-01-31", periods=4, freq="ME")
    full_returns = pd.Series([0.0, -0.50, 0.10, 0.10], index=dates)
    equity = _equity(full_returns)
    splits = {"crash_window": (dates[1], dates[3])}
    table = subperiod_table(full_returns, equity, splits, periods_per_year=12)

    true_growth = 0.50 * 1.10 * 1.10  # (1 - 0.50) * 1.10 * 1.10
    years = (dates[3] - dates[0]).days / 365.25  # rebased from dates[0]'s equity point
    expected_cagr = true_growth ** (1 / years) - 1
    assert table.loc["crash_window", "CAGR"] == pytest.approx(expected_cagr)
    assert table.loc["crash_window", "Growth"] == pytest.approx(true_growth)


def test_subperiod_table_named_regime_hand_computed():
    dates = pd.date_range("2020-01-31", periods=4, freq="ME")
    returns = pd.Series([0.01, 0.02, -0.01, 0.03], index=dates)
    equity = _equity(returns)
    splits = {"middle_two": (dates[1], dates[2])}
    table = subperiod_table(returns, equity, splits, periods_per_year=12)
    # Rebased from dates[0]'s equity point (the boundary immediately before
    # the sub-period's first return at dates[1]), not from a bare 1.0 at
    # dates[1] - see `_rebased_subperiod_equity`.
    rebased = equity.loc[dates[0] : dates[2]] / equity.loc[dates[0]]
    expected_mdd = (rebased / rebased.cummax() - 1).min()
    assert table.loc["middle_two", "Max Drawdown"] == pytest.approx(expected_mdd)
