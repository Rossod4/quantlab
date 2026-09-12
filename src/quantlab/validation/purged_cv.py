"""Purged, embargoed K-fold SPLITTING utility - López de Prado, "Advances in
Financial Machine Learning" (2018), ch. 7 - plus `subperiod_oof_sharpe`, the
statistic THIS PACKET'S fixed-parameter strategies can actually use it for
today.

quant-gate VERDICT.md M06 cycle-1 finding 4 (BINDING - read before using
either function below): a genuine purged CV needs something to REFIT per
training fold and score on the held-out fold, so that the purge/embargo
protect against a real leakage channel (the fitted model's own training
labels overlapping the test window). QuantLab's current strategies
(momentum, value_composite, blend) have FIXED, not fitted, parameters - the
work packet's own `cv_sharpe(returns, splits)` signature (now
`subperiod_oof_sharpe`) never receives the training data at all, only the
already-realized test-fold returns. There is therefore NOTHING for
`purged_kfold_splits`'s purge/embargo to protect here: `subperiod_oof_sharpe`
is the mean Sharpe over N CONTIGUOUS SUB-PERIODS of a strategy that was not
refit per fold, and its value is PROVABLY INVARIANT to `embargo`/
`label_horizon` (test file: `test_subperiod_oof_sharpe_is_invariant_to_
embargo_and_label_horizon`) because those parameters only change which
TRAINING positions are dropped - a value this statistic never reads.

Gate-measured concretely: on one 144-month series, `embargo=1` (shipped),
`embargo=40`, `label_horizon=24`, and even a deliberately fully-leaky
"train = every row" split all produced IDENTICAL `subperiod_oof_sharpe` to
ten decimal places. An earlier version of this module named the statistic
`cv_sharpe` and its report-card gate `purged_cv_mean_oof_sharpe`, with a
reason string claiming "purged/embargoed out-of-sample evidence" - that
overclaimed what a contiguous-sub-period consistency check on a
non-refit strategy actually is. `purged_kfold_splits` ITSELF is unaffected
by this finding (its own construction is independently verified correct -
see quant-gate REVIEW.md/VERDICT.md's "Verified correct" sections) and is
KEPT as a tested utility for a FUTURE milestone that refits a strategy's
parameters per training fold (e.g. a genuine purged CV over the sensitivity
grid: fit = pick the best grid point per training fold, score the held-out
fold - carried to post-v1 in QUANT-NOTES, NOT built in this packet).

Why a return series needs purging/embargo AT ALL, for that future caller
(stated explicitly, since ch. 7's own motivating example is a
supervised-learning LABEL, not a realized return): an out-of-fold Sharpe
computed naively from contiguous chronological folds can still leak if a
training fold's own signal/label depends on information whose effective
window reaches into the adjacent test fold - the walk-forward module's own
module docstring makes the parallel point about why `walk_forward_blend`
needs NO purge (its inputs are already-realized, non-overlapping period
returns) while a K-fold split, which can place a test fold in the MIDDLE of
the series with training data on both sides, is exposed to exactly the
overlap ch. 7 warns about on whichever side a non-trivial label window
exists.

`label_horizon` (keyword-only, default 1) makes that window explicit:
observation `i` is treated as carrying a label spanning periods
`[i, i + label_horizon)` - `label_horizon=1` (the default) means each
observation's label is entirely its own period, so PURGING becomes a no-op
and only `embargo` can still remove anything - this is exactly acceptance
criterion 3's "with embargo=0 and label horizon 1 it reduces to plain
contiguous K-fold". A future fitted-strategy caller whose signal genuinely
has a multi-period label window (e.g. a 12-month momentum score's forward
return) should pass the true `label_horizon` to get real purging.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from quantlab.validation.metrics import MONTHS_PER_YEAR, sharpe_ratio


def purged_kfold_splits(
    index: pd.Index, n_splits: int, embargo: int, *, label_horizon: int = 1
) -> list[tuple[np.ndarray, np.ndarray]]:
    """`n_splits` CONTIGUOUS, non-overlapping test folds partitioning
    `index` in order (as equal as `len(index) // n_splits` allows, with any
    remainder folded into the LAST test fold), each paired with a training
    set that PURGES any observation whose label window
    `[j, j + label_horizon)` overlaps the test fold's own position range,
    and further EMBARGOES the `embargo` positions immediately following the
    test fold (independent of `label_horizon` - see module docstring).

    Returns a list of `(train_positions, test_positions)` INTEGER POSITION
    arrays (not index labels), one pair per fold, in fold order. Test folds
    always PARTITION `index` exactly (every position appears in exactly one
    fold's test set); training sets may be empty for a fold near either end
    of a short series with a large `label_horizon`/`embargo`.
    """
    n = len(index)
    if n_splits < 2:
        raise ValueError(f"n_splits must be >= 2, got {n_splits}")
    if n < n_splits:
        raise ValueError(f"need at least n_splits={n_splits} observations, got {n}")
    if embargo < 0:
        raise ValueError(f"embargo must be >= 0, got {embargo}")
    if label_horizon < 1:
        raise ValueError(f"label_horizon must be >= 1, got {label_horizon}")

    fold_size = n // n_splits
    bounds: list[tuple[int, int]] = []
    start = 0
    for k in range(n_splits):
        end = start + fold_size if k < n_splits - 1 else n
        bounds.append((start, end))
        start = end

    all_positions = np.arange(n)
    splits: list[tuple[np.ndarray, np.ndarray]] = []
    for test_start, test_end in bounds:
        test_positions = all_positions[test_start:test_end]

        # Purge: training position j is dropped if its label window
        # [j, j + label_horizon) intersects [test_start, test_end) - this
        # excludes positions in [purge_from, test_end), which already
        # contains the test fold itself.
        purge_from = max(0, test_start - (label_horizon - 1))
        # Embargo: the `embargo` positions immediately after the test fold,
        # independent of label_horizon.
        embargo_to = min(n, test_end + embargo)

        train_mask = np.ones(n, dtype=bool)
        train_mask[purge_from:embargo_to] = False
        train_positions = all_positions[train_mask]

        splits.append((train_positions, test_positions))

    return splits


@dataclass(frozen=True)
class SubperiodOOFResult:
    """Named `...OOF...` (out-of-fold) for continuity with `purged_kfold_
    splits`'s fold structure, NOT as a claim of leakage-controlled
    out-of-sample evidence - see module docstring. `mean_oof_sharpe` is the
    plain arithmetic mean of `fold_sharpes`."""

    fold_sharpes: list[float]
    mean_oof_sharpe: float
    periods_per_year: int

    def to_json(self) -> dict[str, Any]:
        return {
            "fold_sharpes": list(self.fold_sharpes),
            "mean_oof_sharpe": self.mean_oof_sharpe,
            "periods_per_year": self.periods_per_year,
        }


def subperiod_oof_sharpe(
    returns: pd.Series,
    splits: list[tuple[np.ndarray, np.ndarray]],
    periods_per_year: int = MONTHS_PER_YEAR,
) -> SubperiodOOFResult:
    """Mean Sharpe over the N contiguous test sub-periods `splits` carves
    out of `returns` (each fold's TEST positions only - `_train_positions`
    is accepted for signature compatibility with `purged_kfold_splits`'s
    output but is NEVER READ, which is exactly why this statistic cannot
    detect leakage - see module docstring, BINDING).

    `mean_oof_sharpe` is the plain arithmetic mean of `fold_sharpes`,
    ignoring NaN folds (e.g. a test fold too short/flat for a defined
    Sharpe); NaN if every fold is NaN. This is a CONSISTENCY check ("is
    performance stable across contiguous sub-periods of the same,
    fixed-parameter strategy"), not a purged cross-validation - the value is
    invariant to `splits`' `embargo`/`label_horizon` by construction.
    """
    fold_sharpes = []
    for _train_positions, test_positions in splits:
        fold_returns = returns.iloc[test_positions]
        fold_sharpes.append(sharpe_ratio(fold_returns, periods_per_year=periods_per_year))

    finite = [s for s in fold_sharpes if pd.notna(s)]
    mean_oof_sharpe = float(np.mean(finite)) if finite else float("nan")

    return SubperiodOOFResult(
        fold_sharpes=fold_sharpes,
        mean_oof_sharpe=mean_oof_sharpe,
        periods_per_year=periods_per_year,
    )
