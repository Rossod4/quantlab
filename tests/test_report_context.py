"""Unit tests for src/quantlab/reporting/context.py's `build_report_context`
(work packet acceptance criterion 2's own test): every section key present,
carried caveat strings verbatim, the dirty badge toggling, and a NaN
benchmark degrading to an explicit sentence rather than a bare "nan".

Builds `report_card`-shaped DICTS directly (exactly `ReportCard.to_json()`'s
schema, documented in report_card.py/basic.py/each validation submodule's
own `to_json()`) rather than running the full statistical pipeline - that
pipeline is M06's own test suite's job; this module tests the FORMATTING
layer in isolation, the way the packet's own "the ONLY place numbers are
formatted" framing intends.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from quantlab.reporting import context as context_module
from quantlab.reporting.context import build_report_context
from tests._validation_fixtures import make_backtest_result

_METRICS = {
    "periods_per_year": 12,
    "net_cagr": 0.15,
    "gross_cagr": 0.18,
    "net_annualized_vol": 0.10,
    "net_sharpe": 1.2,
    "net_sortino": 1.5,
    "net_calmar": 1.1,
    "net_max_drawdown": -0.2,
    "hit_rate": 0.55,
    "turnover_mean": 0.3,
    "cost_drag_cagr": -0.01,
    "benchmark_cagr": 0.08,
    "benchmark_sharpe": 0.5,
    "tracking_error": 0.05,
    "information_ratio": 0.4,
    "beta": 0.9,
    "benchmark_overlap_periods": 60,
}

_GATES = [
    {
        "name": "deflated_sharpe_ratio",
        "kind": "hard",
        "value": 0.97,
        "threshold": 0.95,
        "passed": True,
        "reason": "DSR=0.9700 against the 0.95 bar for significance after correcting for N=5 "
        "distinct trials.",
    },
    {
        "name": "probabilistic_sharpe_ratio",
        "kind": "soft",
        "value": 0.99,
        "threshold": 0.95,
        "passed": True,
        "reason": "PSR=0.9900 against the 0.95 bar (computed on the PER-PERIOD Sharpe 1.4874, "
        "not the annualized 1.20).",
    },
    {
        "name": "monte_carlo_drawdown",
        "kind": "soft",
        "value": 0.4,
        "threshold": 0.5,
        "passed": True,
        "reason": "P(bootstrap drawdown worse than observed)=0.40.",
    },
    {
        "name": "no_cliff_score",
        "kind": "soft",
        "value": 0.8,
        "threshold": 0.5,
        "passed": True,
        "reason": "no_cliff_score=0.8000 against 0.50 - a RELATIVE-SPREAD statistic only, never "
        "evidence of quality by itself (see min_net_sharpe below).",
    },
    {
        "name": "min_net_sharpe",
        "kind": "soft",
        "value": 1.2,
        "threshold": 0.3,
        "passed": True,
        "reason": "net Sharpe 1.20 against 0.30 - gated ALONGSIDE no_cliff_score.",
    },
    {
        "name": "walk_forward_stability",
        "kind": "soft",
        "value": 0.8,
        "threshold": 0.5,
        "passed": True,
        "reason": "walk-forward chose the modal weight tuple in 80% of steps.",
    },
]


def _basic(**overrides: object) -> dict:
    base = {
        "metrics": dict(_METRICS),
        "rolling": {
            "3": {
                "2018-01-31": {
                    "CAGR": 0.1,
                    "Annualized Volatility": 0.1,
                    "Sharpe Ratio": 1.0,
                    "Max Drawdown": -0.1,
                }
            }
        },
        "subperiods": {
            "first_half": {
                "CAGR": 0.1,
                "Annualized Volatility": 0.1,
                "Sharpe Ratio": 1.0,
                "Max Drawdown": -0.1,
                "Growth": 1.5,
            }
        },
        "flags": ["coverage bound 0.0% - SEPARATE selection effects, not additive"],
        "walk_forward": None,
        "sensitivity": None,
    }
    base.update(overrides)
    return base


def _report_card(**overrides: object) -> dict:
    base = {
        "basic": _basic(),
        "psr": 0.99,
        "dsr": 0.97,
        "min_trl": 24.0,
        "n_trials": 5,
        "cv": {"fold_sharpes": [1.0, 1.2], "mean_oof_sharpe": 1.1, "periods_per_year": 12},
        "rc": {
            "test_name": "white_rc",
            "statistic": 1.0,
            "p_value": 0.03,
            "best_trial": "momentum-headline",
            "n_trials": 5,
            "n_periods": 60,
            "b": 300,
            "block_len": 2.0,
        },
        "spa": {
            "test_name": "hansen_spa",
            "statistic": 1.0,
            "p_value": 0.03,
            "best_trial": "momentum-headline",
            "n_trials": 5,
            "n_periods": 60,
            "b": 300,
            "block_len": 2.0,
        },
        "monte_carlo": {
            "n_paths": 200,
            "block_len": 2.0,
            "periods_per_year": 12,
            "observed_max_drawdown": -0.2,
            "cagr_p5": 0.05,
            "cagr_p50": 0.15,
            "cagr_p95": 0.25,
            "max_drawdown_p5": -0.3,
            "max_drawdown_p50": -0.2,
            "max_drawdown_p95": -0.1,
            "sharpe_p5": 0.8,
            "sharpe_p50": 1.2,
            "sharpe_p95": 1.6,
            "prob_drawdown_worse_than_observed": 0.4,
        },
        "capacity": None,
        "coverage_bound": 5.0,
        "quality_flags_summary": {
            "forced_exits": 2,
            "extreme_returns": 3,
            "extreme_returns_long": 1,
            "extreme_returns_short": 2,
            "missing_forward_prices": 2,
            "unscoreable_dates": [],
            "dropped_tickers_by_date": {"2020-01-31": ["AAA"]},
            "unscored_by_date": {"2020-01-31": ["BBB"]},
            "degenerate_excluded_book_dates": {},
        },
        "known_caveats": ["a known caveat, verbatim."],
        "gates": list(_GATES),
        "verdict": "ELIGIBLE_FOR_PAPER",
        "provenance": {
            "strategy_id": "momentum-headline",
            "data_semantics_version": "m03b",
            "quantlab_git_sha": "abc1234",
            "dirty": False,
            "dirty_source": "provenance",
            "n_trials": 5,
            "n_trials_raw": 6,
            "dirty_trial_count": 0,
            "rc_trial_count": 5,
            "rc_spa_benchmark_source": "embedded",
            "headline_retained_fraction": 1.0,
            "untrusted_fraction_line": "coverage bound 5.0% - SEPARATE selection effects.",
            "sharpe_sortino_convention": "Sharpe ddof=1 annualized; Sortino ddof=0 full-sample N.",
        },
    }
    base.update(overrides)
    return base


def _result(**overrides: object):
    dates = pd.date_range("2015-01-31", periods=24, freq="ME")
    net_returns = pd.Series([0.02, -0.01] * 12, index=dates)
    defaults: dict[str, object] = {"net_returns": net_returns, "strategy_id": "momentum-headline"}
    defaults.update(overrides)
    return make_backtest_result(**defaults)


# --- section presence -------------------------------------------------------


def test_every_top_level_section_present():
    ctx = build_report_context(_result(), _report_card(), None)
    for key in ("header", "headline", "trust", "gates", "robustness", "execution", "provenance"):
        assert key in ctx, f"missing section {key!r}"


def test_report_card_none_degrades_gracefully_everywhere():
    ctx = build_report_context(_result(), None, None)
    assert ctx["header"]["verdict"].startswith("NOT EVALUATED")
    assert ctx["headline"]["available"] is False
    assert ctx["gates"]["available"] is False
    assert ctx["robustness"]["available"] is False
    # sections that don't depend on the report card still populate.
    assert ctx["execution"]["execution_mode"] is not None
    assert ctx["provenance"]["strategy_id"] == "momentum-headline"


def test_verdict_none_inside_a_present_report_card_reads_not_evaluated():
    ctx = build_report_context(_result(), _report_card(verdict=None), None)
    assert ctx["header"]["verdict"].startswith("NOT EVALUATED")


# --- dirty badge -------------------------------------------------------------


@pytest.mark.parametrize("dirty", [True, False])
def test_dirty_badge_toggles_with_provenance_dirty(dirty):
    result = _result(dirty=dirty)
    ctx = build_report_context(result, _report_card(), None)
    assert ctx["header"]["dirty"] is dirty
    assert ctx["header"]["dirty_badge"] == ("DIRTY TREE" if dirty else "")


# --- NaN benchmark path -------------------------------------------------------


def test_nan_benchmark_sharpe_renders_no_usable_benchmark_line():
    metrics = dict(_METRICS)
    metrics["benchmark_sharpe"] = float("nan")
    metrics["beta"] = float("nan")
    metrics["information_ratio"] = float("nan")
    card = _report_card(basic=_basic(metrics=metrics))
    ctx = build_report_context(_result(), card, None)
    assert "no usable benchmark" in ctx["headline"]["benchmark_line"]
    # never a bare "nan" for the Sharpe cell either.
    sharpe_row = next(r for r in ctx["headline"]["rows"] if r["label"] == "Benchmark Sharpe")
    assert sharpe_row["net"] == "n/a (no usable benchmark)"
    assert "nan" not in sharpe_row["net"]


def test_no_value_is_ever_a_bare_nan_string():
    metrics = dict(_METRICS)
    metrics["net_sortino"] = float("nan")
    metrics["net_calmar"] = float("nan")
    card = _report_card(basic=_basic(metrics=metrics))
    ctx = build_report_context(_result(), card, None)
    rendered = str(ctx)
    assert "nan" not in rendered.lower() or "n/a" in rendered  # every nan is behind "n/a (...)"
    for row in ctx["headline"]["rows"]:
        assert row["net"] != "nan"


def test_sortino_nan_has_a_specific_no_downside_observations_reason():
    # quant-gate VERDICT.md M07 cycle-1 finding 5: Sortino's NaN case (zero
    # downside deviation - metrics.sortino's own zero-vol guard) deserves a
    # specific reason, not the generic "not available".
    metrics = dict(_METRICS)
    metrics["net_sortino"] = float("nan")
    card = _report_card(basic=_basic(metrics=metrics))
    ctx = build_report_context(_result(), card, None)
    sortino_row = next(r for r in ctx["headline"]["rows"] if r["label"] == "Sortino (net)")
    assert sortino_row["net"] == "n/a (no downside observations)"


def test_infinity_renders_as_unbounded_not_bare_inf():
    # quant-gate VERDICT.md M07 cycle-1 finding 5.
    assert context_module._num(float("inf")) == "unbounded (n/a)"
    assert context_module._pct(float("inf")) == "unbounded (n/a)"
    assert context_module._num(float("-inf")) == "unbounded (n/a)"


# --- verbatim carried-note strings ------------------------------------------


def test_coverage_bound_definition_is_the_exact_carried_sentence():
    ctx = build_report_context(_result(), _report_card(), None)
    assert ctx["trust"]["coverage_bound_definition"] == context_module.COVERAGE_BOUND_DEFINITION
    assert "worst sampled rebalance-date year" in ctx["trust"]["coverage_bound_definition"]
    assert (
        "a ceiling on invisibility, not a return impact"
        in (ctx["trust"]["coverage_bound_definition"])
    )


def test_known_caveats_appear_verbatim():
    ctx = build_report_context(_result(), _report_card(), None)
    assert "a known caveat, verbatim." in ctx["trust"]["known_caveats"]


def test_extreme_return_direction_caveats_present_for_both_books():
    ctx = build_report_context(_result(), _report_card(), None)
    caveats = " ".join(ctx["trust"]["extreme_return_caveats"])
    assert "CONSERVATIVE: truncates a genuine right tail" in caveats
    assert "ANTI-CONSERVATIVE: hides an adverse move" in caveats


def test_rolling_ported_convention_note_present_verbatim():
    ctx = build_report_context(_result(), _report_card(), None)
    assert (
        ctx["robustness"]["rolling_ported_convention_note"]
        == context_module.ROLLING_PORTED_CONVENTION_NOTE
    )
    assert (
        "each window's first return is omitted from CAGR and hidden from drawdown"
        in (ctx["robustness"]["rolling_ported_convention_note"])
    )


def test_sensitivity_no_cliff_score_shown_only_beside_min_net_sharpe():
    sensitivity = {
        "param_axes": {"lookback_months": [9, 12, 15]},
        "base_point": {"lookback_months": 12},
        "trials": [],
        "surface": {"(9,)": 1.0, "(12,)": 1.2, "(15,)": 1.4},
        "no_cliff_score": 0.8,
        "neighbourhood_size": 3,
        "neighbourhood_truncated": False,
        "nan_points": 0,
    }
    card = _report_card(basic=_basic(sensitivity=sensitivity))
    ctx = build_report_context(_result(), card, None)
    sens_ctx = ctx["robustness"]["sensitivity"]
    assert sens_ctx is not None
    assert "never evidence of quality by itself" in sens_ctx["no_cliff_gate_reason"]
    assert "gated ALONGSIDE no_cliff_score" in sens_ctx["min_net_sharpe_gate_reason"]
    rows = {r["point_label"]: r for r in sens_ctx["surface_rows"]}
    assert rows["lookback_months=9"]["net_sharpe"] == "1.00"
    assert rows["lookback_months=12"]["is_base_point"] is True
    assert rows["lookback_months=9"]["is_base_point"] is False
    assert sens_ctx["base_point_label"] == "lookback_months=12"


def _real_walk_forward_result():
    """A genuine `walk_forward_blend(...)` result, not a hand-written dict -
    quant-gate VERDICT.md M07 cycle-1 finding 1 (BLOCKER): the ORIGINAL
    version of this fixture assumed `comparison`'s shape rather than reading
    it from the producer, and `context.py`'s transposition bug (row/column
    axes swapped) passed against it silently. Building the real
    `WalkForwardResult` here means the fixture can never again disagree with
    `walk_forward.py`'s own `to_json()`."""
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


