"""Committed artefacts must not carry machine-specific absolute paths."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from quantlab.core.paths import REPO_ROOT, portable_path
from quantlab.reporting.context import _provenance_section
from tests._validation_fixtures import make_backtest_result


def test_a_path_under_the_repo_is_shown_relative_with_forward_slashes():
    assert portable_path(REPO_ROOT / "reports" / "momentum_12_1") == "reports/momentum_12_1"
    assert portable_path(str(REPO_ROOT / "configs" / "x.yaml")) == "configs/x.yaml"


def test_a_path_outside_the_repo_keeps_only_its_name(tmp_path):
    shown = portable_path(tmp_path / "scratch" / "blend_75_25.yaml")
    assert shown == "<external>/blend_75_25.yaml"
    assert "Users" not in shown and str(tmp_path) not in shown


def test_report_provenance_section_prints_the_strategy_config_relative():
    result = make_backtest_result(
        net_returns=pd.Series(0.01, index=pd.date_range("2015-01-31", periods=12, freq="ME")),
        strategy_config=str(REPO_ROOT / "configs" / "strategies" / "momentum_12_1.yaml"),
    )
    section = _provenance_section(result)
    assert section["backtest_config"]["strategy_config"] == "configs/strategies/momentum_12_1.yaml"
    # the saved result's own provenance is untouched (run artefacts are not hand-edited)
    assert str(Path(REPO_ROOT)) in result.provenance["backtest_config"]["strategy_config"]
