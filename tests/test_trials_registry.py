"""Unit tests for src/quantlab/validation/registry.py (the M06 trials
registry - named test_trials_registry.py rather than the packet's literal
"test_registry.py" because tests/test_registry.py already exists for
strategies/registry.py, from M03)."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from quantlab.validation.registry import TrialsRegistry
from quantlab.validation.sensitivity import SensitivityResult, SensitivityTrial
from tests._validation_fixtures import make_backtest_result


def _dates(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2015-01-31", periods=n, freq="ME")


# --- idempotence (acceptance criterion 7) ---------------------------------


def test_same_key_recorded_twice_does_not_increment_n(tmp_path):
    registry = TrialsRegistry(tmp_path, repo_root=tmp_path)
    result = make_backtest_result(
        net_returns=pd.Series(0.01, index=_dates(24)), strategy_id="momentum-aaaa"
    )
    registry.record_backtest(result, family="momentum")
    registry.record_backtest(result, family="momentum")  # identical key, rerun
    assert registry.n_trials("momentum") == 1


def test_changed_param_increments_n(tmp_path):
    registry = TrialsRegistry(tmp_path, repo_root=tmp_path)
    result_a = make_backtest_result(
        net_returns=pd.Series(0.01, index=_dates(24)), strategy_id="momentum-aaaa"
    )
    result_b = make_backtest_result(
        net_returns=pd.Series(0.02, index=_dates(24)), strategy_id="momentum-bbbb"
    )
    registry.record_backtest(result_a, family="momentum")
    registry.record_backtest(result_b, family="momentum")
    assert registry.n_trials("momentum") == 2


def test_semantics_version_change_mints_a_new_key(tmp_path):
    # n_trials_raw() (pre-series-dedup) is the right assertion for KEY
    # minting specifically - both runs here share byte-identical
    # net_returns, so n_trials() (post-dedup, quant-gate VERDICT.md M06
    # cycle-1 finding 1) correctly collapses them to ONE distinct trial;
    # see test_changed_backtest_config_with_genuinely_different_returns_
    # increments_n below for the case where n_trials() also increments.
    registry = TrialsRegistry(tmp_path, repo_root=tmp_path)
    result_v1 = make_backtest_result(
        net_returns=pd.Series(0.01, index=_dates(24)),
        strategy_id="momentum-aaaa",
        data_semantics_version="m03b",
    )
    result_v2 = make_backtest_result(
        net_returns=pd.Series(0.01, index=_dates(24)),
        strategy_id="momentum-aaaa",
        data_semantics_version="m04",
    )
    registry.record_backtest(result_v1, family="momentum")
    registry.record_backtest(result_v2, family="momentum")
    assert registry.n_trials_raw("momentum") == 2
    assert registry.n_trials("momentum") == 1


def test_changed_backtest_config_mints_a_new_raw_key(tmp_path):
    # Same rationale as above: byte-identical returns collapse to one
    # DISTINCT trial even though the raw key count is 2.
    registry = TrialsRegistry(tmp_path, repo_root=tmp_path)
    result_a = make_backtest_result(
        net_returns=pd.Series(0.01, index=_dates(24)), strategy_id="momentum-aaaa"
    )
    result_b = make_backtest_result(
        net_returns=pd.Series(0.01, index=_dates(24)),
        strategy_id="momentum-aaaa",
        initial_capital=2_000_000.0,
    )
    registry.record_backtest(result_a, family="momentum")
    registry.record_backtest(result_b, family="momentum")
    assert registry.n_trials_raw("momentum") == 2
    assert registry.n_trials("momentum") == 1


def test_changed_backtest_config_with_genuinely_different_returns_increments_n(tmp_path):
    # quant-gate VERDICT.md M06 cycle-1 finding 1's OWN scenario, inverted:
    # a config change that actually changes the strategy's realised returns
    # (not just a cosmetic field like initial_capital) IS a genuinely
    # distinct trial, and n_trials() must still count it as one.
    registry = TrialsRegistry(tmp_path, repo_root=tmp_path)
    result_a = make_backtest_result(
        net_returns=pd.Series(0.01, index=_dates(24)), strategy_id="momentum-aaaa"
    )
    result_b = make_backtest_result(
        net_returns=pd.Series(0.02, index=_dates(24)),
        strategy_id="momentum-aaaa",
        initial_capital=2_000_000.0,
    )
    registry.record_backtest(result_a, family="momentum")
    registry.record_backtest(result_b, family="momentum")
    assert registry.n_trials_raw("momentum") == 2
    assert registry.n_trials("momentum") == 2


def test_n_trials_is_per_family(tmp_path):
    registry = TrialsRegistry(tmp_path, repo_root=tmp_path)
    momentum = make_backtest_result(
        net_returns=pd.Series(0.01, index=_dates(24)), strategy_id="momentum-aaaa"
    )
    value = make_backtest_result(
        net_returns=pd.Series(0.01, index=_dates(24)), strategy_id="value_composite-aaaa"
    )
    registry.record_backtest(momentum, family="momentum")
    registry.record_backtest(value, family="value_composite")
    assert registry.n_trials("momentum") == 1
    assert registry.n_trials("value_composite") == 1


# --- series storage --------------------------------------------------------


def test_record_backtest_stores_a_loadable_return_series(tmp_path):
    registry = TrialsRegistry(tmp_path, repo_root=tmp_path)
    net_returns = pd.Series([0.01, -0.02, 0.03], index=_dates(3))
    result = make_backtest_result(net_returns=net_returns, strategy_id="momentum-aaaa")
    record = registry.record_backtest(result, family="momentum")

    assert record.series_path is not None
    loaded = registry.load_series(record)
    pd.testing.assert_series_equal(loaded, net_returns, check_names=False, check_freq=False)


def test_trials_with_series_only_excludes_sensitivity_trials_without_one(tmp_path):
    registry = TrialsRegistry(tmp_path, repo_root=tmp_path)
    result = make_backtest_result(
        net_returns=pd.Series(0.01, index=_dates(12)), strategy_id="momentum-aaaa"
    )
    registry.record_backtest(result, family="momentum")

    sensitivity = SensitivityResult(
        param_axes={"lookback_months": [9, 12, 15]},
        base_point={"lookback_months": 12},
        trials=[
            SensitivityTrial(
                strategy_id="momentum-point-1", params={"lookback_months": 9}, net_sharpe=0.5
            ),
        ],
        surface=pd.Series([0.5], index=pd.Index([(9,)], name=("lookback_months",))),
        no_cliff_score=1.0,
        neighbourhood_size=1,
        neighbourhood_truncated=True,
    )
    registry.record_sensitivity(sensitivity, family="momentum")

    all_trials = registry.trials("momentum")
    with_series = registry.trials("momentum", with_series_only=True)
    assert len(all_trials) == 2
    assert len(with_series) == 1
    assert with_series[0].source == "backtest"


def test_record_sensitivity_stores_series_when_caller_supplies_one(tmp_path):
    registry = TrialsRegistry(tmp_path, repo_root=tmp_path)
    net_returns = pd.Series([0.01, 0.02], index=_dates(2))
    sensitivity = SensitivityResult(
        param_axes={"lookback_months": [9, 12]},
        base_point={"lookback_months": 9},
        trials=[
            SensitivityTrial(
                strategy_id="momentum-point-1", params={"lookback_months": 9}, net_sharpe=0.5
            ),
        ],
        surface=pd.Series([0.5], index=pd.Index([(9,)], name=("lookback_months",))),
        no_cliff_score=1.0,
        neighbourhood_size=1,
        neighbourhood_truncated=True,
    )
    records = registry.record_sensitivity(
        sensitivity, family="momentum", net_returns_by_strategy_id={"momentum-point-1": net_returns}
    )
    assert records[0].series_path is not None
    loaded = registry.load_series(records[0])
    pd.testing.assert_series_equal(loaded, net_returns, check_names=False, check_freq=False)


# --- var_sr_trials -----------------------------------------------------------


def test_var_sr_trials_excludes_nan_sharpes(tmp_path):
    # var_sr_trials() reads net_sharpe_per_period (quant-gate REVIEW.md M06
    # cycle-1 finding 1), not the annualized net_sharpe.
    registry = TrialsRegistry(tmp_path, repo_root=tmp_path)
    # Alternating (not constant) values - a constant series has zero
    # variance and sharpe_ratio()/raw_sharpe() return NaN for it, which
    # would contaminate this test's own finite-Sharpe count.
    for i, (hi, lo) in enumerate([(0.02, 0.0), (0.03, 0.01), (0.04, -0.02)]):
        values = [hi if j % 2 == 0 else lo for j in range(24)]
        result = make_backtest_result(
            net_returns=pd.Series(values, index=_dates(24)), strategy_id=f"momentum-{i:04d}"
        )
        registry.record_backtest(result, family="momentum")
    registry.seed_historical_blend_trials(family="momentum")  # NaN-sharpe entries

    trials = registry.trials("momentum")
    finite = [t.net_sharpe_per_period for t in trials if pd.notna(t.net_sharpe_per_period)]
    nan_count = sum(1 for t in trials if pd.isna(t.net_sharpe_per_period))
    assert nan_count == 5  # the five historical entries
    expected_var = pd.Series(finite).var(ddof=1)
    # n_periods=24 -> floor 1/23 = 0.0435, well below this fixture's actual
    # dispersion (~0.674), so the floor does not bind here - see the
    # dedicated floor tests below for when it does.
    assert registry.var_sr_trials("momentum", n_periods=24) == pytest.approx(expected_var)


def test_var_sr_trials_nan_with_fewer_than_two_finite_trials(tmp_path):
    registry = TrialsRegistry(tmp_path, repo_root=tmp_path)
    result = make_backtest_result(
        net_returns=pd.Series(0.01, index=_dates(24)), strategy_id="momentum-aaaa"
    )
    registry.record_backtest(result, family="momentum")
    assert math.isnan(registry.var_sr_trials("momentum", n_periods=24))


def test_var_sr_trials_nan_when_n_periods_not_above_one(tmp_path):
    registry = TrialsRegistry(tmp_path, repo_root=tmp_path)
    result_a = make_backtest_result(
        net_returns=pd.Series([0.01, -0.02], index=_dates(2)), strategy_id="momentum-aaaa"
    )
    result_b = make_backtest_result(
        net_returns=pd.Series([0.02, -0.01], index=_dates(2)), strategy_id="momentum-bbbb"
    )
    registry.record_backtest(result_a, family="momentum")
    registry.record_backtest(result_b, family="momentum")
    assert math.isnan(registry.var_sr_trials("momentum", n_periods=1))
    assert math.isnan(registry.var_sr_trials("momentum", n_periods=0))


# --- var_sr_trials floor (quant-gate VERDICT.md M06 cycle-1 finding 1c) -----


def _alternating(hi: float, lo: float, n: int) -> pd.Series:
    values = [hi if i % 2 == 0 else lo for i in range(n)]
    return pd.Series(values, index=_dates(n))


def test_var_sr_trials_floors_at_null_sampling_variance(tmp_path):
    # Several DISTINCT trials (genuinely different return series - not
    # deduplicated) that happen to share an IDENTICAL per-period Sharpe
    # (same ratio, different scale) have v_hat=0 exactly - the floor
    # 1/(n_periods-1) must apply instead of returning 0.
    registry = TrialsRegistry(tmp_path, repo_root=tmp_path)
    n = 24
    for i, scale in enumerate([1.0, 2.0, 3.0, 0.5]):
        # hi/lo ratio fixed -> identical per-period Sharpe; scale varies ->
        # genuinely different (non-duplicate) return values.
        result = make_backtest_result(
            net_returns=_alternating(0.02 * scale, -0.01 * scale, n),
            strategy_id=f"momentum-{i:04d}",
        )
        registry.record_backtest(result, family="momentum")

    assert registry.n_trials("momentum") == 4  # genuinely distinct series
    v_hat = registry.var_sr_trials("momentum", n_periods=n)
    expected_floor = 1.0 / (n - 1)
    assert v_hat == pytest.approx(expected_floor)


def test_dsr_does_not_rise_after_many_identical_sharpe_trials_are_added(tmp_path):
    from quantlab.validation.deflated_sharpe import deflated_sharpe_ratio
    from quantlab.validation.metrics import raw_sharpe

    # quant-gate VERDICT.md M06 cycle-1 finding 1's own required regression:
    # identical-Sharpe (but genuinely distinct) trials at N=2/10/100 must
    # give STRICTLY DECREASING DSR, not the pre-fix invariant DSR.
    registry = TrialsRegistry(tmp_path, repo_root=tmp_path)
    n = 60
    headline = _alternating(0.03, -0.01, n)
    registry.record_backtest(
        make_backtest_result(net_returns=headline, strategy_id="momentum-headline"),
        family="momentum",
    )
    sr = raw_sharpe(headline)
    skew, kurt = 0.0, 1.0  # exact for an equal-count alternating series

    dsr_values = []
    n_trials_values = [2, 10, 100]
    scale = 1.0
    added = 1  # the headline itself
    for target_n in n_trials_values:
        while added < target_n:
            scale += 0.37  # keep genuinely distinct (different series_hash)
            sibling = _alternating(0.02 * scale, -0.01 * scale, n)
            registry.record_backtest(
                make_backtest_result(net_returns=sibling, strategy_id=f"momentum-sib{added:04d}"),
                family="momentum",
            )
            added += 1
        assert registry.n_trials("momentum") == target_n
        var_sr_trials = registry.var_sr_trials("momentum", n_periods=n)
        dsr_values.append(deflated_sharpe_ratio(sr, target_n, var_sr_trials, n, skew, kurt))

    for earlier, later in zip(dsr_values, dsr_values[1:], strict=False):
        assert later < earlier, dsr_values


def test_dsr_stays_failed_after_15_and_40_byte_identical_cosmetic_reruns(tmp_path):
    from quantlab.validation.deflated_sharpe import deflated_sharpe_ratio
    from quantlab.validation.metrics import raw_sharpe

    # quant-gate VERDICT.md M06 cycle-1 finding 1's exact reproduction: 9
    # genuinely dispersed siblings plus a headline, min_dsr=0.95-style bar,
    # then recording byte-identical reruns of the HEADLINE that differ only
    # in a cosmetic config field (initial_capital) must NOT move DSR from
    # FAIL to PASS.
    registry = TrialsRegistry(tmp_path, repo_root=tmp_path)
    n = 48
    headline_returns = _alternating(0.012, 0.002, n)
    registry.record_backtest(
        make_backtest_result(net_returns=headline_returns, strategy_id="momentum-headline"),
        family="momentum",
    )
    for i in range(9):
        sibling = _alternating(0.006 + 0.004 * i, -0.008 + 0.003 * i, n)
        registry.record_backtest(
            make_backtest_result(net_returns=sibling, strategy_id=f"momentum-sib{i:02d}"),
            family="momentum",
        )
    assert registry.n_trials("momentum") == 10

    sr = raw_sharpe(headline_returns)
    skew, kurt = 0.0, 1.0
    min_dsr = 0.95

    def _current_dsr() -> float:
        n_trials = registry.n_trials("momentum")
        var_sr_trials = registry.var_sr_trials("momentum", n_periods=n)
        return deflated_sharpe_ratio(sr, n_trials, var_sr_trials, n, skew, kurt)

    baseline_dsr = _current_dsr()
    assert baseline_dsr < min_dsr, "fixture must start FAIL for this regression to mean anything"

    for rerun_count in (15, 40):
        while registry.n_trials_raw("momentum") < 1 + 9 + rerun_count:
            k = registry.n_trials_raw("momentum")
            cosmetic = make_backtest_result(
                net_returns=headline_returns,  # byte-identical
                strategy_id="momentum-headline",
                initial_capital=1_000_000.0 + 1000.0 * k,  # cosmetic-only difference
            )
            registry.record_backtest(cosmetic, family="momentum")
        assert registry.n_trials("momentum") == 10  # dedup holds regardless of rerun_count
        assert _current_dsr() < min_dsr, f"DSR must still FAIL after {rerun_count} cosmetic reruns"


def test_dsr_near_duplicate_headline_reruns_move_but_stay_bounded_then_turn_back_down(tmp_path):
    """quant-gate VERDICT.2.md M06 cycle-2 finding B (non-blocking, carried
    from cycle 1's finding 1's own residual): unlike BYTE-IDENTICAL reruns
    (fully flat, see the test above), NEAR-duplicate reruns of the headline
    - a tiny deterministic perturbation each time, standing in for a real
    1bp cost change - hash as a genuinely NEW distinct trial (unlike the
    byte-identical case) and can still move DSR across a threshold before
    the `1/(n_periods-1)` variance floor binds. This reproduces VERDICT.2's
    own measured SHAPE (DSR rises as var_sr_trials shrinks toward the
    floor, peaks exactly where the floor first binds, then TURNS BACK DOWN
    as N keeps growing with var_sr_trials pinned) at a small, fast scale -
    not a further code fix, since the underlying mechanism (more genuinely
    distinct trials changing N and var_sr_trials) is doing exactly what it
    should; report_card.py discloses this beside the DSR badge instead (see
    test_report_card.py's disclosure-text assertion).

    Fixture design: n=12 periods (floor = 1/11 ~ 0.0909) and 3 background
    siblings whose per-period Sharpes straddle the headline's, chosen (by a
    numeric probe, not hand-derived) so the family's baseline dispersion
    is a few times the floor - close enough that ~10 tiny near-duplicate
    headline reruns are enough to drive the sample variance down to the
    floor, instead of needing hundreds.
    """
    from quantlab.validation.deflated_sharpe import deflated_sharpe_ratio
    from quantlab.validation.metrics import raw_sharpe

    registry = TrialsRegistry(tmp_path, repo_root=tmp_path)
    n = 12
    headline_returns = _alternating(0.03, 0.00, n)
    registry.record_backtest(
        make_backtest_result(net_returns=headline_returns, strategy_id="momentum-headline"),
        family="momentum",
    )
    for i, (hi, lo) in enumerate([(0.018, 0.006), (0.036, -0.006), (0.042, -0.012)]):
        registry.record_backtest(
            make_backtest_result(
                net_returns=_alternating(hi, lo, n), strategy_id=f"momentum-sib{i:02d}"
            ),
            family="momentum",
        )
    assert registry.n_trials("momentum") == 4

    sr = raw_sharpe(headline_returns)
    skew, kurt = 0.0, 1.0
    floor = 1.0 / (n - 1)
    assert registry.var_sr_trials("momentum", n_periods=n) > floor * 2, (
        "fixture must start comfortably above the floor for this regression to mean anything"
    )

    dsr_values: list[float] = []
    var_values: list[float] = []

    def _record() -> None:
        n_trials = registry.n_trials("momentum")
        var_sr_trials = registry.var_sr_trials("momentum", n_periods=n)
        var_values.append(var_sr_trials)
        dsr_values.append(deflated_sharpe_ratio(sr, n_trials, var_sr_trials, n, skew, kurt))

    # Each rerun is a NEAR-duplicate: a real 1bp cost change moves BOTH the
    # backtest config (a new `initial_capital`-style stand-in, so this is a
    # genuinely NEW registry key - two calls with an IDENTICAL key would
    # otherwise silently no-op, since `trials()` keeps only the first-seen
    # record per key) AND the returns themselves by a tiny, distinct amount
    # each time - a genuinely different byte sequence, so series_hash dedup
    # does NOT collapse these the way it does the byte-identical case above.
    for k in range(1, 25):
        bumped = headline_returns + 1e-6 * k
        registry.record_backtest(
            make_backtest_result(
                net_returns=bumped,
                strategy_id="momentum-headline",
                initial_capital=1_000_000.0 + 1.0 * k,  # new key each rerun, like a cost bump
            ),
            family="momentum",
        )
        _record()

    assert registry.n_trials("momentum") == 4 + 24  # every near-duplicate counts as distinct

    # Bounded: the residual never sends DSR to (or past) certainty.
    assert max(dsr_values) < 0.99, dsr_values

    # Not monotone: this is finding B's residual - DSR RISES for a while as
    # var_sr_trials shrinks, unlike the byte-identical case above which
    # never moves at all.
    assert dsr_values[5] > dsr_values[0], dsr_values

    # But bounded, not unlimited: once var_sr_trials has been driven down
    # to the 1/(n_periods-1) floor, it cannot go any lower, and from that
    # point on DSR must TURN (non-increasing) as N keeps growing - the same
    # guarantee test_dsr_decreases_monotonically_in_n_trials pins at the
    # formula level with a fixed var_sr_trials.
    floor_hit = next(i for i, v in enumerate(var_values) if v == pytest.approx(floor, abs=1e-4))
    tail_dsr = dsr_values[floor_hit:]
    assert len(tail_dsr) >= 5, "fixture must actually reach the floor with room to spare"
    for earlier, later in zip(tail_dsr, tail_dsr[1:], strict=False):
        assert later <= earlier + 1e-9, dsr_values
    # And the peak (at the floor) is genuinely higher than both where it
    # started and where it ends up after further near-duplicates.
    assert dsr_values[floor_hit] > dsr_values[0]
    assert dsr_values[floor_hit] > dsr_values[-1]


# --- historical seeding -----------------------------------------------------


def test_seed_historical_blend_trials_is_idempotent(tmp_path):
    registry = TrialsRegistry(tmp_path, repo_root=tmp_path)
    first = registry.seed_historical_blend_trials()
    second = registry.seed_historical_blend_trials()
    assert len(first) == 5
    assert len(second) == 0  # already seeded - nothing new appended
    assert registry.n_trials("blend") == 5


def test_seed_historical_blend_trials_have_no_series_and_nan_sharpe(tmp_path):
    registry = TrialsRegistry(tmp_path, repo_root=tmp_path)
    records = registry.seed_historical_blend_trials()
    for record in records:
        assert record.series_path is None
        assert math.isnan(record.net_sharpe)
        assert record.source == "historical"
        assert record.dirty_source == "historical"


# --- dirty flag (M04b's provenance["dirty"], with a registry fallback) -----


def test_dirty_flag_falls_back_to_git_status_when_absent_from_provenance(tmp_path):
    # No `dirty=` kwarg -> make_backtest_result omits provenance["dirty"]
    # entirely, exercising the pre-M04b fallback path.
    registry = TrialsRegistry(tmp_path, repo_root=tmp_path)
    result = make_backtest_result(
        net_returns=pd.Series(0.01, index=_dates(12)), strategy_id="momentum-aaaa"
    )
    assert "dirty" not in result.provenance
    record = registry.record_backtest(result, family="momentum")
    assert record.dirty is True  # tmp_path is not a git repo - conservative fallback
    assert record.dirty_source == "registry_at_record_time"


def test_dirty_flag_prefers_provenance_when_present(tmp_path):
    registry = TrialsRegistry(tmp_path, repo_root=tmp_path)
    clean_result = make_backtest_result(
        net_returns=pd.Series(0.01, index=_dates(12)), strategy_id="momentum-clean", dirty=False
    )
    dirty_result = make_backtest_result(
        net_returns=pd.Series(0.01, index=_dates(12)), strategy_id="momentum-dirty", dirty=True
    )
    clean_record = registry.record_backtest(clean_result, family="momentum")
    dirty_record = registry.record_backtest(dirty_result, family="momentum")

    # Both come from a non-git tmp_path, so the registry's OWN fallback
    # would read True for both - proving these values genuinely came from
    # provenance, not the fallback.
    assert clean_record.dirty is False
    assert clean_record.dirty_source == "provenance"
    assert dirty_record.dirty is True
    assert dirty_record.dirty_source == "provenance"