def test_walk_forward_section_carries_no_embargo_and_ranking_lines():
    wf_result = _real_walk_forward_result()
    walk_forward = wf_result.to_json()
    card = _report_card(basic=_basic(walk_forward=walk_forward))
    ctx = build_report_context(_result(), card, None)
    wf_ctx = ctx["robustness"]["walk_forward"]
    assert wf_ctx is not None
    assert wf_ctx["no_embargo_note"] == context_module.WALK_FORWARD_NO_EMBARGO_NOTE
    assert "STRICTLY PRIOR" in wf_ctx["no_embargo_note"]
    assert wf_ctx["ranking_agreement_line"] == (
        "ranking agreement under both cost conventions: not checked"
    )
    assert "per-step training Sharpes are NOT retained" in wf_ctx["training_sharpes_note"]
    assert (
        wf_ctx["comparison_ported_convention_note"] == context_module.ROLLING_PORTED_CONVENTION_NOTE
    )

    # quant-gate VERDICT.md M07 cycle-1 finding 1: every comparison cell must
    # be a REAL number, never "n/a" under the wrong axes.
    assert len(wf_ctx["comparison_rows"]) == len(wf_result.comparison.columns)
    for row in wf_ctx["comparison_rows"]:
        assert row["cagr"] != "n/a (not available)", row
        assert row["sharpe"] != "n/a (not available)", row
    labels = {row["label"] for row in wf_ctx["comparison_rows"]}
    assert "Walk-Forward" in labels

    # the chosen-weight sequence itself, one column per child, not only a PNG.
    assert len(wf_ctx["chosen_rows"]) == len(wf_result.chosen_weights)
    first_row = wf_ctx["chosen_rows"][0]
    assert set(first_row["weights_by_child"]) == {"momentum", "value"}
    for row in wf_ctx["chosen_rows"]:
        total = sum(float(v) for v in row["weights_by_child"].values())
        assert abs(total - 1.0) < 1e-6


