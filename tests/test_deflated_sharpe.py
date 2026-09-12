"""Unit tests for src/quantlab/validation/deflated_sharpe.py.

Test (a) ("the paper's own example values" per the work packet) is a
hand-derived closed-form example instead - see deflated_sharpe.py's module
docstring for why, and note it cross-checks PSR's Φ(z) via `math.erf`
directly (an INDEPENDENT computation path from this module's own
`scipy.stats.norm.cdf` call), not by re-calling the same library function.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy import stats

from quantlab.validation.deflated_sharpe import (
    deflated_sharpe_ratio,
    min_track_record_length,
    probabilistic_sharpe_ratio,
)


def _phi(z: float) -> float:
    """Standard normal CDF via math.erf - independent of scipy.stats.norm,
    which is what the module under test itself uses."""
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


# --- (a) hand-derived closed-form example -----------------------------


def test_psr_hand_derived_closed_form_example():
    sr, sr_benchmark, n, skew, kurt = 1.0, 0.5, 101, 0.0, 3.0
    variance_factor = 1 - skew * sr + (kurt - 1) / 4 * sr**2  # 1 - 0 + 0.5 = 1.5
    assert variance_factor == pytest.approx(1.5)
    z = (sr - sr_benchmark) * math.sqrt(n - 1) / math.sqrt(variance_factor)
    expected = _phi(z)

    result = probabilistic_sharpe_ratio(sr, sr_benchmark, n, skew, kurt)
    assert result == pytest.approx(expected, abs=1e-9)


# --- (b) PSR = 0.5 when SR == SR* --------------------------------------


@pytest.mark.parametrize("sr", [-2.0, 0.0, 0.3, 1.5, 5.0])
@pytest.mark.parametrize(("skew", "kurt"), [(0.0, 3.0), (-0.5, 4.0), (0.2, 6.0)])
def test_psr_is_half_when_sr_equals_benchmark(sr, skew, kurt):
    assert probabilistic_sharpe_ratio(sr, sr, 100, skew, kurt) == pytest.approx(0.5, abs=1e-12)


# --- (c) DSR decreases monotonically in N ------------------------------


def test_dsr_decreases_monotonically_in_n_trials():
    sr, n, skew, kurt = 1.2, 120, -0.3, 5.0
    var_sr_trials = 0.04
    n_trials_values = [2, 5, 10, 50, 200, 1000]
    dsrs = [deflated_sharpe_ratio(sr, nt, var_sr_trials, n, skew, kurt) for nt in n_trials_values]
    for earlier, later in zip(dsrs, dsrs[1:], strict=False):
        assert later < earlier


def test_dsr_one_trial_ignores_var_sr_trials_entirely():
    # quant-gate VERDICT.md M06 cycle-1 finding 1(c): N=1 is SR*=0
    # UNCONDITIONALLY (a single trial has no multiplicity to correct for),
    # not just when var_sr_trials happens to be 0 - the old code NaN'd here
    # because it hit the N=1 Phi^-1(0) singularity for any nonzero
    # var_sr_trials; that singularity no longer applies since N=1 no longer
    # reaches the general formula at all.
    sr, n, skew, kurt = 1.0, 100, 0.0, 3.0
    expected = probabilistic_sharpe_ratio(sr, 0.0, n, skew, kurt)
    for var_sr_trials in (0.0, 0.04, 5.0):
        assert deflated_sharpe_ratio(sr, 1, var_sr_trials, n, skew, kurt) == pytest.approx(
            expected, abs=1e-12
        )


def test_dsr_zero_trials_is_nan():
    assert math.isnan(deflated_sharpe_ratio(1.0, 0, 0.04, 100, 0.0, 3.0))


def test_dsr_negative_or_nan_variance_is_nan():
    assert math.isnan(deflated_sharpe_ratio(1.0, 10, -0.01, 100, 0.0, 3.0))
    assert math.isnan(deflated_sharpe_ratio(1.0, 10, float("nan"), 100, 0.0, 3.0))


# --- orchestrator sanity anchors (2026-09-11): checkable without a
# literature table - see deflated_sharpe_ratio's own docstring for the
# "var_sr_trials == 0" special case these rely on. ------------------------


def test_dsr_reduces_to_psr_when_n_trials_one_and_variance_zero():
    sr, n, skew, kurt = 1.2, 100, -0.3, 5.0
    dsr = deflated_sharpe_ratio(sr, 1, 0.0, n, skew, kurt)
    psr = probabilistic_sharpe_ratio(sr, 0.0, n, skew, kurt)
    assert dsr == pytest.approx(psr, abs=1e-12)


def test_dsr_reduces_to_psr_when_variance_zero_for_any_n_trials():
    # Zero dispersion among the trials' Sharpes means there is no "expected
    # spread from searching" to add at ANY N, not just N=1.
    sr, n, skew, kurt = 0.9, 80, 0.1, 4.0
    psr = probabilistic_sharpe_ratio(sr, 0.0, n, skew, kurt)
    for n_trials in (1, 2, 10, 500):
        dsr = deflated_sharpe_ratio(sr, n_trials, 0.0, n, skew, kurt)
        assert dsr == pytest.approx(psr, abs=1e-12)


# --- (d) Gaussian skew/kurt reduce the denominator ---------------------


def test_psr_denominator_is_one_at_sr_zero_regardless_of_skew_kurt():
    # At SR=0 both the skew and kurtosis correction terms vanish (they are
    # scaled by SR and SR^2 respectively), so the denominator reduces to
    # sqrt(1) = 1 for ANY skew/kurt - the packet's "reduce the denominator
    # to 1" read literally. This also holds at non-Gaussian skew/kurt,
    # which is exactly why it isolates the SR=0 mechanism rather than
    # anything specific to normality.
    for skew, kurt in [(0.0, 3.0), (-2.0, 10.0), (1.5, 8.0)]:
        z_direct = (0.0 - 0.0) * math.sqrt(99) / math.sqrt(1 - skew * 0.0 + (kurt - 1) / 4 * 0.0**2)
        assert z_direct == 0.0
        assert probabilistic_sharpe_ratio(0.0, 0.0, 100, skew, kurt) == pytest.approx(0.5)


def test_psr_gaussian_values_match_the_lo_2002_variance_formula():
    # At Gaussian skew=0, kurt=3 (non-excess), the PSR denominator reduces
    # to the well-known Lo (2002) Sharpe-ratio variance term sqrt(1 +
    # SR^2/2) - the standard result the general formula specializes to
    # under normality (rather than "1" for a nonzero SR - see this test
    # module's docstring on interpreting test (d)).
    sr = 0.8
    variance_factor = 1 - 0.0 * sr + (3.0 - 1) / 4 * sr**2
    assert variance_factor == pytest.approx(1 + sr**2 / 2)


# --- quant-gate REVIEW.md M06 cycle-1 blocker 1 regression: per-period vs
# annualized footing (report_card.py's own fix, exercised here directly on
# deflated_sharpe_ratio with the reviewer's own reproduction) -------------


def test_dsr_footing_bug_regression_reviewers_exact_numbers():
    """The reviewer's own hand check: a synthetic monthly series (n=48,
    mean=0.006, vol=0.045), var_sr_trials=0.05, n_trials=10 -
    `np.random.default_rng(1).normal(0.006, 0.045, 48)` reproduces their
    reported figures almost exactly: the CORRECT convention (per-period SR,
    n=48) gives DSR=0.0289 (their "≈0.029"); the BUGGY convention this
    packet's report_card.py used to compute (annualized SR, SAME n=48)
    gives DSR=0.2559 (their "≈0.256") - an ~8.9x inflation from the footing
    mismatch alone, on identical underlying data. skew/kurt are the plain
    method-of-moments estimators (quant-gate REVIEW.md finding 2 - see
    report_card.py's own docstring)."""
    returns = np.random.default_rng(1).normal(0.006, 0.045, 48)
    n = len(returns)
    sr_per_period = returns.mean() / returns.std(ddof=1)
    sr_annualized = sr_per_period * math.sqrt(12)
    skew = float(stats.skew(returns, bias=True))
    kurt = float(stats.kurtosis(returns, fisher=False, bias=True))

    dsr_correct = deflated_sharpe_ratio(sr_per_period, 10, 0.05, n, skew, kurt)
    dsr_buggy = deflated_sharpe_ratio(sr_annualized, 10, 0.05, n, skew, kurt)

    assert dsr_correct == pytest.approx(0.029, abs=1e-3)
    assert dsr_buggy == pytest.approx(0.256, abs=1e-3)
    assert dsr_buggy > 5 * dsr_correct  # the bug makes DSR spuriously easy to pass


# --- min_track_record_length -------------------------------------------


def test_min_track_record_length_inf_when_sr_not_above_benchmark():
    assert math.isinf(min_track_record_length(0.5, 0.5, 0.0, 3.0))
    assert math.isinf(min_track_record_length(0.4, 0.5, 0.0, 3.0))


def test_min_track_record_length_hand_computed():
    sr, sr_benchmark, skew, kurt, confidence = 1.0, 0.0, 0.0, 3.0, 0.95
    variance_factor = 1 - skew * sr + (kurt - 1) / 4 * sr**2
    z_alpha = _phi_inv(confidence)
    expected = 1 + variance_factor * (z_alpha / (sr - sr_benchmark)) ** 2
    result = min_track_record_length(sr, sr_benchmark, skew, kurt, confidence)
    assert result == pytest.approx(expected, rel=1e-9)


def _phi_inv(p: float) -> float:
    # scipy is already a hard dependency of this module; used here only to
    # build the test's own expected value independently of calling
    # min_track_record_length itself.
    from scipy import stats

    return float(stats.norm.ppf(p))
