"""Unit tests for src/quantlab/validation/metrics.py. Parity against the old
repo's own implementation lives in tests/parity/test_metrics_parity.py; this
file is about correctness/behavior of the new metrics and of `summary()`.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from quantlab.validation import metrics
from tests._validation_fixtures import Exploding, make_backtest_result

# --- ported functions: light sanity coverage (parity test is the rigorous one) ---


def test_cagr_constant_monthly_return():
    r = 0.01
    dates = pd.date_range("2020-01-31", periods=25, freq="ME")
    equity = pd.Series((1 + r) ** np.arange(25), index=dates)
    assert metrics.cagr(equity) == pytest.approx((1 + r) ** 12 - 1, abs=1e-3)


def test_max_drawdown_exact_fifty_percent():
    equity = pd.Series(
        [1.0, 1.5, 2.0, 1.5, 1.0, 1.0, 1.0],
        index=pd.date_range("2020-01-31", periods=7, freq="ME"),
    )
    assert metrics.max_drawdown(equity) == pytest.approx(-0.5)


def test_annualized_vol_zero_for_constant_returns():
    returns = pd.Series([0.01] * 12, index=pd.date_range("2020-01-31", periods=12, freq="ME"))
    assert metrics.annualized_vol(returns) == pytest.approx(0.0)


def test_sharpe_ratio_zero_risk_free_matches_return_over_vol():
    returns = pd.Series(
        [0.01, 0.02, -0.01, 0.03], index=pd.date_range("2020-01-31", periods=4, freq="ME")
    )
    expected = (returns.mean() * 12) / (returns.std() * np.sqrt(12))
    assert metrics.sharpe_ratio(returns, risk_free_rate=0.0) == pytest.approx(expected)


# --- new metrics: hand-computed (acceptance criterion 7) ---


def test_calmar_hand_computed():
    equity = pd.Series(
        [1.0, 1.5, 2.0, 1.5, 1.0, 1.0, 1.0],
        index=pd.date_range("2020-01-31", periods=7, freq="ME"),
    )
    # equity[-1] == equity[0] == 1.0 -> total_return == 1.0 -> cagr == 0.
    assert metrics.calmar(equity) == pytest.approx(0.0)


def test_calmar_nan_when_no_drawdown():
    dates = pd.date_range("2020-01-31", periods=4, freq="ME")
    equity = pd.Series([1.0, 1.1, 1.2, 1.3], index=dates)
    assert math.isnan(metrics.calmar(equity))


def test_sortino_hand_computed_known_downside_deviation():
    returns = pd.Series(
        [0.02, -0.01, 0.03, -0.02], index=pd.date_range("2020-03-31", periods=4, freq="QE")
    )
    # annualized_return = mean * 4 = 0.02
    # downside = [0, -0.01, 0, -0.02]; mean(sq) = 0.000125; downside_dev = sqrt(0.000125)*2
    annualized_return = 0.02
    downside_dev = math.sqrt(0.000125) * 2
    expected = annualized_return / downside_dev
    assert metrics.sortino(returns, periods_per_year=4) == pytest.approx(expected)


def test_sortino_nan_when_never_negative():
    returns = pd.Series([0.01, 0.02, 0.03], index=pd.date_range("2020-01-31", periods=3, freq="ME"))
    assert math.isnan(metrics.sortino(returns))


def test_hit_rate_hand_computed():
    returns = pd.Series([0.01, -0.02, 0.03, 0.0, -0.01])
    assert metrics.hit_rate(returns) == pytest.approx(0.4)


def test_turnover_mean_hand_computed():
    turnover = pd.Series([0.1, 0.2, 0.3])
    assert metrics.turnover_mean(turnover) == pytest.approx(0.2)


def test_cost_drag_cagr_hand_computed():
    dates = pd.date_range("2020-01-01", "2021-01-01", freq="366D")
    gross_equity = pd.Series([1.0, 1.10], index=dates)
    net_equity = pd.Series([1.0, 1.05], index=dates)
    years = (dates[-1] - dates[0]).days / 365.25
    expected = 1.10 ** (1 / years) - 1 - (1.05 ** (1 / years) - 1)
    assert metrics.cost_drag_cagr(gross_equity, net_equity) == pytest.approx(expected)


def test_tracking_error_zero_when_identical():
    dates = pd.date_range("2020-01-31", periods=6, freq="ME")
    returns = pd.Series([0.01, -0.02, 0.03, 0.0, 0.02, -0.01], index=dates)
    assert metrics.tracking_error(returns, returns) == pytest.approx(0.0, abs=1e-12)


def test_information_ratio_zero_when_identical():
    dates = pd.date_range("2020-01-31", periods=6, freq="ME")
    returns = pd.Series([0.01, -0.02, 0.03, 0.0, 0.02, -0.01], index=dates)
    assert metrics.information_ratio(returns, returns) == pytest.approx(0.0, abs=1e-12)


def test_beta_one_for_series_equal_to_benchmark():
    dates = pd.date_range("2020-01-31", periods=6, freq="ME")
    returns = pd.Series([0.01, -0.02, 0.03, 0.0, 0.02, -0.01], index=dates)
    assert metrics.beta(returns, returns) == pytest.approx(1.0)


def test_beta_hand_computed_two_times_benchmark():
    dates = pd.date_range("2020-03-31", periods=2, freq="QE")
    benchmark = pd.Series([0.01, 0.03], index=dates)
    returns = pd.Series([0.02, 0.06], index=dates)  # exactly 2x benchmark
    assert metrics.beta(returns, benchmark) == pytest.approx(2.0)


def test_beta_nan_for_zero_variance_benchmark():
    dates = pd.date_range("2020-01-31", periods=4, freq="ME")
    benchmark = pd.Series([0.01, 0.01, 0.01, 0.01], index=dates)
    returns = pd.Series([0.02, -0.01, 0.03, 0.0], index=dates)
    assert math.isnan(metrics.beta(returns, benchmark))


def test_tracking_error_and_beta_align_on_common_dates():
    dates_a = pd.date_range("2020-01-31", periods=5, freq="ME")
    returns = pd.Series([0.01, 0.02, 0.03, 0.04, 0.05], index=dates_a)
    # Benchmark only has the last 4 dates, but matches `returns` exactly
    # there - common-dates alignment should still find TE == 0.
    benchmark = pd.Series([0.02, 0.03, 0.04, 0.05], index=dates_a[1:])
    te = metrics.tracking_error(returns, benchmark)
    assert te == pytest.approx(0.0, abs=1e-12)


# --- summary() ---


def _monthly_returns(values: list[float], start: str = "2020-01-31") -> pd.Series:
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="ME"))


def test_summary_reads_periods_per_year_from_provenance():
    net_returns = _monthly_returns([0.01, 0.02, -0.01, 0.03, 0.0, 0.02])
    result = make_backtest_result(net_returns=net_returns, rebalance_freq="weekly")
    s = metrics.summary(result)
    assert s.periods_per_year == 52


def test_summary_populates_all_fields_finite_where_expected():
    net_returns = _monthly_returns([0.02, -0.01, 0.03, 0.01, -0.02, 0.04])
    gross_returns = net_returns + 0.001
    benchmark_returns = _monthly_returns([0.01, 0.0, 0.02, 0.01, -0.01, 0.02])
    result = make_backtest_result(
        net_returns=net_returns, gross_returns=gross_returns, benchmark_returns=benchmark_returns
    )
    s = metrics.summary(result)
    assert s.periods_per_year == 12
    for field in (
        "net_cagr",
        "gross_cagr",
        "net_annualized_vol",
        "net_sharpe",
        "net_max_drawdown",
        "hit_rate",
        "turnover_mean",
        "cost_drag_cagr",
        "benchmark_cagr",
        "benchmark_sharpe",
        "tracking_error",
        "information_ratio",
        "beta",
    ):
        assert not math.isnan(getattr(s, field)), field


def test_summary_uses_benchmark_result_override_when_given():
    net_returns = _monthly_returns([0.02, -0.01, 0.03, 0.01, -0.02, 0.04])
    embedded_benchmark = _monthly_returns([0.0] * 6)
    result = make_backtest_result(net_returns=net_returns, benchmark_returns=embedded_benchmark)

    override_benchmark_returns = _monthly_returns([0.05] * 6)
    override_result = make_backtest_result(net_returns=override_benchmark_returns)

    s_default = metrics.summary(result)
    s_override = metrics.summary(result, override_result)
    assert s_default.benchmark_cagr != pytest.approx(s_override.benchmark_cagr)


def test_summary_does_not_touch_snapshots():
    import dataclasses

    net_returns = _monthly_returns([0.02, -0.01, 0.03, 0.01, -0.02, 0.04])
    result = make_backtest_result(net_returns=net_returns)
    exploding_result = dataclasses.replace(result, snapshots=Exploding())

    # Would raise AssertionError if summary() ever touched .snapshots.
    s = metrics.summary(exploding_result)
    assert not math.isnan(s.net_sharpe)


def test_metrics_summary_json_round_trip():
    # A non-constant benchmark, so `beta` is a real number rather than NaN
    # (the default zero-variance benchmark would make NaN != NaN break the
    # round-trip equality check below).
    net_returns = _monthly_returns([0.02, -0.01, 0.03, 0.01, -0.02, 0.04])
    benchmark_returns = _monthly_returns([0.01, 0.0, 0.02, 0.01, -0.01, 0.02])
    result = make_backtest_result(net_returns=net_returns, benchmark_returns=benchmark_returns)
    s = metrics.summary(result)

    import json

    round_tripped = metrics.MetricsSummary.from_json(json.loads(json.dumps(s.to_json())))
    assert round_tripped == s
