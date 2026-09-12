"""White's Reality Check (White, "A Reality Check for Data Snooping",
Econometrica 2000) and Hansen's Superior Predictive Ability test (Hansen,
"A Test for Superior Predictive Ability", J. Business & Economic Statistics
2005) over a matrix of trial return series - "does the BEST of these trials
beat the benchmark by more than data-snooping alone would predict?"

Both tests share the same shape: observe `d_k,t = trial_k_return_t -
benchmark_return_t` for K trials over T periods, form the statistic
`V = max_k sqrt(T) * mean_t(d_k,t)` (White) or a STUDENTIZED version divided
by each trial's own return volatility (Hansen), then ask how extreme `V` is
against a null distribution built by STATIONARY-BOOTSTRAP resampling
(`bootstrap.py`, Politis & Romano 1994) the SAME `d` matrix and recentering
each bootstrap draw around the null hypothesis "no trial beats the
benchmark" (mean 0). The two tests differ only in the recentering and
studentization:

- White RC recenters EVERY trial's bootstrap mean fully to 0, regardless of
  how well or badly it performed - a deliberately conservative treatment
  that treats every trial as if it had exactly zero true edge.
- Hansen SPA studentizes by each trial's own volatility and recenters only
  trials whose OWN sample statistic is not already strongly negative
  (Hansen 2005 eq. 16-17's "consistent" recentering, threshold
  -sqrt(2 ln ln T)) - keeping a poor performer's own negative mean rather
  than forcing it to 0 makes the max-over-trials null distribution LOWER on
  average, which is exactly why Hansen's SPA is less conservative than
  White's RC and (acceptance criterion 4) SPA's p-value is never larger than
  RC's on the same data.

`benchmark_returns=None` tests against a ZERO benchmark (is the best trial
profitable at all, rather than "does it beat SPY").

Block-length calibration (quant-gate VERDICT.md M06 cycle-1 finding 7, NOT
fixed here - a config/disclosure matter, not a formula bug): on i.i.d.
input at the shipped `bootstrap.block_len: 6.0`, White RC's actual size at
the `max_rc_pvalue: 0.10` bar measures ~0.117 (SPA ~0.118) over 600
simulations, post the `(1 + count) / (B + 1)` p-value fix (quant-gate
VERDICT.2.md M06 cycle-2 item 7) - about 17% more false "significant"
verdicts than nominal. `block_len=1.0` (plain i.i.d. resampling) measures
~0.085-0.092, confirming the statistic's OWN construction is correctly
calibrated and the over-sizing comes entirely from the block length on
i.i.d. input. Real monthly returns are autocorrelated, so `block_len=6.0`
may still be the right choice for this platform's actual data - but the
gate REASON should state the measured over-sizing rather than imply nominal
calibration (quant-gate VERDICT.3.md M06 cycle-3 carried item, closed by
M07's report layer using `MEASURED_SIZE_AT_SHIPPED_BLOCK_LEN` below), and
the in-tree synthetic-null test needs enough simulations to have power to
see it (200 sims, the packet's own number, does not - see
test_reality_check.py).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from quantlab.validation.bootstrap import stationary_bootstrap_indices
from quantlab.validation.registry import TrialRecord, TrialsRegistry

# quant-gate VERDICT.3.md M06 cycle-3 carried item: "put the measured size in
# the RC and SPA gate reasons" (or, as landed, beside the M07 report's RC/SPA
# badges - see reporting/context.py's `_gates_section`) rather than let a
# reader believe the `max_rc_pvalue`/`max_spa_pvalue` bar in
# configs/validation.yaml reflects achieved calibration. A DOCUMENTED
# constant (see the block-length-calibration note in this module's own
# docstring above for the measurement itself: 600 stationary-bootstrap
# simulations of i.i.d. data at `MEASURED_SIZE_BLOCK_LEN`) - never
# recomputed live on a real run, so a caller must not attach it to a result
# measured at a different `block_len`.
MEASURED_SIZE_BLOCK_LEN = 6.0
MEASURED_SIZE_AT_SHIPPED_BLOCK_LEN = {"white_rc": 0.117, "hansen_spa": 0.118}
NOMINAL_SIZE_BAR = 0.10


def _column_label(record: TrialRecord) -> str:
    """The FULL three-part registry key, joined - NOT `record.key[0]`
    (`strategy_id` alone). quant-gate VERDICT.md M06 cycle-1 finding 2:
    labelling columns by `strategy_id` alone collapses every trial that
    shares a `strategy_id` but differs in `data_semantics_version` or
    `backtest_config_hash` into ONE column (a plain dict comprehension keeps
    only the last-seen value for a repeated key), silently under-counting
    exactly the reruns the three-part key exists to distinguish."""
    return "|".join(record.key)


def _common_index(
    series_list: list[pd.Series], benchmark_returns: pd.Series | None
) -> pd.DatetimeIndex | None:
    common: pd.DatetimeIndex | None = None
    for s in series_list:
        common = s.index if common is None else common.intersection(s.index)
    if benchmark_returns is not None and common is not None:
        common = common.intersection(benchmark_returns.index)
    return common


def _resolve_overlap(
    series: dict[str, pd.Series],
    benchmark_returns: pd.Series | None,
    min_overlap_fraction: float,
    headline_label: str | None = None,
) -> tuple[dict[str, pd.Series], list[str], dict[str, float]]:
    """GREEDY iterative true-overlap resolution (quant-gate VERDICT.md M06
    cycle-1 item 9, tightened from an earlier length-ratio heuristic, then
    tightened AGAIN after that first attempt mis-handled its own motivating
    case - see below): while any remaining trial retains less than
    `min_overlap_fraction` of its OWN window in the CURRENT group's common
    date range, find whichever SINGLE trial's removal grows the group's
    common window the most, drop it, and repeat.

    Candidates for removal are EVERY working trial EXCEPT `headline_label`,
    not only the ones currently failing the floor. A trial that is itself
    constraining everyone else's common window typically shows 100%
    self-retention (it IS the common window, or a subset of it) and would
    never be flagged by its OWN fraction - a first version of this function
    only ever removed already-failing trials and, on "3 long aligned trials
    + 1 short outlier", ended up deleting the three long trials one at a
    time (since removing any one of them, with the outlier still present,
    never helped) before failing outright with the short outlier as the
    sole survivor. Considering every trial as a candidate and picking
    whichever removal most GROWS the resulting common window fixes this:
    removing the short outlier restores the long trials' full mutual
    overlap, so it is chosen immediately. This is also what correctly
    handles "two same-length, merely offset windows plus an aligned
    majority" (removing the offset trial grows the majority's common
    window; removing a majority member does not).

    quant-gate VERDICT.2.md M06 cycle-2 finding A: the algorithm above is
    blind to WHICH trial is being validated - if the headline's own window
    is offset from the majority of its family's other recorded trials, it
    is exactly the trial the greedy search picks to drop, since removing it
    grows everyone else's common window the most. The Reality Check would
    then silently run on (and pass or fail on behalf of) the headline's
    SIBLINGS while never examining the headline itself. `headline_label` is
    therefore excluded from the removal-candidate set entirely: a headline
    below the floor can still be RESCUED by removing some other, genuinely
    offending trial (the ordinary greedy search keeps running on the
    non-headline candidates for exactly this reason), but the headline
    itself is never the trial removed to make room for it. If no removal of
    any OTHER trial helps and the headline is still below the floor, the
    final "drop everyone still below the floor" pass gives the headline its
    own NAMED reason ("headline trial excluded by overlap floor
    (retained_fraction=...)") instead of the generic one, for
    `build_trial_matrix` to raise on.

    If no single removal would grow the common window at all (a genuine
    tie/deadlock - rare), every trial still below the floor is excluded in
    one final pass and iteration stops - best effort, not a fixed point.

    Returns `(survivors, excluded_reasons, retained_fractions)`.
    `retained_fractions` covers EVERY trial ever considered (both survivors
    and excluded), each trial's fraction measured against the group common
    range AT THE MOMENT it was resolved - this is what lets a caller
    (report_card.py) report a HEADLINE trial's own retained fraction in
    provenance regardless of whether it survived.
    """
    if min_overlap_fraction <= 0.0 or not series:
        return series, [], {}

    working = dict(series)
    excluded: list[str] = []
    retained_fractions: dict[str, float] = {}

    while working:
        common = _common_index(list(working.values()), benchmark_returns)
        current_len = len(common) if common is not None else 0
        if current_len == 0:
            for label in working:
                retained_fractions.setdefault(label, 0.0)
            break
        fractions = {
            label: len(common.intersection(s.index)) / len(s.index) for label, s in working.items()
        }
        below = {label for label, f in fractions.items() if f < min_overlap_fraction}
        if not below:
            retained_fractions.update(fractions)
            break

        # Whichever SINGLE removal (from the working set, EXCLUDING the
        # headline) most grows the resulting common window - see docstring
        # for why candidates are not restricted to the currently-failing
        # trials, and why the headline is never a candidate. This still
        # gives a headline that is currently below the floor a chance to be
        # RESCUED by removing some other, genuinely offending trial (e.g. a
        # short outlier dragging everyone's common window down) before we
        # conclude the headline itself cannot be saved.
        candidates = [label for label in working if label != headline_label]
        best_label, best_new_len = None, current_len
        for label in candidates:
            rest = [s for other, s in working.items() if other != label]
            rest_common = _common_index(rest, benchmark_returns)
            new_len = len(rest_common) if rest_common is not None else 0
            if new_len > best_new_len:
                best_new_len, best_label = new_len, label

        if best_label is None:
            # No single non-headline removal helps further - drop everyone
            # still below the floor at this point (best effort) and stop.
            # If the headline itself is among them, it gets the NAMED cause
            # ("headline trial excluded by overlap floor...") instead of the
            # generic message, so `build_trial_matrix` can raise on it by
            # name rather than silently building a matrix of its siblings.
            for label in below:
                if label == headline_label:
                    excluded.append(
                        "headline trial excluded by overlap floor (retained_fraction="
                        f"{fractions[label]:.0%})"
                    )
                else:
                    excluded.append(
                        f"{label} excluded from the Reality Check/SPA matrix: retains only "
                        f"{fractions[label]:.0%} of its own {len(working[label].index)}-period "
                        f"window in the common date range (floor {min_overlap_fraction:.0%})"
                    )
                retained_fractions[label] = fractions[label]
                del working[label]
            for label in working:
                retained_fractions.setdefault(label, fractions[label])
            break

        fraction = fractions[best_label]
        span = len(working[best_label].index)
        excluded.append(
            f"{best_label} excluded from the Reality Check/SPA matrix: retains only "
            f"{fraction:.0%} of its own {span}-period window in the common date range "
            f"(floor {min_overlap_fraction:.0%})"
        )
        retained_fractions[best_label] = fraction
        del working[best_label]

    return working, excluded, retained_fractions


class TrialMatrixError(ValueError):
    """Raised by `build_trial_matrix` when no RC/SPA matrix can be built.

    Subclasses `ValueError` so pre-existing `except ValueError:` call sites
    keep working unchanged, but carries the exclusion bookkeeping
    (`excluded`, `retained_fractions`) that would otherwise be lost the
    moment the exception is raised - quant-gate VERDICT.2.md M06 cycle-2
    finding A's second bug: a bare `raise ValueError(...)` here meant the
    `matrix, excluded, retained_fractions = build_trial_matrix(...)`
    tuple-unpack in `report_card.py` never executed, so a caller that
    caught the exception had no way to report WHY, or what had been
    excluded, even when trials were in fact present and excluded for an
    informative reason.

    `reason_kind` is one of three mutually distinguishable causes (quant-
    gate VERDICT.2.md M06 cycle-2 finding A item 2), for `report_card.py`'s
    RC-is-None gate reason to report accurately instead of a single generic
    message regardless of cause:
    - "too_few_trials_recorded": the registry itself never held >= 2 trials
      with a stored return series for this family - no exclusion occurred.
    - "excluded_by_overlap_floor": the overlap floor excluded trials (the
      headline itself, per finding A item 1, or others) down to < 2
      survivors or to an empty common window.
    - "no_common_dates": trials were present (and none excluded by the
      floor) but their date ranges - or the benchmark's - simply do not
      overlap.
    """

    def __init__(
        self,
        message: str,
        *,
        reason_kind: str,
        excluded: list[str],
        retained_fractions: dict[str, float],
    ) -> None:
        super().__init__(message)
        self.reason_kind = reason_kind
        self.excluded = excluded
        self.retained_fractions = retained_fractions


def build_trial_matrix(
    registry: TrialsRegistry,
    family: str,
    benchmark_returns: pd.Series | None = None,
    *,
    min_overlap_fraction: float = 0.0,
    headline_label: str | None = None,
) -> tuple[pd.DataFrame, list[str], dict[str, float]]:
    """A `T x K` matrix of every recorded trial in `family` that has a
    stored return series (`with_series_only=True` - see registry.py's
    module docstring on why sensitivity/historical trials typically lack
    one), aligned on their COMMON dates (and the benchmark's, if given).
    Columns are labelled by the trial's FULL registry key (`_column_label`).

    Returns `(matrix, excluded_reasons, retained_fractions)` - see
    `_resolve_overlap`'s docstring (quant-gate VERDICT.md M06 cycle-1 item
    9) for the exclusion algorithm and what `retained_fractions` covers.
    `min_overlap_fraction=0.0` (the default) disables the floor entirely -
    every trial is kept, the pre-existing behaviour.

    `headline_label` (quant-gate VERDICT.2.md M06 cycle-2 finding A item 1):
    when given and the trial with that label was recorded with a series,
    it is PINNED - never a removal candidate in `_resolve_overlap` - and if
    it still cannot clear `min_overlap_fraction` without being removed
    itself, this raises `TrialMatrixError` naming that exact cause rather
    than silently returning a matrix built from its siblings alone. A
    caller MUST NOT treat a returned matrix as validating the headline
    unless it asserts `headline_label in matrix.columns` itself (see
    `report_card.py`) - this function guarantees it by raising otherwise,
    but the assertion at the call site is the honest, defence-in-depth
    invariant check.

    Raises `TrialMatrixError` (a `ValueError` subclass - see its docstring
    for `reason_kind`) if, AFTER any exclusion, fewer than 2 trials remain
    with a stored series (a Reality Check needs at least 2 trials to have a
    "best of several" to test), the common-date intersection is empty, or
    the headline trial could not be retained above the floor.
    quant-gate VERDICT.md M06 cycle-1 finding 2: the trial-count check runs
    on the ACTUAL matrix column count, not on the pre-collapse record list.
    """
    records: list[TrialRecord] = registry.trials(family, with_series_only=True)
    series = {_column_label(r): registry.load_series(r) for r in records}
    headline_had_series = headline_label is not None and headline_label in series

    series, excluded, retained_fractions = _resolve_overlap(
        series, benchmark_returns, min_overlap_fraction, headline_label=headline_label
    )

    if headline_had_series and headline_label not in series:
        headline_fraction = retained_fractions.get(headline_label, 0.0)
        raise TrialMatrixError(
            "headline trial excluded by overlap floor "
            f"(retained_fraction={headline_fraction:.0%}): the headline trial "
            f"{headline_label!r} in family {family!r} could not be retained above the "
            f"{min_overlap_fraction:.0%} overlap floor without removing itself - "
            "the Reality Check/SPA refuse to run on its sibling trials alone.",
            reason_kind="excluded_by_overlap_floor",
            excluded=excluded,
            retained_fractions=retained_fractions,
        )

    common = _common_index(list(series.values()), benchmark_returns)
    if not series or common is None or len(common) == 0:
        reason_kind = "excluded_by_overlap_floor" if excluded else "no_common_dates"
        detail = (
            f" after excluding {len(excluded)} trial(s) below the overlap floor" if excluded else ""
        )
        raise TrialMatrixError(
            f"no common dates across trials in family {family!r}{detail}",
            reason_kind=reason_kind,
            excluded=excluded,
            retained_fractions=retained_fractions,
        )

    matrix = pd.DataFrame({label: s.loc[common] for label, s in series.items()})
    if benchmark_returns is not None:
        matrix = matrix.sub(benchmark_returns.loc[common], axis=0)

    if matrix.shape[1] < 2:
        reason_kind = "excluded_by_overlap_floor" if excluded else "too_few_trials_recorded"
        raise TrialMatrixError(
            f"need at least 2 trials with a stored return series in family {family!r} to run "
            f"a Reality Check / SPA; found {matrix.shape[1]} after alignment/exclusion "
            f"(registry held {len(records)} records with a series)",
            reason_kind=reason_kind,
            excluded=excluded,
            retained_fractions=retained_fractions,
        )
    return matrix, excluded, retained_fractions


@dataclass(frozen=True)
class RealityCheckResult:
    test_name: str  # "white_rc" | "hansen_spa"
    statistic: float
    p_value: float
    best_trial: str
    n_trials: int
    n_periods: int
    b: int
    block_len: float

    def to_json(self) -> dict[str, Any]:
        return {
            "test_name": self.test_name,
            "statistic": self.statistic,
            "p_value": self.p_value,
            "best_trial": self.best_trial,
            "n_trials": self.n_trials,
            "n_periods": self.n_periods,
            "b": self.b,
            "block_len": self.block_len,
        }


def white_reality_check(
    excess_returns: pd.DataFrame, b: int, block_len: float, seed: int
) -> RealityCheckResult:
    """`excess_returns`: a `T x K` DataFrame, trial return minus benchmark
    (already differenced - see `build_trial_matrix`). Tests
    H0: no trial's true mean excess return is positive."""
    values = excess_returns.to_numpy()
    labels = list(excess_returns.columns)
    t_periods, _k = values.shape
    means = values.mean(axis=0)
    observed_stat = float(math.sqrt(t_periods) * means.max())
    best_idx = int(np.argmax(means))

    rng = np.random.default_rng(seed)
    boot_stats = np.empty(b)
    for i in range(b):
        idx = stationary_bootstrap_indices(t_periods, block_len, rng)
        resampled_means = values[idx].mean(axis=0)
        # Recenter fully to 0 (White's own null: every trial has zero true
        # mean) by subtracting each trial's OWN sample mean.
        boot_stats[i] = math.sqrt(t_periods) * (resampled_means - means).max()

    # (1 + count) / (B + 1), not count/B: a bootstrap p-value of exactly
    # 0.0 is not attainable under a continuous null and biases p downward
    # by about 1/(B+1) (quant-gate VERDICT.md M06 cycle-1 finding 7).
    p_value = float((1 + np.sum(boot_stats >= observed_stat)) / (b + 1))
    return RealityCheckResult(
        test_name="white_rc",
        statistic=observed_stat,
        p_value=p_value,
        best_trial=labels[best_idx],
        n_trials=values.shape[1],
        n_periods=t_periods,
        b=b,
        block_len=block_len,
    )


def hansen_spa(
    excess_returns: pd.DataFrame, b: int, block_len: float, seed: int
) -> RealityCheckResult:
    """Hansen's studentized SPA test with the "consistent" recentering
    (2005 eq. 16-17) - see module docstring for why this is less
    conservative than `white_reality_check` on the same data."""
    values = excess_returns.to_numpy()
    labels = list(excess_returns.columns)
    t_periods, _k = values.shape
    means = values.mean(axis=0)
    stds = values.std(axis=0, ddof=1)
    stds_safe = np.where(stds == 0, np.nan, stds)
    t_stats = math.sqrt(t_periods) * means / stds_safe
    observed_stat = float(np.nanmax(t_stats))
    best_idx = int(np.nanargmax(t_stats))

    # Consistent recentering threshold -sqrt(2 ln ln T); undefined (treated
    # as -inf, i.e. recenter nothing) for T so small that ln(ln(T)) isn't
    # real (T <= e).
    threshold = (
        -math.sqrt(2 * math.log(math.log(t_periods))) if t_periods > math.e else float("-inf")
    )
    recenter = np.where(t_stats >= threshold, means, 0.0)

    rng = np.random.default_rng(seed)
    boot_stats = np.empty(b)
    for i in range(b):
        idx = stationary_bootstrap_indices(t_periods, block_len, rng)
        resampled_means = values[idx].mean(axis=0)
        boot_t = math.sqrt(t_periods) * (resampled_means - recenter) / stds_safe
        boot_stats[i] = np.nanmax(boot_t)

    # (1 + count) / (B + 1), not count/B: a bootstrap p-value of exactly
    # 0.0 is not attainable under a continuous null and biases p downward
    # by about 1/(B+1) (quant-gate VERDICT.md M06 cycle-1 finding 7).
    p_value = float((1 + np.sum(boot_stats >= observed_stat)) / (b + 1))
    return RealityCheckResult(
        test_name="hansen_spa",
        statistic=observed_stat,
        p_value=p_value,
        best_trial=labels[best_idx],
        n_trials=values.shape[1],
        n_periods=t_periods,
        b=b,
        block_len=block_len,
    )
