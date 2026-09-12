"""Unit tests for src/quantlab/validation/bootstrap.py's shared stationary
bootstrap primitive (used by both reality_check.py and monte_carlo.py -
see their own test files for tests through those higher-level APIs)."""

from __future__ import annotations

import numpy as np
import pytest

from quantlab.validation.bootstrap import (
    stationary_bootstrap_indices,
    stationary_bootstrap_resample,
)


def test_block_len_one_is_exactly_iid_resampling():
    # p_continue = 1 - 1/1 = 0, so every step's continuation draw
    # (uniform on [0, 1)) is never < 0 - every index comes from the
    # "restart" draw, i.e. plain i.i.d. resampling with replacement.
    rng = np.random.default_rng(42)
    indices = stationary_bootstrap_indices(50, block_len=1.0, rng=rng)

    rng_expected = np.random.default_rng(42)
    _ = rng_expected.random(50)  # continue_draws, drawn but never used at block_len=1
    expected = rng_expected.integers(0, 50, size=50)
    np.testing.assert_array_equal(indices, expected)


def test_indices_always_within_bounds():
    rng = np.random.default_rng(7)
    indices = stationary_bootstrap_indices(30, block_len=5.0, rng=rng)
    assert indices.min() >= 0
    assert indices.max() < 30
    assert len(indices) == 30


def test_large_block_len_tends_toward_one_contiguous_run():
    # A very large block_len makes the continuation probability close to 1,
    # so a resample of a small series should mostly be one contiguous
    # (wrapping) run from a single random start.
    rng = np.random.default_rng(1)
    n = 20
    indices = stationary_bootstrap_indices(n, block_len=1000.0, rng=rng)
    diffs = np.diff(indices)
    # Every step either continues (+1 mod n) or restarts; with p_continue
    # this close to 1, restarts should be rare over one resample.
    continuations = np.sum((diffs == 1) | (diffs == -(n - 1)))
    assert continuations >= n - 3


def test_empty_series_returns_empty_indices():
    rng = np.random.default_rng(0)
    assert len(stationary_bootstrap_indices(0, block_len=5.0, rng=rng)) == 0


def test_block_len_below_one_raises():
    rng = np.random.default_rng(0)
    with pytest.raises(ValueError):
        stationary_bootstrap_indices(10, block_len=0.5, rng=rng)


def test_resample_reproducible_with_same_seed():
    values = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    a = stationary_bootstrap_resample(values, 2.0, np.random.default_rng(3))
    b = stationary_bootstrap_resample(values, 2.0, np.random.default_rng(3))
    np.testing.assert_array_equal(a, b)


def test_resample_values_all_come_from_original():
    values = np.array([10.0, 20.0, 30.0])
    resampled = stationary_bootstrap_resample(values, 2.0, np.random.default_rng(5))
    assert set(resampled.tolist()) <= set(values.tolist())