def test_execution_convention_close_and_next_open_notes():
    result_close = _result()
    result_close.provenance["backtest_config"]["execution"] = "close"
    ctx_close = build_report_context(result_close, _report_card(), None)
    assert "same-session close" in ctx_close["execution"]["execution_note"]

    result_next = _result()
    result_next.provenance["backtest_config"]["execution"] = "next_open"
    ctx_next = build_report_context(result_next, _report_card(), None)
    assert "next session's open" in ctx_next["execution"]["execution_note"]
    assert "open-to-open" in ctx_next["execution"]["execution_note"]


# --- gate value formatting ----------------------------------------------------


def test_gate_values_are_never_a_repr_and_always_fixed_precision():
    ctx = build_report_context(_result(), _report_card(), None)
    for gate in ctx["gates"]["hard"] + ctx["gates"]["soft"]:
        assert "np.float64" not in gate["value"]
        assert "np.float64" not in gate["threshold"]


def test_monte_carlo_percentiles_shown_in_gates_section():
    ctx = build_report_context(_result(), _report_card(), None)
    detail = ctx["gates"]["monte_carlo_detail"]
    assert detail is not None
    assert "CAGR p5/p50/p95" in detail
    assert "Sharpe p5/p50/p95" in detail


def test_dsr_nan_because_registry_thin_has_a_distinct_reason():
    card = _report_card(dsr=float("nan"))
    ctx = build_report_context(_result(), card, None)
    assert "registry too thin" in ctx["gates"]["dsr"]
    assert math.isnan(float("nan"))  # sanity: NaN input is exercised above


