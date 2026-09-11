"""Unit tests for src/quantlab/validation/basic.py."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from quantlab.backtest.result import QualityFlags
from quantlab.validation.basic import (
    RollingConfig,
    ValidationConfig,
    WalkForwardAxisConfig,
    load_validation_config,
    validate_basic,
)
from quantlab.validation.sensitivity import SensitivityResult, SensitivityTrial
from tests._validation_fixtures import make_backtest_result


def _default_config(**overrides: object) -> ValidationConfig:
    defaults: dict[str, object] = {
        "rolling": RollingConfig(window_years=[1]),
        "regimes": {},
        "walk_forward": WalkForwardAxisConfig(),
        "sensitivity": {},
        "thresholds": {},
    }
    defaults.update(overrides)
    return ValidationConfig(**defaults)


def _monthly_returns(values: list[float], start: str = "2020-01-31") -> pd.Series:
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="ME"))


# --- config loading ---


def test_load_validation_config_parses_shipped_config():
    path = Path(__file__).resolve().parent.parent / "configs" / "validation.yaml"
    config = load_validation_config(path)
    assert config.rolling.window_years == [3, 5]
    assert "covid_2020" in config.regimes
    assert config.walk_forward.train_years == 5
    assert len(config.walk_forward.weight_grid) == 5
    assert "momentum" in config.sensitivity
    assert config.thresholds["min_net_sharpe"] == pytest.approx(0.3)
    assert config.benchmark_overlap_min_fraction == pytest.approx(0.9)


def test_load_validation_config_missing_file_raises_config_error():
    from quantlab.core.errors import ConfigError

    with pytest.raises(ConfigError):
        load_validation_config("configs/does_not_exist.yaml")


# --- validate_basic: quality flags (carried M04 verdict items 2-4) ---


def _occurrences(flags: list[str], needle: str) -> int:
    return sum(1 for f in flags if needle in f)


def test_validate_basic_reports_each_quality_counter_exactly_once():
    # Quant-gate VERDICT.md cycle-1 finding 3: unscored_by_date and
    # dropped_tickers_by_date used to appear TWICE (once in the combined
    # coverage sentence, once as their own standalone flag). Assert
    # occurrence COUNTS of the exact number-bearing phrase, not substring
    # membership - a membership check passes under the duplication this
    # regression exists to catch.
    net_returns = _monthly_returns([0.01] * 24)
    qf = QualityFlags(
        forced_exits=2,
        extreme_returns=3,
        extreme_returns_long=2,
        extreme_returns_short=1,
        missing_forward_prices=2,  # equals forced_exits - must not appear as a second number
        unscored_by_date={"2020-01-31": ["AAPL"], "2020-02-29": ["MSFT"]},
        dropped_tickers_by_date={"2020-03-31": ["GOOG"]},
    )
    result = make_backtest_result(net_returns=net_returns, quality_flags=qf, coverage_bound=12.5)
    basic = validate_basic(result, None, _default_config())

    assert _occurrences(basic.flags, "2 forced exit") == 1
    assert _occurrences(basic.flags, "2 long-book extreme-return") == 1
    assert _occurrences(basic.flags, "1 short-book extreme-return") == 1
    # The exact number-bearing phrases from the standalone flags - each
    # must appear exactly once across ALL flags, including the combined
    # coverage sentence.
    assert _occurrences(basic.flags, "2 rebalance date(s) had declared-universe") == 1
    assert _occurrences(basic.flags, "1 rebalance date(s) had ticker(s) dropped") == 1

    joined = " | ".join(basic.flags)
    assert "12.5%" in joined
    assert "SEPARATE selection effects" in joined
    assert "missing_forward_prices" not in joined


def test_validate_basic_omits_zero_quality_counters():
    net_returns = _monthly_returns([0.01] * 24)
    result = make_backtest_result(net_returns=net_returns, quality_flags=QualityFlags())
    basic = validate_basic(result, None, _default_config())
    joined = " | ".join(basic.flags)
    assert "forced exit" not in joined
    assert "extreme-return" not in joined


# --- validate_basic: benchmark comparison ---


def test_validate_basic_flags_benchmark_sharpe_exceeding_strategy():
    # Both series have nonzero variance (constant returns would give a NaN
    # Sharpe, which the `>` comparison would silently read as False
    # regardless of intent) - the strategy's mean return is ~0 (Sharpe ~0),
    # the benchmark's is clearly positive (Sharpe clearly positive).
    net_returns = _monthly_returns([0.001, -0.002, 0.0, 0.001] * 6)
    benchmark_returns = _monthly_returns([0.03, 0.01] * 12)
    result = make_backtest_result(net_returns=net_returns, benchmark_returns=benchmark_returns)
    basic = validate_basic(result, None, _default_config())
    assert any("benchmark Sharpe exceeds strategy Sharpe" in f for f in basic.flags)


def test_validate_basic_no_benchmark_flag_when_strategy_wins():
    net_returns = _monthly_returns([0.03, 0.01] * 12)
    benchmark_returns = _monthly_returns([0.001, -0.002, 0.0, 0.001] * 6)
    result = make_backtest_result(net_returns=net_returns, benchmark_returns=benchmark_returns)
    basic = validate_basic(result, None, _default_config())
    assert not any("benchmark Sharpe exceeds" in f for f in basic.flags)


def test_validate_basic_flags_no_usable_benchmark_when_sharpe_is_nan():
    # Quant-gate carried item 9: a constant (zero-variance) embedded
    # benchmark gives a NaN Sharpe, and `NaN > net_sharpe` is silently
    # False - the old code fell through with no comparison flag at all.
    net_returns = _monthly_returns([0.001, -0.002, 0.0, 0.001] * 6)
    benchmark_returns = _monthly_returns([0.02] * 24)  # constant -> zero variance
    result = make_backtest_result(net_returns=net_returns, benchmark_returns=benchmark_returns)
    basic = validate_basic(result, None, _default_config())
    assert any("no usable benchmark Sharpe" in f for f in basic.flags)
    assert not any("benchmark Sharpe exceeds" in f for f in basic.flags)


# --- validate_basic: rolling windows ---


def test_validate_basic_flags_negative_rolling_windows():
    # 2 up years then heavy losses, monthly, so several rolling 1y windows
    # that span the crash have negative CAGR.
    values = [0.02] * 24 + [-0.1] * 12
    net_returns = _monthly_returns(values)
    basic = validate_basic(
        make_backtest_result(net_returns=net_returns),
        None,
        _default_config(rolling=RollingConfig(window_years=[1])),
    )
    assert 1 in basic.rolling
    assert any("rolling 1y windows negative" in f for f in basic.flags)


def test_validate_basic_flags_insufficient_history_instead_of_raising():
    net_returns = _monthly_returns([0.01] * 6)
    basic = validate_basic(
        make_backtest_result(net_returns=net_returns),
        None,
        _default_config(rolling=RollingConfig(window_years=[5])),
    )
    assert 5 not in basic.rolling
    assert any("insufficient history" in f for f in basic.flags)


# --- validate_basic: sensitivity neighbourhood truncation (finding 2) ---


def test_validate_basic_flags_truncated_sensitivity_neighbourhood():
    net_returns = _monthly_returns([0.01, -0.02, 0.03, 0.0] * 6)
    result = make_backtest_result(net_returns=net_returns)
    sensitivity = SensitivityResult(
        param_axes={"lookback_months": [9, 12, 15]},
        base_point={"lookback_months": 9},
        trials=[SensitivityTrial(strategy_id="s-1", params={"lookback_months": 9}, net_sharpe=1.0)],
        surface=pd.Series([1.0], index=pd.Index([(9,)], name=("lookback_months",))),
        no_cliff_score=0.5,
        neighbourhood_size=2,
        neighbourhood_truncated=True,
    )
    basic = validate_basic(result, None, _default_config(), sensitivity=sensitivity)
    assert any("truncated at a grid edge" in f for f in basic.flags)
    assert basic.sensitivity is sensitivity


def test_validate_basic_no_truncation_flag_when_sensitivity_omitted():
    net_returns = _monthly_returns([0.01, -0.02, 0.03, 0.0] * 6)
    result = make_backtest_result(net_returns=net_returns)
    basic = validate_basic(result, None, _default_config())
    assert not any("truncated" in f for f in basic.flags)


def test_validate_basic_flags_sensitivity_nan_points():
    # Quant-gate carried item 8: a NaN-Sharpe neighbour must be disclosed,
    # not just silently excluded from the score.
    net_returns = _monthly_returns([0.01, -0.02, 0.03, 0.0] * 6)
    result = make_backtest_result(net_returns=net_returns)
    sensitivity = SensitivityResult(
        param_axes={"lookback_months": [9, 12, 15]},
        base_point={"lookback_months": 12},
        trials=[SensitivityTrial(strategy_id="s-1", params={"lookback_months": 9}, net_sharpe=1.0)],
        surface=pd.Series([1.0], index=pd.Index([(9,)], name=("lookback_months",))),
        no_cliff_score=0.5,
        neighbourhood_size=3,
        neighbourhood_truncated=False,
        nan_points=1,
    )
    basic = validate_basic(result, None, _default_config(), sensitivity=sensitivity)
    assert any("NaN Sharpe" in f for f in basic.flags)


# --- validate_basic: benchmark overlap (finding 6) ---


def test_validate_basic_flags_short_benchmark_overlap():
    net_returns = _monthly_returns([0.01, -0.02, 0.03, 0.0] * 15)  # 60 periods
    overlap_start = net_returns.index[-6]
    benchmark_returns = _monthly_returns([0.02, -0.01] * 3, start=overlap_start)  # 6 periods
    result = make_backtest_result(net_returns=net_returns, benchmark_returns=benchmark_returns)
    basic = validate_basic(result, None, _default_config())
    assert any("benchmark covers 6 of 60 periods" in f for f in basic.flags)


def test_validate_basic_no_overlap_flag_when_benchmark_covers_full_window():
    net_returns = _monthly_returns([0.01, -0.02, 0.03, 0.0] * 15)
    benchmark_returns = _monthly_returns([0.02, -0.01, 0.0, 0.03] * 15)
    result = make_backtest_result(net_returns=net_returns, benchmark_returns=benchmark_returns)
    basic = validate_basic(result, None, _default_config())
    assert not any("periods (" in f and "benchmark covers" in f for f in basic.flags)


# --- determinism + JSON round trip (acceptance criterion 6) ---


def test_validate_basic_is_deterministic():
    # A non-constant benchmark, so `beta`/`benchmark_sharpe` are real numbers
    # rather than NaN (NaN != NaN would break this equality check even
    # though the result genuinely is deterministic run-to-run).
    net_returns = _monthly_returns([0.01, -0.02, 0.03, 0.0] * 9)
    benchmark_returns = _monthly_returns([0.02, -0.01, 0.0, 0.03] * 9)
    result = make_backtest_result(net_returns=net_returns, benchmark_returns=benchmark_returns)
    config = _default_config()
    first = validate_basic(result, None, config)
    second = validate_basic(result, None, config)
    assert first.flags == second.flags
    assert first.metrics == second.metrics


def test_validate_basic_json_round_trips():
    net_returns = _monthly_returns([0.01, -0.02, 0.03, 0.0] * 9)
    result = make_backtest_result(net_returns=net_returns)
    basic = validate_basic(result, None, _default_config())
    payload = json.loads(json.dumps(basic.to_json()))
    assert payload["flags"] == basic.flags
    assert payload["walk_forward"] is None
    assert payload["sensitivity"] is None
    assert "1" in payload["rolling"]
