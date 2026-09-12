"""Unit tests for src/quantlab/validation/monte_carlo.py."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantlab.validation.monte_carlo import block_bootstrap_paths, monte_carlo_summary


def _returns(n: int = 60, seed: int = 0) -> pd.Series:
    rng = np.random.default_rng(seed)
    values = rng.normal(loc=0.01, scale=0.04, size=n)
    return pd.Series(values, index=pd.date_range("2015-01-31", periods=n, freq="ME"))


# --- acceptance criterion 5: mean of bootstrapped means ~ sample mean ----


def test_mean_of_bootstrapped_means_matches_sample_mean_within_3se():
    returns = _returns(n=80, seed=1)
    n_paths = 2000
    paths = block_bootstrap_paths(returns, n_paths=n_paths, block_len=4.0, seed=123)

    per_path_means = paths.mean(axis=1)
    mean_of_means = per_path_means.mean()
    se = per_path_means.std(ddof=1) / np.sqrt(n_paths)

    assert abs(mean_of_means - returns.mean()) < 3 * se


# --- block_len=1 reduces to iid resampling -------------------------------


def test_block_len_one_matches_direct_iid_resample():
    from quantlab.validation.bootstrap import stationary_bootstrap_resample

    returns = _returns(n=40, seed=2)
    paths = block_bootstrap_paths(returns, n_paths=1, block_len=1.0, seed=99)

    expected = stationary_bootstrap_resample(returns.to_numpy(), 1.0, np.random.default_rng(99))
    np.testing.assert_array_equal(paths[0], expected)


def test_block_bootstrap_paths_shape_and_reproducibility():
    returns = _returns(n=30, seed=3)
    a = block_bootstrap_paths(returns, n_paths=10, block_len=3.0, seed=5)
    b = block_bootstrap_paths(returns, n_paths=10, block_len=3.0, seed=5)
    assert a.shape == (10, 30)
    np.testing.assert_array_equal(a, b)


# --- monte_carlo_summary ---------------------------------------------------


def test_monte_carlo_summary_percentiles_ordered_and_reproducible():
    returns = _returns(n=60, seed=4)
    result_a = monte_carlo_summary(
        returns, n_paths=300, block_len=3.0, seed=11, periods_per_year=12
    )
    result_b = monte_carlo_summary(
        returns, n_paths=300, block_len=3.0, seed=11, periods_per_year=12
    )

    assert result_a.cagr_p5 <= result_a.cagr_p50 <= result_a.cagr_p95
    assert result_a.max_drawdown_p5 <= result_a.max_drawdown_p50 <= result_a.max_drawdown_p95
    assert result_a.sharpe_p5 <= result_a.sharpe_p50 <= result_a.sharpe_p95
    assert result_a == result_b


def test_monte_carlo_summary_prob_drawdown_worse_is_between_zero_and_one():
    returns = _returns(n=60, seed=6)
    result = monte_carlo_summary(returns, n_paths=200, block_len=4.0, seed=13, periods_per_year=12)
    assert 0.0 <= result.prob_drawdown_worse_than_observed <= 1.0


def test_monte_carlo_summary_json_round_trips():
    import json

    returns = _returns(n=48, seed=8)
    result = monte_carlo_summary(returns, n_paths=100, block_len=2.0, seed=1, periods_per_year=12)
    payload = json.loads(json.dumps(result.to_json()))
    assert payload["n_paths"] == 100
    assert payload["cagr_p50"] == pytest.approx(result.cagr_p50)
