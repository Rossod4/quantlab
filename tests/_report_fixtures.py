"""Shared fixture builder for the M07 reporting test suite
(test_plots.py, test_report_context.py, test_render.py, test_cli_report.py).

Mirrors `tests/test_report_card.py`'s own fixture design exactly (same
deterministic alternating-return series, same background-trial registration,
same price panel / holdings history / sensitivity grid) so the three
verdicts this module builds - REJECTED, RESEARCH_ONLY, ELIGIBLE_FOR_PAPER -
are the same "M06 fixture results" acceptance criterion 2 asks M07 to
render, not a separate, less-scrutinized set of numbers. Not itself a test
module (no `test_` prefix).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from quantlab.backtest.result import BacktestResult
from quantlab.core.types import TargetWeights
from quantlab.validation.basic import (
    BootstrapConfig,
    RollingConfig,
    ValidationConfig,
    WalkForwardAxisConfig,
)
from quantlab.validation.registry import TrialsRegistry
from quantlab.validation.report_card import ReportCard, build_report_card
from quantlab.validation.sensitivity import SensitivityResult, SensitivityTrial
from tests._validation_fixtures import make_backtest_result

N_PERIODS = 60


def alternating(hi: float, lo: float, n: int = N_PERIODS) -> pd.Series:
    values = [hi if i % 2 == 0 else lo for i in range(n)]
    return pd.Series(values, index=pd.date_range("2015-01-31", periods=n, freq="ME"))


def config(**threshold_overrides: object) -> ValidationConfig:
    thresholds = {
        "min_dsr": 0.95,
        "max_rc_pvalue": 0.10,
        "min_psr": 0.95,
        "min_subperiod_oof_sharpe": 0.0,
        "min_no_cliff_score": 0.5,
        "min_net_sharpe": 0.3,
        "mc_max_prob_drawdown_worse_than_observed": 0.5,
        "capacity_min_multiple_of_intended_capital": 100.0,
        "max_spa_pvalue": 0.10,
        "min_walk_forward_stability_fraction": 0.5,
        "max_coverage_bound_pct": 15.0,
        "min_track_record_confidence": 0.95,
    }
    thresholds.update(threshold_overrides)
    return ValidationConfig(
        rolling=RollingConfig(window_years=[1]),
        regimes={"first_year": ("2015-01-01", "2015-12-31")},
        walk_forward=WalkForwardAxisConfig(),
        sensitivity={},
        bootstrap=BootstrapConfig(
            # deliberately small - these fixtures only need a report card to
            # exist and render, not a well-calibrated statistical test; M06's
            # own suite covers RC/SPA/Monte Carlo correctness at realistic B.
            b=60,
            block_len=2.0,
            seed=0,
            monte_carlo_n_paths=40,
            monte_carlo_seed=1,
            purged_cv_n_splits=5,
            purged_cv_embargo=1,
        ),
        thresholds=thresholds,
    )


def register_background_trials(registry: TrialsRegistry, family: str = "momentum") -> None:
    pairs = [(0.02, -0.02), (0.03, -0.01), (0.01, -0.03), (0.04, -0.02)]
    for i, (hi, lo) in enumerate(pairs):
        result = make_backtest_result(
            net_returns=alternating(hi, lo), strategy_id=f"{family}-bg{i:04d}"
        )
        registry.record_backtest(result, family=family)


def holdings_history() -> dict:
    weights = {"AAA": 0.25, "BBB": 0.25, "CCC": 0.25, "DDD": 0.25}
    return {
        pd.Timestamp("2015-01-31"): TargetWeights(
            asof=pd.Timestamp("2015-01-31"), weights=weights, strategy_id="momentum-headline"
        )
    }


def price_panel() -> dict[str, pd.DataFrame]:
    dates = pd.date_range("2020-01-01", periods=90, freq="B")
    panel = {}
    for ticker in ("AAA", "BBB", "CCC"):
        panel[ticker] = pd.DataFrame(
            {"high": 1010.0, "low": 990.0, "close": 1000.0, "volume": 10_000_000.0}, index=dates
        )
    return panel


def flat_sensitivity() -> SensitivityResult:
    return SensitivityResult(
        param_axes={"lookback_months": [9, 12, 15]},
        base_point={"lookback_months": 12},
        trials=[
            SensitivityTrial(
                strategy_id="momentum-p1", params={"lookback_months": 9}, net_sharpe=10.0
            ),
            SensitivityTrial(
                strategy_id="momentum-p2", params={"lookback_months": 12}, net_sharpe=10.0
            ),
            SensitivityTrial(
                strategy_id="momentum-p3", params={"lookback_months": 15}, net_sharpe=10.0
            ),
        ],
        surface=pd.Series(
            [10.0, 10.0, 10.0], index=pd.Index([(9,), (12,), (15,)], name=("lookback_months",))
        ),
        no_cliff_score=1.0,
        neighbourhood_size=3,
        neighbourhood_truncated=False,
    )


def strong_headline_result(**overrides: object) -> BacktestResult:
    defaults: dict[str, object] = {
        "net_returns": alternating(0.05, 0.01),
        "benchmark_returns": alternating(0.001, -0.001),
        "strategy_id": "momentum-headline",
        "holdings_history": holdings_history(),
    }
    defaults.update(overrides)
    return make_backtest_result(**defaults)


def real_walk_forward_result():
    """A genuine `walk_forward_blend(...)` result - quant-gate VERDICT.md M07
    cycle-1 finding 1 (BLOCKER): the context/template layer must be
    exercised against the PRODUCER's real `to_json()` shape by the
    rendering acceptance suite, not only asserted against a hand-written
    dict in a unit test."""
    from quantlab.validation.walk_forward import walk_forward_blend

    dates = pd.date_range("2005-03-31", periods=64, freq="QE")
    momentum = pd.Series([0.03, -0.01, 0.02, -0.02] * 16, index=dates)
    value = pd.Series([0.01, 0.02, -0.01, 0.015] * 16, index=dates)
    return walk_forward_blend(
        [momentum, value],
        weight_grid=[(1.0, 0.0), (0.75, 0.25), (0.5, 0.5), (0.25, 0.75), (0.0, 1.0)],
        train_years=3,
        test_years=1,
        child_labels=("momentum", "value"),
    )


def fully_populate_backtest_config(result: BacktestResult) -> BacktestResult:
    """quant-gate VERDICT.md M07 cycle-1 finding 6: every other fixture
    leaves `backtest_config` sparse (only `rebalance_freq`/`initial_capital`/
    `start`/`end`), so the M04 carried "which price the entry is measured
    at" sentence (`next_open`) is exercised by NO rendered fixture. Mutates
    `result.provenance["backtest_config"]` in place (a plain dict, despite
    `BacktestResult` itself being frozen) and returns `result` for chaining."""
    result.provenance["backtest_config"].update(
        {
            "execution": "next_open",
            "cost_model": "flat_bps",
            "one_way_cost_bps": 10.0,
            "borrow_fee_annual_bps": 30.0,
            "corwin_schultz_lookback_days": 60,
            "delisting_haircut": 0.0,
            "extreme_return_policy": "exclude_legacy",
            "extreme_return_bound": 3.0,
            "max_dropped_fraction": 0.05,
            "abort_on_unscoreable": True,
        }
    )
    return result


def build_rejected(tmp_path: Path) -> tuple[BacktestResult, ReportCard]:
    """Weak strategy vs. a strong benchmark - fails the hard
    `net_sharpe_vs_benchmark` gate, capping the verdict at REJECTED."""
    registry = TrialsRegistry(tmp_path / "registry", repo_root=tmp_path)
    result = make_backtest_result(
        net_returns=alternating(0.001, -0.001),
        benchmark_returns=alternating(0.04, 0.02),
        strategy_id="momentum-weak",
        holdings_history=holdings_history(),
    )
    card = build_report_card(result, None, registry, config())
    assert card.verdict == "REJECTED"
    return result, card


def build_research_only(tmp_path: Path) -> tuple[BacktestResult, ReportCard]:
    """Every hard gate passes but no sensitivity grid / price panel was
    supplied, so the soft `no_cliff_score`/`capacity_ceiling` gates fail -
    RESEARCH_ONLY, never REJECTED."""
    registry = TrialsRegistry(tmp_path / "registry", repo_root=tmp_path)
    register_background_trials(registry)
    result = strong_headline_result()
    card = build_report_card(result, None, registry, config())
    assert card.verdict == "RESEARCH_ONLY"
    return result, card


def build_eligible(tmp_path: Path) -> tuple[BacktestResult, ReportCard]:
    """Every hard and soft gate passes (sensitivity grid + price panel
    supplied) - ELIGIBLE_FOR_PAPER."""
    registry = TrialsRegistry(tmp_path / "registry", repo_root=tmp_path)
    register_background_trials(registry)
    result = strong_headline_result()
    card = build_report_card(
        result,
        None,
        registry,
        config(),
        sensitivity=flat_sensitivity(),
        price_panel=price_panel(),
    )
    assert card.verdict == "ELIGIBLE_FOR_PAPER"
    return result, card


def build_eligible_with_walk_forward(tmp_path: Path) -> tuple[BacktestResult, ReportCard]:
    """Same as `build_eligible`, plus a REAL walk-forward result and a fully
    populated `backtest_config` (`execution=next_open` and every other
    execution-convention field) - the fourth fixture quant-gate VERDICT.md
    M07 cycle-1 findings 1 and 6 both ask for, so section 5's walk-forward
    block and section 6's `next_open` sentence are both exercised by the
    RENDERING acceptance suite, not only by unit tests."""
    registry = TrialsRegistry(tmp_path / "registry", repo_root=tmp_path)
    register_background_trials(registry)
    result = fully_populate_backtest_config(strong_headline_result())
    card = build_report_card(
        result,
        None,
        registry,
        config(),
        sensitivity=flat_sensitivity(),
        price_panel=price_panel(),
        walk_forward=real_walk_forward_result(),
    )
    return result, card


def save_result_and_card(result: BacktestResult, card: ReportCard, out_dir: Path) -> Path:
    """Save `result` and `card.to_json()` into the SAME directory, exactly
    the layout `render.render_report`/`cli.report` expect
    (`result.save(...)` + a sibling `report_card.json`)."""
    import json

    out_dir.mkdir(parents=True, exist_ok=True)
    result.save(out_dir)
    (out_dir / "report_card.json").write_text(json.dumps(card.to_json(), sort_keys=True))
    return out_dir
