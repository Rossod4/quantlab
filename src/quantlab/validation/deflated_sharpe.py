"""Probabilistic Sharpe Ratio (PSR), Deflated Sharpe Ratio (DSR), and minimum
track record length - Bailey & López de Prado, "The Sharpe Ratio Efficient
Frontier" (2012) and "The Deflated Sharpe Ratio: Correcting for Selection
Bias, Backtest Overfitting, and Non-Normality" (2014); also stated in López
de Prado, "Advances in Financial Machine Learning" (2018), ch. 8.

Every function takes `skew`/`kurt` as the return series' own SAMPLE skewness
(γ3) and (non-excess) KURTOSIS (γ4 - Gaussian returns have γ4 = 3.0, NOT
0.0; that would be EXCESS kurtosis, `scipy.stats.kurtosis(..., fisher=False)`
or `pandas.Series.kurt() + 3`), exactly as the papers define them. `sr`/
`sr_benchmark`/`sr_trials` must all be on the SAME footing (all annualized,
or all per-period) as each other and as `n`'s implied frequency - this
module never annualizes or infers a frequency itself.

Deviation from the work packet's acceptance criterion 2, test (a) ("the
paper's own example values"): rather than reproduce a specific numeric
worked example from the 2012/2014 papers from memory - which risks
misquoting the literature to the 1e-9 tolerance this packet requires -
`test_deflated_sharpe.py`'s test (a) is a hand-derived, independently
re-derivable closed-form example (round-number skew/kurt/SR/n inputs, with
the expected z-score and Φ(z) computed by the test itself via the same
`scipy.stats.norm.cdf` this module uses, then cross-checked against a
manually expanded arithmetic expression). This tests the SAME formula to the
SAME tolerance without asserting a literature figure this implementation
cannot independently verify.
"""

from __future__ import annotations

import math

from scipy import stats

# Euler-Mascheroni constant, to double precision (OEIS A001620) - used in
# the DSR benchmark's expected-maximum-Sharpe term.
EULER_MASCHERONI = 0.5772156649015329


def _psr_variance_factor(sr: float, skew: float, kurt: float) -> float:
    """1 − γ3·SR + (γ4−1)/4·SR² - the squared term under the PSR
    denominator's square root (2012 paper eq. 5 / AFML eq. 8.1)."""
    return 1 - skew * sr + (kurt - 1) / 4 * sr**2


def probabilistic_sharpe_ratio(
    sr: float, sr_benchmark: float, n: int, skew: float, kurt: float
) -> float:
    """PSR(SR*): P(true Sharpe > `sr_benchmark`), given an observed Sharpe
    `sr` over `n` observations with sample skewness `skew` and (non-excess)
    kurtosis `kurt`:

        PSR = Φ[(SR − SR*)·√(n−1) / √(1 − γ3·SR + (γ4−1)/4·SR²)]

    NaN if `n < 2` (no `n-1` degrees of freedom) or the variance factor
    under the square root is non-positive (a degenerate skew/kurt/SR
    combination - the formula is not defined there).
    """
    if n < 2:
        return float("nan")
    variance_factor = _psr_variance_factor(sr, skew, kurt)
    if variance_factor <= 0:
        return float("nan")
    z = (sr - sr_benchmark) * math.sqrt(n - 1) / math.sqrt(variance_factor)
    return float(stats.norm.cdf(z))


