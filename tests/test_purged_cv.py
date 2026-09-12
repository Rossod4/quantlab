"""Unit tests for src/quantlab/validation/purged_cv.py."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantlab.validation.purged_cv import purged_kfold_splits, subperiod_oof_sharpe


def _index(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2020-01-31", periods=n, freq="ME")


def _assert_no_leakage(
    splits: list[tuple[np.ndarray, np.ndarray]], label_horizon: int, embargo: int
) -> None:
    """Shared leakage assertion: no training position's label window
    [j, j+label_horizon) may overlap its fold's test range, and no training
    position may fall in the `embargo` periods immediately after it."""
    for train_positions, test_positions in splits:
        test_start, test_end = int(test_positions.min()), int(test_positions.max()) + 1
        for j in train_positions:
            j = int(j)
            label_overlaps_test = j < test_end and j + label_horizon > test_start
            in_embargo_zone = test_end <= j < test_end + embargo
            assert not label_overlaps_test, (
                f"train position {j} leaks into test fold [{test_start}, {test_end}) "
                f"via its label window"
            )
            assert not in_embargo_zone, f"train position {j} sits inside the post-test embargo"


# --- purge/embargo leakage (positive) -----------------------------------


def test_no_train_index_within_purge_or_embargo_of_any_test_index():
    splits = purged_kfold_splits(_index(20), n_splits=4, embargo=2, label_horizon=3)
    _assert_no_leakage(splits, label_horizon=3, embargo=2)


def test_folds_partition_the_index():
    index = _index(23)  # not evenly divisible by n_splits
    splits = purged_kfold_splits(index, n_splits=4, embargo=1, label_horizon=2)
    all_test = np.concatenate([test for _train, test in splits])
    assert sorted(all_test.tolist()) == list(range(len(index)))
    assert len(set(all_test.tolist())) == len(index)  # no duplicates


# --- embargo=0, label_horizon=1 reduces to plain contiguous K-fold ------


def test_embargo_zero_and_label_horizon_one_reduces_to_plain_kfold():
    index = _index(20)
    splits = purged_kfold_splits(index, n_splits=4, embargo=0, label_horizon=1)
    for train_positions, test_positions in splits:
        expected_train = np.array(
            [p for p in range(len(index)) if p not in set(test_positions.tolist())]
        )
        np.testing.assert_array_equal(np.sort(train_positions), expected_train)


# --- negative test: the SAME assertion catches a deliberately unpurged split --


def test_assertion_detects_a_deliberately_unpurged_split():
    # A naive split that drops only the test fold itself, with NO purge and
    # NO embargo, while the leakage check demands label_horizon=3, embargo=2
    # - this MUST fail the same assertion used above, proving it actually
    # detects leakage rather than being vacuously true.
    index = _index(20)
    n = len(index)
    n_splits = 4
    fold_size = n // n_splits
    naive_splits = []
    for k in range(n_splits):
        start = k * fold_size
        end = start + fold_size if k < n_splits - 1 else n
        test_positions = np.arange(start, end)
        train_positions = np.array([p for p in range(n) if p not in set(test_positions.tolist())])
        naive_splits.append((train_positions, test_positions))

    with pytest.raises(AssertionError):
        _assert_no_leakage(naive_splits, label_horizon=3, embargo=2)


# --- validation ----------------------------------------------------------


def test_purged_kfold_splits_rejects_too_few_splits():
    with pytest.raises(ValueError):
        purged_kfold_splits(_index(20), n_splits=1, embargo=0)


def test_purged_kfold_splits_rejects_negative_embargo():
    with pytest.raises(ValueError):
        purged_kfold_splits(_index(20), n_splits=4, embargo=-1)


def test_purged_kfold_splits_rejects_zero_label_horizon():
    with pytest.raises(ValueError):
        purged_kfold_splits(_index(20), n_splits=4, embargo=0, label_horizon=0)


# --- subperiod_oof_sharpe ---------------------------------------------------


def test_subperiod_oof_sharpe_hand_computed_per_fold_and_mean():
    returns = pd.Series([0.01, 0.02, -0.01, 0.03, 0.00, 0.02, -0.02, 0.01], index=_index(8))
    splits = purged_kfold_splits(returns.index, n_splits=4, embargo=0, label_horizon=1)
    result = subperiod_oof_sharpe(returns, splits, periods_per_year=12)

    expected_fold_sharpes = []
    for _train, test in splits:
        fold = returns.iloc[test]
        expected_fold_sharpes.append(
            (fold.mean() * 12) / (fold.std() * (12**0.5)) if fold.std() != 0 else float("nan")
        )
    for actual, expected in zip(result.fold_sharpes, expected_fold_sharpes, strict=True):
        if pd.isna(expected):
            assert pd.isna(actual)
        else:
            assert actual == pytest.approx(expected)

    finite = [s for s in expected_fold_sharpes if not pd.isna(s)]
    assert result.mean_oof_sharpe == pytest.approx(sum(finite) / len(finite))


def test_subperiod_oof_sharpe_is_invariant_to_embargo_and_label_horizon():
    # quant-gate VERDICT.md M06 cycle-1 finding 4: subperiod_oof_sharpe
    # never reads the training positions, so purge/embargo cannot change
    # its value - pin that so nobody later assumes otherwise. Includes a
    # deliberately, fully-leaky "train = every row" split (the reviewer's
    # own reproduction) to make the point as starkly as possible.
    returns = pd.Series(
        [0.012, -0.02, 0.031, 0.00, 0.018, -0.011, 0.024, 0.005, 0.013, -0.017, 0.02, 0.009],
        index=_index(12),
    )
    baseline_splits = purged_kfold_splits(returns.index, n_splits=4, embargo=1, label_horizon=1)
    baseline = subperiod_oof_sharpe(returns, baseline_splits, periods_per_year=12)

    variant_splits = [
        purged_kfold_splits(returns.index, n_splits=4, embargo=0, label_horizon=1),
        purged_kfold_splits(returns.index, n_splits=4, embargo=3, label_horizon=1),
        purged_kfold_splits(returns.index, n_splits=4, embargo=1, label_horizon=6),
    ]
    for splits in variant_splits:
        result = subperiod_oof_sharpe(returns, splits, periods_per_year=12)
        assert result.mean_oof_sharpe == pytest.approx(baseline.mean_oof_sharpe, abs=1e-12)
        assert result.fold_sharpes == pytest.approx(baseline.fold_sharpes, abs=1e-12)

    # A deliberately fully-leaky split (every row in every fold's "training"
    # set, which subperiod_oof_sharpe never reads) still matches exactly.
    test_only_splits = [(np.arange(len(returns)), test) for _train, test in baseline_splits]
    leaky_result = subperiod_oof_sharpe(returns, test_only_splits, periods_per_year=12)
    assert leaky_result.mean_oof_sharpe == pytest.approx(baseline.mean_oof_sharpe, abs=1e-12)
