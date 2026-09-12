"""Unit tests for src/quantlab/validation/report_card.py (acceptance
criterion 8: three fixture results producing REJECTED, RESEARCH_ONLY and
ELIGIBLE_FOR_PAPER respectively).

Fixture design notes (so the numbers below are auditable, not magic):
  - `_alternating` returns are a deterministic two-point series (no RNG) so
    every test is exactly reproducible. A series with hi/lo BOTH positive
    is monotonically increasing regardless of resampling order, so its
    Monte Carlo observed max drawdown is EXACTLY 0.0 and every bootstrap
    resample's drawdown is ALSO exactly 0.0 - `monte_carlo_drawdown`'s
    gate (`prob(drawdown STRICTLY worse) <= 0.5`) then reads 0.0
    deterministically, with no reliance on randomness.
  - An exactly-alternating, EQUAL-COUNT two-point series has PLAIN
    method-of-moments (`scipy.stats`, `bias=True` - report_card.py's own
    convention as of quant-gate REVIEW.md finding 2) skew=0 and non-excess
    kurtosis=1 EXACTLY, at ANY n and ANY hi/lo values - the third/fourth
    central moments are +-delta^3/delta^4 in equal numbers, so they cancel
    (skew) or are identical (kurtosis) regardless of scale or sample size.
    This makes `variance_factor = 1 - skew*sr + (kurt-1)/4*sr**2` reduce to
    EXACTLY 1 for every fixture below, at ANY Sharpe magnitude - no
    "how high can sr go before this breaks" ceiling to worry about.
  - PSR/DSR/`min_track_record_length` are computed on the PER-PERIOD Sharpe
    (`net_returns.mean()/std(ddof=1)`, quant-gate REVIEW.md finding 1 - the
    "same footing" fix), NOT the annualized headline Sharpe. The "strong"
    headline series (hi=0.05, lo=0.01, both POSITIVE for the Monte Carlo
    point above) has a per-period Sharpe of ~1.49 (annualized ~5.15, used
    only for the `min_net_sharpe`/`purged_cv` gates and for display). Four
    background trials (per-period Sharpes 0, +0.50, -0.50, +0.33) with all
    raw MEANS below the headline's give a moderate `var_sr_trials` and let
    White RC/Hansen SPA cleanly identify the headline as the best trial.
"""

from __future__ import annotations

import pandas as pd
import pytest

from quantlab.validation.basic import (
    BootstrapConfig,
    RollingConfig,
    ValidationConfig,
    WalkForwardAxisConfig,
)
from quantlab.validation.registry import TrialsRegistry
from quantlab.validation.report_card import build_report_card
from quantlab.validation.sensitivity import SensitivityResult, SensitivityTrial
from tests._validation_fixtures import make_backtest_result

N_PERIODS = 60


def _alternating(hi: float, lo: float, n: int = N_PERIODS) -> pd.Series:
    values = [hi if i % 2 == 0 else lo for i in range(n)]
    return pd.Series(values, index=pd.date_range("2015-01-31", periods=n, freq="ME"))


def _config(**threshold_overrides: object) -> ValidationConfig:
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
        regimes={},
        walk_forward=WalkForwardAxisConfig(),
        sensitivity={},
        bootstrap=BootstrapConfig(
            b=300,
            block_len=2.0,
            seed=0,
            monte_carlo_n_paths=200,
            monte_carlo_seed=1,
            purged_cv_n_splits=5,
            purged_cv_embargo=1,
        ),
        thresholds=thresholds,
    )


def _register_background_trials(registry: TrialsRegistry, family: str = "momentum") -> None:
    # (hi, lo) pairs -> mean in {0.0, 0.01, -0.01, 0.01}, all < headline's
    # 0.03, with varied Sharpes (0, +1.7, -1.7, +1.1) for a moderate,
    # non-degenerate var_sr_trials.
    pairs = [(0.02, -0.02), (0.03, -0.01), (0.01, -0.03), (0.04, -0.02)]
    for i, (hi, lo) in enumerate(pairs):
        result = make_backtest_result(
            net_returns=_alternating(hi, lo), strategy_id=f"{family}-bg{i:04d}"
        )
        registry.record_backtest(result, family=family)


