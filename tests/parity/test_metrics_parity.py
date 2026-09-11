"""Golden parity tests (M05 acceptance criterion 2): quantlab.validation.
metrics's ported functions (`cagr`, `annualized_vol`, `sharpe_ratio`,
`max_drawdown`) against the ORIGINAL implementation in
..\\MomentumValueStrategy\\src\\evaluation\\metrics.py, on the same synthetic
series the old repo's own tests/test_metrics.py used.

Chosen approach (the work packet offers two): import the old repo's module
directly via sys.path rather than hard-coding expected values, so a
numeric drift in either implementation is caught even if nobody remembers
to update a hard-coded constant. `metrics.py` has no internal imports beyond
numpy/pandas, so this import is self-contained and doesn't need the old
repo's "src" package context for anything else.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_OLD_REPO_ROOT = Path(__file__).resolve().parents[3] / "MomentumValueStrategy"
if str(_OLD_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_OLD_REPO_ROOT))

from src.evaluation import metrics as old_metrics  # noqa: E402

from quantlab.validation import metrics as new_metrics  # noqa: E402

TOL = 1e-12


def test_cagr_parity_constant_monthly_return():
    r = 0.01
    dates = pd.date_range("2020-01-31", periods=25, freq="ME")
    equity = pd.Series((1 + r) ** np.arange(25), index=dates)
    assert new_metrics.cagr(equity) == pytest.approx(old_metrics.cagr(equity), abs=TOL)


def test_max_drawdown_parity_fifty_percent():
    equity = pd.Series(
        [1.0, 1.5, 2.0, 1.5, 1.0, 1.0, 1.0],
        index=pd.date_range("2020-01-31", periods=7, freq="ME"),
    )
    new, old = new_metrics.max_drawdown(equity), old_metrics.max_drawdown(equity)
    assert new == pytest.approx(old, abs=TOL)


def test_max_drawdown_parity_no_decline():
    dates = pd.date_range("2020-01-31", periods=4, freq="ME")
    equity = pd.Series([1.0, 1.1, 1.2, 1.3], index=dates)
    new, old = new_metrics.max_drawdown(equity), old_metrics.max_drawdown(equity)
    assert new == pytest.approx(old, abs=TOL)


def test_annualized_vol_parity_zero_for_constant_returns():
    returns = pd.Series([0.01] * 12, index=pd.date_range("2020-01-31", periods=12, freq="ME"))
    assert new_metrics.annualized_vol(returns) == pytest.approx(
        old_metrics.annualized_vol(returns), abs=TOL
    )


def test_sharpe_ratio_parity():
    returns = pd.Series(
        [0.01, 0.02, -0.01, 0.03], index=pd.date_range("2020-01-31", periods=4, freq="ME")
    )
    assert new_metrics.sharpe_ratio(returns, risk_free_rate=0.0) == pytest.approx(
        old_metrics.sharpe_ratio(returns, risk_free_rate=0.0), abs=TOL
    )


def test_sharpe_ratio_parity_nonzero_risk_free_and_periods_per_year():
    returns = pd.Series(
        [0.05, -0.02, 0.03, 0.01, -0.01, 0.04, 0.0, 0.02],
        index=pd.date_range("2020-03-31", periods=8, freq="QE"),
    )
    new = new_metrics.sharpe_ratio(returns, risk_free_rate=0.02, periods_per_year=4)
    old = old_metrics.sharpe_ratio(returns, risk_free_rate=0.02, periods_per_year=4)
    assert new == pytest.approx(old, abs=TOL)