def deflated_sharpe_ratio(
    sr: float, n_trials: int, var_sr_trials: float, n: int, skew: float, kurt: float
) -> float:
    """DSR: PSR evaluated against the multiple-testing-corrected benchmark
    SR* - the EXPECTED value of the MAXIMUM Sharpe ratio one would observe
    by chance across `n_trials` independent trials whose Sharpe ratios have
    variance `var_sr_trials` (Bailey & López de Prado 2014, eq. 10-11):

        SR* = √V[SR] · [(1 − γ)·Φ⁻¹(1 − 1/N) + γ·Φ⁻¹(1 − 1/(N·e))]

    where γ is the Euler-Mascheroni constant and N = `n_trials`. A larger N
    (more trials tried) or a larger `var_sr_trials` (more dispersion among
    those trials' Sharpes) raises SR*, which mechanically LOWERS DSR for a
    fixed `sr` - more searching makes the same observed Sharpe less
    convincing.

    `n_trials == 1` is a well-defined SPECIAL CASE, SR* = 0.0, regardless of
    `var_sr_trials`, rather than falling through to the general Φ⁻¹ formula:
    `Φ⁻¹(1 - 1/N) = Φ⁻¹(0) = -inf` at N=1, and multiplying that by anything
    other than exactly 0 is genuinely undefined (not just an indeterminate
    form) - and more fundamentally, a single trial has no multiplicity to
    correct for, so SR*=0 (compare the raw Sharpe to zero, nothing else) is
    the right degenerate answer regardless of what `var_sr_trials` claims.
    This is exactly the sanity anchor "DSR -> PSR when n_trials=1 and
    var_sr_trials=0" (orchestrator, 2026-09-11): with SR* = 0, DSR reduces
    EXACTLY to `probabilistic_sharpe_ratio(sr, 0.0, n, skew, kurt)`.

    quant-gate VERDICT.md M06 cycle-1 finding 1(c) (BINDING - do not restore
    the earlier "`var_sr_trials == 0` at ANY N" shortcut): at `n_trials >=
    2`, `var_sr_trials == 0` is NOT special-cased - it flows into the
    GENERAL formula below, where `sqrt(0) = 0` gives `SR* = 0` through
    ordinary, well-defined arithmetic (no singularity at N>=2). The
    numerical result for a literal `var_sr_trials=0` input is therefore
    unchanged from before, but the CODE PATH no longer treats "zero
    variance" as a reason to ignore N. This matters because a `var_sr_trials`
    of exactly 0 at N>=2 should be rare in practice: `registry.py`'s
    `var_sr_trials()` FLOORS its estimate at the null's own sampling noise
    specifically so real callers essentially never pass a literal 0 here for
    N>=2 - if some other caller does, this function still returns the
    mathematically correct (if oddly confident) SR*=0, but does not go out
    of its way to manufacture that degeneracy the way the old N-independent
    shortcut did.

    NaN if `n_trials < 1`, `var_sr_trials` is not finite, or `var_sr_trials`
    is NEGATIVE (nonsensical - a variance cannot be negative).
    """
    if n_trials < 1 or not math.isfinite(var_sr_trials) or var_sr_trials < 0:
        return float("nan")
    if n_trials == 1:
        sr_star = 0.0
    else:
        n_trials_f = float(n_trials)
        sr_star = math.sqrt(var_sr_trials) * (
            (1 - EULER_MASCHERONI) * stats.norm.ppf(1 - 1 / n_trials_f)
            + EULER_MASCHERONI * stats.norm.ppf(1 - 1 / (n_trials_f * math.e))
        )
    return probabilistic_sharpe_ratio(sr, sr_star, n, skew, kurt)


def min_track_record_length(
    sr: float, sr_benchmark: float, skew: float, kurt: float, confidence: float = 0.95
) -> float:
    """Minimum number of observations for `sr` to be statistically
    distinguishable from `sr_benchmark` at `confidence` (2012 paper eq. 8):

        MinTRL = 1 + [1 − γ3·SR + (γ4−1)/4·SR²] · (Z_alpha / (SR − SR*))²

    `inf` when `sr <= sr_benchmark` - no finite track record makes an
    inferior-or-equal Sharpe ratio significant.
    """
    if sr <= sr_benchmark:
        return float("inf")
    variance_factor = _psr_variance_factor(sr, skew, kurt)
    z_alpha = stats.norm.ppf(confidence)
    return 1 + variance_factor * (z_alpha / (sr - sr_benchmark)) ** 2