def _strong_headline_result(**overrides: object) -> object:
    defaults: dict[str, object] = {
        "net_returns": _alternating(0.05, 0.01),  # both positive - see module docstring
        "benchmark_returns": _alternating(0.001, -0.001),  # weak, low-Sharpe benchmark
        "strategy_id": "momentum-headline",
    }
    defaults.update(overrides)
    return make_backtest_result(**defaults)


def _price_panel() -> dict[str, pd.DataFrame]:
    dates = pd.date_range("2020-01-01", periods=90, freq="B")
    panel = {}
    for ticker in ("AAA", "BBB", "CCC"):
        panel[ticker] = pd.DataFrame(
            {"high": 1010.0, "low": 990.0, "close": 1000.0, "volume": 10_000_000.0}, index=dates
        )
    return panel


def _holdings_history() -> dict:
    from quantlab.core.types import TargetWeights

    weights = {"AAA": 0.25, "BBB": 0.25, "CCC": 0.25, "DDD": 0.25}
    return {
        pd.Timestamp("2015-01-31"): TargetWeights(
            asof=pd.Timestamp("2015-01-31"), weights=weights, strategy_id="momentum-headline"
        )
    }


def _flat_sensitivity() -> SensitivityResult:
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


# --- REJECTED --------------------------------------------------------------


def test_report_card_rejected_when_benchmark_beats_strategy_and_no_registry_history(tmp_path):
    registry = TrialsRegistry(tmp_path, repo_root=tmp_path)
    result = make_backtest_result(
        net_returns=_alternating(0.001, -0.001),  # weak strategy
        benchmark_returns=_alternating(0.04, 0.02),  # strong benchmark
        strategy_id="momentum-weak",
    )
    report_card = build_report_card(result, None, registry, _config())

    assert report_card.verdict == "REJECTED"
    assert all(g.reason for g in report_card.gates)
    hard_gates = {g.name: g for g in report_card.gates if g.kind == "hard"}
    assert hard_gates["net_sharpe_vs_benchmark"].passed is False


# --- RESEARCH_ONLY -----------------------------------------------------------


def test_report_card_research_only_when_hard_gates_pass_but_soft_gates_missing(tmp_path):
    registry = TrialsRegistry(tmp_path, repo_root=tmp_path)
    _register_background_trials(registry)
    result = _strong_headline_result()

    report_card = build_report_card(result, None, registry, _config())

    assert all(g.reason for g in report_card.gates)
    hard_gates = {g.name: g for g in report_card.gates if g.kind == "hard"}
    for name, gate in hard_gates.items():
        assert gate.passed, f"expected hard gate {name!r} to pass: {gate.reason}"
    soft_gates = {g.name: g for g in report_card.gates if g.kind == "soft"}
    assert soft_gates["no_cliff_score"].passed is False  # no sensitivity supplied
    assert soft_gates["capacity_ceiling"].passed is False  # no price panel supplied
    assert report_card.verdict == "RESEARCH_ONLY"


# --- ELIGIBLE_FOR_PAPER -------------------------------------------------------


def test_report_card_eligible_for_paper_when_every_gate_passes(tmp_path):
    registry = TrialsRegistry(tmp_path, repo_root=tmp_path)
    _register_background_trials(registry)
    result = _strong_headline_result(holdings_history=_holdings_history())

    report_card = build_report_card(
        result,
        None,
        registry,
        _config(),
        sensitivity=_flat_sensitivity(),
        price_panel=_price_panel(),
    )

    assert all(g.reason for g in report_card.gates)
    failing = [g for g in report_card.gates if not g.passed]
    assert failing == [], f"unexpected failing gate(s): {[(g.name, g.reason) for g in failing]}"
    assert report_card.verdict == "ELIGIBLE_FOR_PAPER"


# --- config threshold flips verdict without code change (acceptance 8) ------


