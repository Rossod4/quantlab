"""Unit tests for src/quantlab/validation/reality_check.py.

The synthetic-null calibration test (acceptance criterion 4's KS check) is
run for White RC only, at the packet's own N=200 sims x B=200 scale; Hansen
SPA's directional relationship to RC ("SPA p <= RC p ... assert
directionally") is checked on ONE constructed dataset rather than repeating
the full N=200 calibration sweep a second time, to keep the whole suite
under the 90s budget - acceptance criterion 4 only requires this
relationship "on the same data", not at calibration scale.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from scipy import stats as scipy_stats

from quantlab.validation.reality_check import (
    TrialMatrixError,
    build_trial_matrix,
    hansen_spa,
    white_reality_check,
)
from quantlab.validation.registry import TrialsRegistry
from tests._validation_fixtures import make_backtest_result

N_SIMS = 200
B = 200
T_PERIODS = 40
K_TRIALS = 4


def _iid_noise_matrix(rng: np.random.Generator, t: int, k: int) -> pd.DataFrame:
    dates = pd.date_range("2015-01-31", periods=t, freq="ME")
    values = rng.normal(loc=0.0, scale=0.03, size=(t, k))
    return pd.DataFrame(values, index=dates, columns=[f"trial_{i}" for i in range(k)])


# --- synthetic null: p-values ~ Uniform(0, 1) ----------------------------


def test_white_rc_synthetic_null_pvalues_are_uniform():
    # LOW-POWER NOTICE (quant-gate VERDICT.2.md M06 cycle-2 finding D,
    # non-blocking): this test runs at block_len=3.0, NOT the shipped
    # configs/validation.yaml block_len=6.0, and 200 sims does not have
    # power to see the ~0.117-0.123 measured over-sizing documented in
    # reality_check.py's module docstring at block_len=6.0 - a KS-vs-uniform
    # check at this scale is a sanity check on the STATISTIC's construction,
    # not a calibration measurement at the shipped configuration. See
    # test_white_rc_size_at_shipped_block_length_is_bounded below for a
    # size bound at the gate's own 0.10 bar and the shipped block_len.
    #
    # p_value = (1 + count) / (B + 1) (quant-gate VERDICT.md M06 cycle-1
    # item 12/finding 7) - never exactly 0.0, unlike the plain count/B
    # estimator, which would otherwise put an atom of mass at 0 under the
    # null (not a valid draw from a continuous Uniform(0,1)) and bias this
    # KS comparison. The ks_p > 0.01 bar below still holds under the
    # corrected estimator - re-verified empirically, not just assumed.
    rng = np.random.default_rng(0)
    p_values = []
    for sim in range(N_SIMS):
        matrix = _iid_noise_matrix(rng, T_PERIODS, K_TRIALS)
        result = white_reality_check(matrix, b=B, block_len=3.0, seed=1000 + sim)
        p_values.append(result.p_value)

    ks_stat, ks_p = scipy_stats.kstest(p_values, "uniform")
    assert ks_p > 0.01, f"p-values not consistent with Uniform(0,1): KS stat={ks_stat}, p={ks_p}"


def test_white_rc_size_at_shipped_block_length_is_bounded():
    """quant-gate VERDICT.2.md M06 cycle-2 finding D (non-blocking): a real
    SIZE bound at the gate's own max_rc_pvalue=0.10 bar, at the SHIPPED
    configs/validation.yaml block_len=6.0 (not block_len=3.0 above), with
    enough simulations to have power to see the measured over-sizing this
    module's docstring documents (~0.117-0.123 over 600 sims at B=?; here
    300 sims at a smaller B to stay inside the suite's 90s budget).

    This is intentionally a WIDE tolerance band, not a tight calibration
    check: the point is to catch a gross regression in the bootstrap or
    p-value formula (size collapsing toward 0 or blowing up toward 1),
    while tolerating the run-to-run noise of 300 sims at this B/T/K scale.
    The measured size at block_len=6.0 is documented ABOVE nominal (0.10),
    not below it - a size that fell back to ~0.10 or lower would itself be
    a legitimate finding (the over-sizing going away), so the band is
    centred above 0.10 with room on both sides rather than requiring
    size <= 0.10.
    """
    rng = np.random.default_rng(123)
    n_sims = 300
    b = 150
    exceed = 0
    for sim in range(n_sims):
        matrix = _iid_noise_matrix(rng, T_PERIODS, K_TRIALS)
        result = white_reality_check(matrix, b=b, block_len=6.0, seed=5000 + sim)
        if result.p_value <= 0.10:
            exceed += 1
    size = exceed / n_sims
    assert 0.04 <= size <= 0.28, (
        f"White RC size at the 0.10 bar measured {size:.3f} over {n_sims} sims at the shipped "
        "block_len=6.0 - outside the tolerance band around the documented ~0.12 measured size"
    )


# --- planted alternative: small p-value -----------------------------------


def test_white_rc_planted_alternative_pvalue_is_small():
    rng = np.random.default_rng(42)
    matrix = _iid_noise_matrix(rng, T_PERIODS, K_TRIALS)
    # Plant a clearly profitable trial - a strong, consistent positive mean
    # far larger than the noise scale.
    matrix["trial_planted"] = 0.03 + rng.normal(0.0, 0.01, size=T_PERIODS)

    result = white_reality_check(matrix, b=B, block_len=3.0, seed=7)
    assert result.p_value < 0.05
    assert result.best_trial == "trial_planted"


# --- SPA <= RC directionally, on the same data ----------------------------


def test_spa_pvalue_is_at_most_rc_pvalue_on_the_same_data():
    rng = np.random.default_rng(11)
    matrix = _iid_noise_matrix(rng, T_PERIODS, K_TRIALS)
    # A mix of one clear winner and several mediocre/poor trials, so RC's
    # full-recentering and SPA's consistent recentering genuinely diverge.
    matrix["trial_good"] = 0.02 + rng.normal(0.0, 0.02, size=T_PERIODS)
    matrix["trial_bad"] = -0.03 + rng.normal(0.0, 0.02, size=T_PERIODS)

    rc = white_reality_check(matrix, b=B, block_len=3.0, seed=5)
    spa = hansen_spa(matrix, b=B, block_len=3.0, seed=5)
    assert spa.p_value <= rc.p_value + 1e-9


# --- RealityCheckResult basics --------------------------------------------


def test_white_rc_identifies_the_best_trial():
    dates = pd.date_range("2015-01-31", periods=20, freq="ME")
    matrix = pd.DataFrame(
        {
            "low": pd.Series(0.001, index=dates),
            "high": pd.Series(0.02, index=dates),
        }
    )
    result = white_reality_check(matrix, b=50, block_len=2.0, seed=1)
    assert result.best_trial == "high"
    assert result.n_trials == 2
    assert result.n_periods == 20


def test_reality_check_result_json_round_trips():
    import json

    dates = pd.date_range("2015-01-31", periods=20, freq="ME")
    matrix = pd.DataFrame({"a": pd.Series(0.01, index=dates), "b": pd.Series(0.02, index=dates)})
    result = white_reality_check(matrix, b=30, block_len=2.0, seed=2)
    payload = json.loads(json.dumps(result.to_json()))
    assert payload["test_name"] == "white_rc"
    assert payload["best_trial"] == "b"


# --- build_trial_matrix ----------------------------------------------------


def test_build_trial_matrix_aligns_common_dates_across_registered_trials(tmp_path):
    registry = TrialsRegistry(tmp_path, repo_root=tmp_path)
    dates = pd.date_range("2015-01-31", periods=24, freq="ME")

    for i in range(3):
        net_returns = pd.Series(0.01 * (i + 1), index=dates)
        result = make_backtest_result(net_returns=net_returns, strategy_id=f"momentum-{i:010d}")
        registry.record_backtest(result, family="momentum")

    matrix, excluded, retained = build_trial_matrix(registry, "momentum")
    assert matrix.shape == (24, 3)
    assert excluded == []
    assert retained == {}  # min_overlap_fraction disabled (default 0.0) - nothing measured


def test_build_trial_matrix_raises_with_fewer_than_two_trials(tmp_path):
    registry = TrialsRegistry(tmp_path, repo_root=tmp_path)
    dates = pd.date_range("2015-01-31", periods=10, freq="ME")
    result = make_backtest_result(net_returns=pd.Series(0.01, index=dates))
    registry.record_backtest(result, family="momentum")

    with pytest.raises(ValueError):
        build_trial_matrix(registry, "momentum")


def test_build_trial_matrix_labels_columns_by_full_key_not_strategy_id_alone(tmp_path):
    # quant-gate VERDICT.md M06 cycle-1 finding 2: three trials sharing ONE
    # strategy_id but differing backtest configs (genuinely different
    # return series) must produce THREE columns, not collapse to one.
    registry = TrialsRegistry(tmp_path, repo_root=tmp_path)
    dates = pd.date_range("2015-01-31", periods=24, freq="ME")
    for i, capital in enumerate([1_000_000.0, 2_000_000.0, 3_000_000.0]):
        net_returns = pd.Series(0.01 * (i + 1), index=dates)
        result = make_backtest_result(
            net_returns=net_returns, strategy_id="momentum-deadbeef01", initial_capital=capital
        )
        registry.record_backtest(result, family="momentum")
    # A different strategy_id too, for a 4th distinct key.
    other = make_backtest_result(
        net_returns=pd.Series(0.04, index=dates), strategy_id="momentum-cafebabe02"
    )
    registry.record_backtest(other, family="momentum")

    assert registry.n_trials("momentum") == 4
    matrix, excluded, _retained = build_trial_matrix(registry, "momentum")
    assert matrix.shape == (24, 4)
    assert excluded == []


def test_build_trial_matrix_excludes_trials_below_min_overlap_fraction(tmp_path):
    # quant-gate VERDICT.md M06 cycle-1 finding 10 / item 9: a short outlier
    # (10 of 120 periods, a SUBSET of the long trials' shared window) must
    # be excluded, and the three long survivors must keep their FULL
    # 120-period mutual overlap - not just "the outlier's own fraction is
    # below the floor" (which is trivially false: it retains 100% of
    # itself) but "removing it is what lets everyone else clear the floor".
    registry = TrialsRegistry(tmp_path, repo_root=tmp_path)
    long_dates = pd.date_range("2010-01-31", periods=120, freq="ME")
    short_dates = long_dates[-10:]  # only the last 10 of 120 overlap

    for i in range(3):
        result = make_backtest_result(
            net_returns=pd.Series(0.01 * (i + 1), index=long_dates),
            strategy_id=f"momentum-long{i:02d}",
        )
        registry.record_backtest(result, family="momentum")
    outlier = make_backtest_result(
        net_returns=pd.Series(0.05, index=short_dates), strategy_id="momentum-outlier"
    )
    registry.record_backtest(outlier, family="momentum")

    matrix, excluded, retained = build_trial_matrix(registry, "momentum", min_overlap_fraction=0.8)
    assert matrix.shape == (120, 3)  # the outlier is dropped, survivors keep their full window
    assert len(excluded) == 1
    assert "momentum-outlier" in excluded[0]
    # Every recorded fraction reads 1.0 here - the outlier's own window
    # trivially retains 100% of ITSELF (which is exactly why "is this
    # trial's own fraction low" can never catch it), and the three
    # survivors retain 100% of their full 120-period window once the
    # outlier is gone. Neither number, on its own, names the culprit.
    for fraction in retained.values():
        assert fraction == pytest.approx(1.0)


def test_build_trial_matrix_detects_two_same_length_offset_windows(tmp_path):
    # quant-gate VERDICT.md M06 cycle-1 item 9 (tightened): the case the
    # earlier length-ratio heuristic explicitly missed - two SAME-LENGTH
    # trials whose windows are merely offset, alongside a majority aligned
    # with one of them. A naive "is this trial's OWN fraction below the
    # floor" check would also flag the aligned majority (their fraction
    # drops too, dragged down by the offset trial) unless the algorithm
    # specifically identifies that removing the OFFSET trial (not a
    # majority member) is what fixes it for everyone else.
    registry = TrialsRegistry(tmp_path, repo_root=tmp_path)
    aligned_dates = pd.date_range("2010-01-31", periods=120, freq="ME")
    # Starts exactly where aligned_dates' 61st date is, runs the SAME 120
    # periods forward - same length, shifted by 60, so aligned_dates[60:]
    # (60 dates) is the entire overlap.
    offset_dates = pd.date_range(aligned_dates[60], periods=120, freq="ME")

    for i in range(2):
        result = make_backtest_result(
            net_returns=pd.Series(0.01 * (i + 1), index=aligned_dates),
            strategy_id=f"momentum-aligned{i:02d}",
        )
        registry.record_backtest(result, family="momentum")
    offset_trial = make_backtest_result(
        net_returns=pd.Series(0.02, index=offset_dates), strategy_id="momentum-offset"
    )
    registry.record_backtest(offset_trial, family="momentum")

    matrix, excluded, retained = build_trial_matrix(registry, "momentum", min_overlap_fraction=0.8)

    assert len(excluded) == 1
    assert "momentum-offset" in excluded[0]
    # The two ALIGNED trials survive with their FULL mutual window, not the
    # ~50% they would have shown while the offset trial was still present.
    assert matrix.shape == (120, 2)
    for label, fraction in retained.items():
        if "momentum-aligned" in label:
            assert fraction == pytest.approx(1.0)
        elif "momentum-offset" in label:
            assert fraction == pytest.approx(60 / 120)


# --- headline pinning (quant-gate VERDICT.2.md M06 cycle-2 finding A) ------


def test_headline_trial_is_never_a_removal_candidate(tmp_path):
    """BLOCKING item 1: the exact planted case from the verdict - three
    strong trials aligned 2014-2023 plus a worthless HEADLINE offset to
    2019-2028 (same length, 60-of-120-month overlap, well under the 0.8
    floor). Before this fix, the greedy resolver would drop the HEADLINE
    (removing it grows the three siblings' common window the most) and the
    Reality Check would silently run on the siblings alone. Now the
    headline is never a removal candidate: it cannot be rescued (removing
    a sibling never grows the window while the headline still constrains
    it), so `build_trial_matrix` must raise `TrialMatrixError` naming the
    headline as the cause - never return a matrix built from the siblings.
    """
    registry = TrialsRegistry(tmp_path, repo_root=tmp_path)
    aligned_dates = pd.date_range("2014-01-31", periods=120, freq="ME")
    offset_dates = pd.date_range(aligned_dates[60], periods=120, freq="ME")  # 2019-2028

    for i in range(3):
        sibling = make_backtest_result(
            net_returns=pd.Series(0.02 * (i + 1), index=aligned_dates),
            strategy_id=f"momentum-strong{i:02d}",
        )
        registry.record_backtest(sibling, family="momentum")
    headline = make_backtest_result(
        net_returns=pd.Series(-0.01, index=offset_dates), strategy_id="momentum-headline"
    )
    headline_record = registry.record_backtest(headline, family="momentum")
    headline_label = "|".join(headline_record.key)

    with pytest.raises(TrialMatrixError) as excinfo:
        build_trial_matrix(
            registry, "momentum", min_overlap_fraction=0.8, headline_label=headline_label
        )

    assert excinfo.value.reason_kind == "excluded_by_overlap_floor"
    assert "headline trial excluded by overlap floor" in str(excinfo.value)
    assert "retained_fraction=" in str(excinfo.value)
    # The exclusion bookkeeping must survive the raise (item 2) - a caller
    # catching this must be able to see what was measured, not just that
    # something failed.
    assert headline_label in excinfo.value.retained_fractions
    assert excinfo.value.retained_fractions[headline_label] == pytest.approx(60 / 120)


def test_headline_trial_can_still_be_rescued_by_removing_a_true_outlier(tmp_path):
    # The headline is pinned against REMOVAL, not against being RESCUED:
    # if some OTHER trial is the true outlier constraining the common
    # window, removing that outlier (not the headline) must still succeed,
    # exactly as it would with no headline_label at all.
    registry = TrialsRegistry(tmp_path, repo_root=tmp_path)
    long_dates = pd.date_range("2010-01-31", periods=120, freq="ME")
    short_dates = long_dates[-10:]

    for i in range(2):
        sibling = make_backtest_result(
            net_returns=pd.Series(0.01 * (i + 1), index=long_dates),
            strategy_id=f"momentum-long{i:02d}",
        )
        registry.record_backtest(sibling, family="momentum")
    outlier = make_backtest_result(
        net_returns=pd.Series(0.05, index=short_dates), strategy_id="momentum-outlier"
    )
    registry.record_backtest(outlier, family="momentum")
    headline = make_backtest_result(
        net_returns=pd.Series(0.02, index=long_dates), strategy_id="momentum-headline"
    )
    headline_record = registry.record_backtest(headline, family="momentum")
    headline_label = "|".join(headline_record.key)

    matrix, excluded, retained = build_trial_matrix(
        registry, "momentum", min_overlap_fraction=0.8, headline_label=headline_label
    )

    assert matrix.shape == (120, 3)  # headline + the two long siblings survive
    assert headline_label in matrix.columns
    assert len(excluded) == 1
    assert "momentum-outlier" in excluded[0]
    assert retained[headline_label] == pytest.approx(1.0)


# --- distinguishable rc-is-None causes (item 2) -----------------------------


def test_build_trial_matrix_raises_too_few_trials_recorded(tmp_path):
    registry = TrialsRegistry(tmp_path, repo_root=tmp_path)
    dates = pd.date_range("2015-01-31", periods=10, freq="ME")
    result = make_backtest_result(net_returns=pd.Series(0.01, index=dates))
    registry.record_backtest(result, family="momentum")

    with pytest.raises(TrialMatrixError) as excinfo:
        build_trial_matrix(registry, "momentum")

    assert excinfo.value.reason_kind == "too_few_trials_recorded"
    assert excinfo.value.excluded == []


def test_build_trial_matrix_raises_excluded_by_overlap_floor_without_headline(tmp_path):
    # Same offset-outlier shape as the non-headline overlap test above, but
    # tightened so removing the outlier still leaves fewer than 2 survivors
    # - the "excluded_by_overlap_floor" cause, not "too_few_trials_recorded"
    # (nothing was ever excluded in that case) nor "no_common_dates" (dates
    # DO overlap; the floor is what excludes them).
    registry = TrialsRegistry(tmp_path, repo_root=tmp_path)
    long_dates = pd.date_range("2010-01-31", periods=120, freq="ME")
    short_dates = long_dates[-10:]
    long_result = make_backtest_result(
        net_returns=pd.Series(0.01, index=long_dates), strategy_id="momentum-long00"
    )
    registry.record_backtest(long_result, family="momentum")
    outlier = make_backtest_result(
        net_returns=pd.Series(0.05, index=short_dates), strategy_id="momentum-outlier"
    )
    registry.record_backtest(outlier, family="momentum")

    with pytest.raises(TrialMatrixError) as excinfo:
        build_trial_matrix(registry, "momentum", min_overlap_fraction=0.8)

    assert excinfo.value.reason_kind == "excluded_by_overlap_floor"
    assert len(excinfo.value.excluded) == 1
    assert "momentum-outlier" in excinfo.value.excluded[0]


def test_build_trial_matrix_raises_no_common_dates(tmp_path):
    # Two trials with genuinely disjoint date ranges and the floor DISABLED
    # (default min_overlap_fraction=0.0) - no exclusion ever runs, so this
    # is a pure "no_common_dates" cause, not "excluded_by_overlap_floor".
    registry = TrialsRegistry(tmp_path, repo_root=tmp_path)
    dates_a = pd.date_range("2010-01-31", periods=12, freq="ME")
    dates_b = pd.date_range("2020-01-31", periods=12, freq="ME")
    a = make_backtest_result(net_returns=pd.Series(0.01, index=dates_a), strategy_id="momentum-a0")
    b = make_backtest_result(net_returns=pd.Series(0.02, index=dates_b), strategy_id="momentum-b0")
    registry.record_backtest(a, family="momentum")
    registry.record_backtest(b, family="momentum")

    with pytest.raises(TrialMatrixError) as excinfo:
        build_trial_matrix(registry, "momentum")

    assert excinfo.value.reason_kind == "no_common_dates"
    assert excinfo.value.excluded == []
