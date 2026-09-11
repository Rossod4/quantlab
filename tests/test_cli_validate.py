"""Unit tests for src/quantlab/cli.py's `validate` one-liner (quant-gate
VERDICT.md cycle-1 finding 4: a nonzero extreme-return count must appear in
the one-liner, with the long/short breakdown)."""

from __future__ import annotations

import pandas as pd

from quantlab.backtest.result import QualityFlags
from quantlab.cli import _validate_one_liner
from quantlab.validation import metrics
from tests._validation_fixtures import make_backtest_result


def _summary() -> metrics.MetricsSummary:
    dates = pd.date_range("2020-01-31", periods=6, freq="ME")
    net_returns = pd.Series([0.01, -0.02, 0.03, 0.01, -0.01, 0.02], index=dates)
    result = make_backtest_result(net_returns=net_returns)
    return metrics.summary(result)


def test_one_liner_omits_extreme_returns_when_zero():
    line = _validate_one_liner(_summary(), QualityFlags())
    assert "extreme_returns" not in line


def test_one_liner_includes_extreme_returns_long_and_short_when_nonzero():
    qf = QualityFlags(extreme_returns=3, extreme_returns_long=2, extreme_returns_short=1)
    line = _validate_one_liner(_summary(), qf)
    assert "extreme_returns_long=2" in line
    assert "extreme_returns_short=1" in line


def test_one_liner_includes_extreme_returns_when_only_short_nonzero():
    qf = QualityFlags(extreme_returns=1, extreme_returns_long=0, extreme_returns_short=1)
    line = _validate_one_liner(_summary(), qf)
    assert "extreme_returns_long=0" in line
    assert "extreme_returns_short=1" in line


def test_one_liner_still_reports_core_metrics():
    line = _validate_one_liner(_summary(), QualityFlags())
    for token in ("net CAGR=", "Sharpe=", "Sortino=", "Calmar=", "maxDD=", "hit_rate="):
        assert token in line