def test_changing_coverage_threshold_flips_verdict_without_code_change(tmp_path):
    registry = TrialsRegistry(tmp_path, repo_root=tmp_path)
    _register_background_trials(registry)
    result = _strong_headline_result(coverage_bound=20.0)

    rejected_card = build_report_card(result, None, registry, _config(max_coverage_bound_pct=15.0))
    assert rejected_card.verdict == "REJECTED"
    assert not any(g.name == "coverage_bound" and g.passed for g in rejected_card.gates)

    relaxed_card = build_report_card(result, None, registry, _config(max_coverage_bound_pct=25.0))
    assert relaxed_card.verdict != "REJECTED"
    assert any(g.name == "coverage_bound" and g.passed for g in relaxed_card.gates)


# --- DSR monotonicity disclosure (quant-gate VERDICT.2.md M06 cycle-2 -------
# finding B, non-blocking item 3) --------------------------------------------


def test_dsr_gate_reason_discloses_non_monotonicity_beside_the_badge(tmp_path):
    # The disclosure must be printed beside the DSR badge whenever DSR is
    # actually computed (not only in the "too thin a registry" NaN branch,
    # which already carries its own distinct explanation).
    registry = TrialsRegistry(tmp_path, repo_root=tmp_path)
    _register_background_trials(registry)
    result = _strong_headline_result()

    report_card = build_report_card(result, None, registry, _config())

    dsr_gate = next(g for g in report_card.gates if g.name == "deflated_sharpe_ratio")
    assert (
        "DSR is not monotone in N above the variance floor; near-duplicate reruns of one grid "
        "point can move it." in dsr_gate.reason
    )


# --- capacity gate "trivially passable" disclosure (quant-gate ------------
# VERDICT.2.md M06 cycle-2 finding C, non-blocking item 4) ------------------


def test_capacity_gate_states_trivially_passable_note_at_small_stake(tmp_path):
    # Alex's default intended_capital_usd ($1,000) against this fixture's
    # panel (3 tickers, $10M daily volume each) clears the 100x bar by many
    # orders of magnitude - exactly the case the note exists to flag, since
    # a green badge here says nothing about edge, only that the stake is
    # tiny relative to the instrument's liquidity.
    registry = TrialsRegistry(tmp_path, repo_root=tmp_path)
    _register_background_trials(registry)
    result = _strong_headline_result(holdings_history=_holdings_history())

    report_card = build_report_card(
        result,
        None,
        registry,
        _config(),
        sensitivity=_flat_sensitivity(),
        price_panel=_price_panel(),
    )

    cap_gate = next(g for g in report_card.gates if g.name == "capacity_ceiling")
    assert cap_gate.passed is True
    assert cap_gate.value > 10 * cap_gate.threshold, (
        "fixture must actually clear the bar by >10x for this regression to mean anything"
    )
    assert "capacity gate is trivially passable at this stake" in cap_gate.reason


def test_capacity_gate_omits_trivially_passable_note_when_close_to_the_bar(tmp_path):
    # Raising the bar to just under the fixture's own multiple keeps the
    # gate passing without clearing it by >10x - the note must NOT appear.
    registry = TrialsRegistry(tmp_path, repo_root=tmp_path)
    _register_background_trials(registry)
    result = _strong_headline_result(holdings_history=_holdings_history())

    baseline = build_report_card(
        result,
        None,
        registry,
        _config(),
        sensitivity=_flat_sensitivity(),
        price_panel=_price_panel(),
    )
    baseline_cap_gate = next(g for g in baseline.gates if g.name == "capacity_ceiling")
    near_bar_multiple = baseline_cap_gate.value / 2.0  # still passes, well under 10x headroom

    report_card = build_report_card(
        result,
        None,
        registry,
        _config(capacity_min_multiple_of_intended_capital=near_bar_multiple),
        sensitivity=_flat_sensitivity(),
        price_panel=_price_panel(),
    )
    cap_gate = next(g for g in report_card.gates if g.name == "capacity_ceiling")
    assert cap_gate.passed is True
    assert cap_gate.value <= 10 * cap_gate.threshold
    assert "capacity gate is trivially passable at this stake" not in cap_gate.reason


# --- annualization invariance (quant-gate REVIEW.md finding 1) -------------