# --- RC/SPA measured over-sizing (M06 cycle-3 carried item, M07 addendum) ---


def test_rc_spa_measured_size_shown_at_the_shipped_block_len():
    card = _report_card()
    card["rc"]["block_len"] = 6.0
    card["spa"]["block_len"] = 6.0
    ctx = build_report_context(_result(), card, None)
    assert "measured size ≈ 0.12 at the 0.10 bar" in ctx["gates"]["rc_detail"]
    assert "treat the bar as approximate" in ctx["gates"]["rc_detail"]
    assert "measured size ≈ 0.12 at the 0.10 bar" in ctx["gates"]["spa_detail"]


def test_rc_spa_measured_size_absent_note_at_a_different_block_len():
    # the default fixture's rc/spa use block_len=2.0, not the shipped 6.0 the
    # measurement covers - must not claim a calibration it never measured.
    ctx = build_report_context(_result(), _report_card(), None)
    assert "not measured at the block_len this run used (2.0)" in ctx["gates"]["rc_detail"]
    assert "measured size ≈" not in ctx["gates"]["rc_detail"]


# --- quant-gate REVIEW.md iteration-2 findings ------------------------------


def test_psr_and_monte_carlo_gates_carry_the_m06_informational_note():
    ctx = build_report_context(_result(), _report_card(), None)
    psr_gate = next(g for g in ctx["gates"]["soft"] if g["name"] == "probabilistic_sharpe_ratio")
    mc_gate = next(g for g in ctx["gates"]["soft"] if g["name"] == "monte_carlo_drawdown")
    assert (
        "min_psr 0.95 binds only below an annualised Sharpe of about 0.47 on a 12-year "
        "monthly book" in psr_gate["note"]
    )
    assert (
        "the Monte Carlo drawdown gate sits at the centre of its own statistic's null"
        in mc_gate["note"]
    )
    assert "neither is evidence of quality" in psr_gate["note"]
    assert "neither is evidence of quality" in mc_gate["note"]
    # other gates must NOT carry either informational note.
    dsr_gate = next(g for g in ctx["gates"]["hard"] if g["name"] == "deflated_sharpe_ratio")
    assert dsr_gate["note"] == ""


def test_n_trials_raw_and_dirty_count_present_beside_deduplicated_n():
    card = _report_card()
    card["provenance"]["n_trials_raw"] = 6
    card["provenance"]["dirty_trial_count"] = 2
    ctx = build_report_context(_result(), card, None)
    assert ctx["gates"]["n_trials"] == 5
    assert ctx["gates"]["n_trials_raw"] == 6
    assert ctx["gates"]["dirty_trial_count"] == 2


def test_gate_reason_is_a_plain_str_never_markup():
    # quant-gate REVIEW.md finding 1: `reason` must NOT be marked Markup-safe
    # (it can carry ticker symbols / other external-adjacent data via
    # report_card.py's capacity gate) - only the separate `note` field (a
    # static internal literal) may be.
    from markupsafe import Markup

    ctx = build_report_context(_result(), _report_card(), None)
    for gate in ctx["gates"]["hard"] + ctx["gates"]["soft"]:
        assert not isinstance(gate["reason"], Markup)
