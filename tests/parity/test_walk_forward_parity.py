"""Golden parity test (M05 acceptance criterion 3): the new N-sleeve
`quantlab.validation.walk_forward.walk_forward_blend` against the original
two-sleeve ..\\MomentumValueStrategy\\src\\evaluation\\walk_forward.py
implementation, on the same synthetic alternating-sleeve fixtures the old
repo's own tests/test_walk_forward.py used.

Not explicitly named in the work packet's "In scope" test-file list (which
names only tests/parity/test_metrics_parity.py), but required by acceptance
criterion 3 - kept in tests/parity/ alongside the metrics parity test since
it has the same "import the old repo directly" shape, rather than folded
into tests/test_walk_forward.py which covers the new module's OWN
(N-sleeve) behavior.

Unlike the metrics parity test, the old `walk_forward.py` imports `from
src.evaluation.comparison import ...` - a real intra-package import - so
this file adds the old repo root to `sys.path` and imports normally
(rather than `importlib.util.spec_from_file_location`, which cannot resolve
that internal import).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_OLD_REPO_ROOT = Path(__file__).resolve().parents[3] / "MomentumValueStrategy"
if str(_OLD_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_OLD_REPO_ROOT))

from src.evaluation.walk_forward import walk_forward_blend as old_walk_forward_blend  # noqa: E402

from quantlab.validation.walk_forward import (  # noqa: E402
    walk_forward_blend as new_walk_forward_blend,
)

TOL = 1e-12
_LEGACY_WEIGHTS = (1.0, 0.75, 0.5, 0.25, 0.0)
_LEGACY_GRID = [(w, 1.0 - w) for w in _LEGACY_WEIGHTS]


def _quarterly_dates(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2012-03-31", periods=n, freq="QE")


def _alternating(n: int, high: float, low: float) -> pd.Series:
    values = [high if i % 2 == 0 else low for i in range(n)]
    return pd.Series(values, index=_quarterly_dates(n))


def _run_both(momentum: pd.Series, value: pd.Series):
    old = old_walk_forward_blend(momentum, value, train_years=5, test_years=1)
    new = new_walk_forward_blend(
        [momentum, value],
        weight_grid=_LEGACY_GRID,
        train_years=5,
        test_years=1,
        periods_per_year=4,
    )
    return old, new


def test_walk_forward_blend_parity_dominant_sleeve():
    n = 32
    momentum = _alternating(n, 0.04, 0.0)
    value = _alternating(n, 0.01, -0.01)
    old, new = _run_both(momentum, value)

    pd.testing.assert_series_equal(new.oos_returns, old.oos_returns, check_exact=False, atol=TOL)
    momentum_weight_new = new.chosen_weights.iloc[:, 0]
    pd.testing.assert_series_equal(
        momentum_weight_new, old.chosen_weights, check_exact=False, atol=TOL, check_names=False
    )


def test_walk_forward_blend_parity_dominance_flipped():
    n = 32
    momentum = _alternating(n, 0.01, -0.01)
    value = _alternating(n, 0.04, 0.0)
    old, new = _run_both(momentum, value)

    pd.testing.assert_series_equal(new.oos_returns, old.oos_returns, check_exact=False, atol=TOL)
    momentum_weight_new = new.chosen_weights.iloc[:, 0]
    pd.testing.assert_series_equal(
        momentum_weight_new, old.chosen_weights, check_exact=False, atol=TOL, check_names=False
    )


def test_walk_forward_blend_parity_partial_final_block():
    # 23 common quarters with 5 training years: the tail after quarter 20
    # is a 3-quarter PARTIAL block, which must be kept (not dropped) by
    # both implementations identically.
    n = 23
    momentum = _alternating(n, 0.04, 0.0)
    value = _alternating(n, 0.01, -0.01)
    old, new = _run_both(momentum, value)

    assert len(new.oos_returns) == len(old.oos_returns) == 3
    pd.testing.assert_series_equal(new.oos_returns, old.oos_returns, check_exact=False, atol=TOL)


def test_walk_forward_blend_parity_common_dates_alignment():
    # value is missing the first 4 quarters - both implementations must
    # shift their training/test indexing to the common window identically.
    n = 32
    momentum = _alternating(n, 0.04, 0.0)
    value = _alternating(n, 0.01, -0.01).iloc[4:]
    old, new = _run_both(momentum, value)

    assert len(new.oos_returns) == len(old.oos_returns)
    pd.testing.assert_series_equal(new.oos_returns, old.oos_returns, check_exact=False, atol=TOL)