def test_psr_is_invariant_to_the_periods_per_year_label(tmp_path):
    # PSR is a function of (per-period sr, n, skew, kurt) alone - none of
    # deflated_sharpe.py's formulas take a periods_per_year argument, so
    # labelling the SAME return series "monthly" vs "quarterly" (i.e.
    # relabeling rebalance_freq, which only changes what m.net_sharpe is
    # ANNUALIZED to) must not move PSR at all. This is exactly the
    # regression the footing bug would have failed: the old code fed in
    # the ANNUALIZED Sharpe, which DOES depend on periods_per_year.
    net_returns = _alternating(0.03, -0.01, n=48)
    registry_monthly = TrialsRegistry(tmp_path / "monthly", repo_root=tmp_path)
    registry_quarterly = TrialsRegistry(tmp_path / "quarterly", repo_root=tmp_path)

    result_monthly = make_backtest_result(
        net_returns=net_returns, strategy_id="momentum-freqtest", rebalance_freq="month_end"
    )
    result_quarterly = make_backtest_result(
        net_returns=net_returns, strategy_id="momentum-freqtest", rebalance_freq="quarter_end"
    )

    card_monthly = build_report_card(result_monthly, None, registry_monthly, _config())
    card_quarterly = build_report_card(result_quarterly, None, registry_quarterly, _config())

    assert card_monthly.psr == pytest.approx(card_quarterly.psr, abs=1e-12)
    # The two annualized headline Sharpes (display-only) DO differ, proving
    # this isn't a vacuous check where nothing actually changed between runs.
    assert card_monthly.basic.metrics.net_sharpe != pytest.approx(
        card_quarterly.basic.metrics.net_sharpe
    )


# --- JSON round trip ----------------------------------------------------------


def test_report_card_json_round_trips(tmp_path):
    import json

    registry = TrialsRegistry(tmp_path, repo_root=tmp_path)
    _register_background_trials(registry)
    result = _strong_headline_result()
    report_card = build_report_card(result, None, registry, _config())

    payload = json.loads(json.dumps(report_card.to_json()))
    assert payload["verdict"] == report_card.verdict
    assert len(payload["gates"]) == len(report_card.gates)


# --- headline pinning (quant-gate VERDICT.2.md M06 cycle-2 finding A) ------


def test_rc_hard_gate_fails_named_cause_when_headline_offset_from_siblings(tmp_path):
    """BLOCKING item 1, end to end through `build_report_card`: the exact
    planted case from the verdict - three strong trials aligned 2014-2023
    plus a worthless HEADLINE offset to 2019-2028 (same length, 60-month
    overlap, under the 0.8 floor). Before this fix, the greedy overlap
    resolver would drop the HEADLINE itself and the Reality Check would
    silently PASS or FAIL on behalf of the three siblings alone - never
    examining the strategy actually being validated. Now the RC hard gate
    must FAIL, named by cause, and `report_card.rc` must be None (the
    headline could never be included, so no test was ever actually run).
    """
    registry = TrialsRegistry(tmp_path, repo_root=tmp_path)
    aligned_dates = pd.date_range("2014-01-31", periods=120, freq="ME")
    offset_dates = pd.date_range(aligned_dates[60], periods=120, freq="ME")  # 2019-2028

    for i in range(3):
        sibling = make_backtest_result(
            net_returns=_alternating(0.05, 0.03, n=120).set_axis(aligned_dates),
            strategy_id=f"momentum-strongsib{i:02d}",
        )
        registry.record_backtest(sibling, family="momentum")

    headline = make_backtest_result(
        net_returns=_alternating(0.001, -0.05, n=120).set_axis(offset_dates),  # worthless
        benchmark_returns=_alternating(0.001, -0.001, n=120).set_axis(offset_dates),
        strategy_id="momentum-headline",
    )

    report_card = build_report_card(headline, None, registry, _config())

    rc_gate = next(g for g in report_card.gates if g.name == "reality_check_pvalue")
    assert rc_gate.passed is False
    assert "headline trial excluded by overlap floor" in rc_gate.reason
    assert report_card.rc is None
    # The RC hard gate failing must cap the verdict at REJECTED - the
    # regression this guards against is a silent PASS computed on the
    # siblings, which this assertion would not catch on its own without
    # the reason-string check above also naming the true cause.
    assert report_card.verdict == "REJECTED"
