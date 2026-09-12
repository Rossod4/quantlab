"""`ReportCard`: the platform's decision function - composes M05's
`ValidationBasic` with M06's multiple-testing-aware statistics (PSR/DSR,
purged/embargoed CV, White Reality Check / Hansen SPA, block-bootstrap Monte
Carlo, capacity) into one verdict: REJECTED | RESEARCH_ONLY |
ELIGIBLE_FOR_PAPER. Every threshold below is read from
`ValidationConfig.thresholds` (configs/validation.yaml) - never hardcoded,
per the work packet's "Interfaces to honor".

Verdict logic (from the work packet, verbatim):
  - REJECTED if any HARD gate fails: DSR < `min_dsr`, White RC p-value >
    `max_rc_pvalue`, net Sharpe < benchmark Sharpe (including "no usable
    benchmark", per the M05 carried item below), coverage_bound >
    `max_coverage_bound_pct`, or min track record length > available n.
  - ELIGIBLE_FOR_PAPER if every hard gate AND every soft gate passes: PSR >=
    `min_psr`, subperiod OOF Sharpe > `min_subperiod_oof_sharpe` (renamed
    from `min_purged_cv_mean_oof_sharpe` - quant-gate VERDICT.md M06 cycle-1
    finding 4, see below), no_cliff_score >= `min_no_cliff_score` (ALWAYS
    paired with `min_net_sharpe` - see the M05 carried item below, binding), MC
    P(drawdown worse than observed) <= `mc_max_prob_drawdown_worse_than_
    observed`, capacity ceiling >= `capacity_min_multiple_of_intended_
    capital` x intended capital, Hansen SPA p-value <= `max_spa_pvalue`,
    and (if a walk-forward result was supplied) chosen-weight stability >=
    `min_walk_forward_stability_fraction`. Two additional SOFT gates,
    orchestrator-added (2026-09-11, see below) rather than in the packet's
    own bulleted list: `max_drawdown_floor` (on the FULL-SAMPLE net max
    drawdown only) and `max_negative_rolling_window_fraction`.
  - RESEARCH_ONLY otherwise.
A soft gate this report card could not compute at all (no walk-forward
supplied is the one exception - "if present" per the packet - which is
vacuously satisfied) is treated as a FAILURE, not a silent pass, and says so
in its own reason string.

Carried, binding items addressed here:
  - M04 verdict item 2: PSR/DSR's `skew`/`kurt` inputs come from the same
    `net_returns` the extreme-return guard may have truncated; a nonzero
    `extreme_returns_long`/`extreme_returns_short` count is appended to the
    PSR/DSR gates' own reason strings, stating the direction (see
    `_extreme_return_caveat`).
  - M05 carried item 2: `no_cliff_score` is never quoted alone - `soft` gate
    `min_net_sharpe` is evaluated ALONGSIDE `no_cliff_score` and both must
    pass for ELIGIBLE_FOR_PAPER (this is why `min_net_sharpe`, though absent
    from the packet's own bulleted soft-gate list above, is still a REAL
    gate here rather than merely informational).
  - M05 carried item 3: purged CV needs an embargo (a contiguous test fold
    can sit mid-series with training rows on both sides, so a training
    row's own label window can overlap it from either direction) while
    `walk_forward_blend` needs none (its weight choice is made from a
    strictly PRIOR block and applied only to a strictly SUBSEQUENT one) -
    stated in `_PURGE_VS_WALK_FORWARD_NOTE`, always present in
    `known_caveats`.
  - M05 carried item 4: a walk-forward's weight RANKING has not been
    checked against the real netted-cost blend backtest's own ranking -
    `_WALK_FORWARD_RANKING_NOTE`, added to `known_caveats` whenever a
    walk-forward result is supplied.
  - M05 carried item 5: whether any CHOSEN walk-forward step had a NaN
    training Sharpe cannot be checked from a `WalkForwardResult` alone
    (per-step training Sharpes are not retained on the object, and
    `walk_forward.py` is a read-only interface for this packet) -
    `_WALK_FORWARD_NAN_TIEBREAK_NOTE`, added under the same condition, left
    as an OPEN ITEM rather than silently assumed clean.
  - M04 verdict item 4 / M05 item 3: the coverage-bound/unscored/dropped
    "SEPARATE selection effects" sentence is already produced by
    `validate_basic` (`basic.flags[0]`) - this module does not reproduce it.
  - registry.py's own base-point double-counting note is repeated in
    `known_caveats` here (`_REGISTRY_BASE_POINT_NOTE`) so a reader of the
    report card sees it without also reading registry.py.

Orchestrator decision (2026-09-11, superseding iteration 1's "deliberately
not wired" note): `max_drawdown_floor` and `max_negative_rolling_window_
fraction` (both pre-seeded in configs/validation.yaml by M05) are wired in
as SOFT gates only - a failure caps the verdict at RESEARCH_ONLY, never
REJECTED. `max_drawdown_floor` reads `MetricsSummary.net_max_drawdown` (the
FULL-SAMPLE figure) - never a rolling column, per the M05 carried item on
`rolling_window_metrics`'s first-return blindness.
`max_negative_rolling_window_fraction` takes the WORST fraction across every
configured rolling window length (`_max_negative_rolling_fraction`,
conservative like `CoverageReport.overall_bound`'s "worst year"), and its
gate reason states the rolling table's frozen ported convention explicitly
(see `rolling.py`'s module docstring) so a reader isn't misled about what
"negative CAGR" means there.

Quant-gate REVIEW.md, M06 cycle-1 (2026-09-11):
  - Finding 1 [blocker]: PSR/DSR/`min_track_record_length` were being fed
    `MetricsSummary.net_sharpe` (ANNUALIZED) alongside `n = len(net_returns)`
    (a raw PERIOD count) and skew/kurt computed on the raw per-period
    series - a footing mismatch (reviewer's hand check: ~9x DSR error on a
    realistic n=48/var_sr_trials=0.05/N=10 example). Fixed: a PER-PERIOD
    `sr_per_period` (`metrics.raw_sharpe` - mean/std(ddof=1), no
    annualization) is now what actually goes into all three formulas;
    `m.net_sharpe` is kept only for the gate reasons' side-by-side display.
    This cascaded into `registry.py`: `var_sr_trials()` (SR*'s dispersion
    input) now reads `TrialRecord.net_sharpe_per_period`, not the
    annualized `net_sharpe` - see that module's own docstring.
  - Finding 2 [minor]: skew/kurt now use the plain method-of-moments
    estimators (`scipy.stats.skew(bias=True)` / `kurtosis(fisher=False,
    bias=True)`), not pandas' bias-corrected G1/G2 - matching the DSR
    literature's own convention and `test_report_card.py`'s fixture
    reasoning (an exactly-alternating equal-count series has skew=0 and
    non-excess kurtosis=1 EXACTLY under method-of-moments, at any N - not
    merely approximately, as pandas' finite-sample correction gave).

Quant-gate VERDICT.md, M06 cycle-1 (REJECT - the maths was right, the
plumbing to the verdict was not; fixed here):
  - Finding 1 [blocker]: recording MORE trials could RAISE DSR - see
    registry.py's own docstring for the full mechanism (trial dedup by
    return-series hash, a variance floor, and the `n_trials==1`-only SR*=0
    special case in deflated_sharpe.py). This module now reads
    `registry.n_trials(fam)` (deduplicated) for the DSR gate and additionally
    surfaces `registry.n_trials_raw(fam)` (pre-dedup) in the provenance
    section so both numbers are inspectable. `_REGISTRY_BASE_POINT_NOTE`'s
    false "conservative" claim is corrected above.
  - Finding 2 [blocker]: `build_trial_matrix` now labels RC/SPA matrix
    columns by the FULL three-part registry key, not `strategy_id` alone,
    and its "too few trials" guard now checks the actual matrix column
    count - see reality_check.py's own docstring. The realised trial count
    K (`rc.n_trials`/`spa.n_trials`) is now printed in both gates' reasons
    and in the provenance section.
  - Finding 3 [blocker]: RC/SPA's benchmark is now a STATED CHOICE
    (`ValidationConfig.reality_check.benchmark`, default `"embedded"` -
    `result.benchmark_returns` unless a separate `benchmark_result` is
    supplied, exactly what `metrics.summary()`/`net_sharpe_vs_benchmark`/
    `min_track_record_length` already use), not an accident of whether the
    CLI happened to receive `--benchmark`. The resolved source is printed in
    both RC and SPA gate reasons and in the provenance section.
  - Finding 4 [blocker]: the gate formerly named `purged_cv_mean_oof_sharpe`
    is renamed `subperiod_oof_sharpe` - see purged_cv.py's own (renamed)
    module docstring for why: it is a contiguous-sub-period consistency
    check on a FIXED-PARAMETER strategy, not a purged cross-validation
    (nothing is refit per fold, so purge/embargo cannot change its value).
    The gate's reason string says so plainly, and `known_caveats` repeats it
    whenever the gate is present.
  - Finding 5 [blocker]: `cli.py`'s `validate --full` now seeds the
    historical blend trials, runs the sensitivity grid through the REAL
    engine, and wires `walk_forward`/`sensitivity` through to this function
    - see cli.py's own module docstring. `ELIGIBLE_FOR_PAPER` is reachable
    through the shipped CLI on a fixture built to earn it.
  - Finding 6 [blocker]: `ReportCard.provenance` (`ReportCardProvenance`,
    below) carries `strategy_id`, `data_semantics_version`,
    `quantlab_git_sha`, `dirty`/`dirty_source`, `n_trials`/`n_trials_raw`,
    the realised RC trial count K, the resolved RC/SPA benchmark source, the
    coverage/selection "untrusted fraction" line, and the Sharpe/Sortino
    convention statement - closing the carried M04 item that the dirty-tree
    flag must reach the report card's provenance section, which it
    previously did not.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import Any, Literal

import pandas as pd
from scipy import stats

from quantlab.backtest.result import BacktestResult, QualityFlags
from quantlab.validation.basic import ValidationBasic, ValidationConfig, validate_basic
from quantlab.validation.capacity import CapacityResult, capacity_estimate
from quantlab.validation.deflated_sharpe import (
    deflated_sharpe_ratio,
    min_track_record_length,
    probabilistic_sharpe_ratio,
)
from quantlab.validation.metrics import raw_sharpe
from quantlab.validation.monte_carlo import MonteCarloResult, monte_carlo_summary
from quantlab.validation.purged_cv import (
    SubperiodOOFResult,
    purged_kfold_splits,
    subperiod_oof_sharpe,
)
from quantlab.validation.reality_check import (
    RealityCheckResult,
    build_trial_matrix,
    hansen_spa,
    white_reality_check,
)
from quantlab.validation.registry import TrialsRegistry
from quantlab.validation.sensitivity import SensitivityResult
from quantlab.validation.walk_forward import WalkForwardResult

Verdict = Literal["REJECTED", "RESEARCH_ONLY", "ELIGIBLE_FOR_PAPER"]

_PURGE_VS_WALK_FORWARD_NOTE = (
    "Purged/embargoed CV needs both a purge and an embargo because a contiguous test fold "
    "can sit in the MIDDLE of the series with training data on both sides, so a training "
    "row's own label window can overlap the test fold from either direction; the "
    "walk-forward check (validation/walk_forward.py) needs neither, because its weight "
    "choice is made from a STRICTLY PRIOR training block and applied only to the STRICTLY "
    "SUBSEQUENT, not-yet-realized test block - there is no way for the test block's own "
    "returns to leak backward into that choice."
)
_WALK_FORWARD_RANKING_NOTE = (
    "This walk-forward's Sharpe RANKING across weight choices has NOT been checked against "
    "the real, netted-cost blend backtest's own ranking (walk_forward.py blends each child's "
    "NET RETURNS; strategies/blend.py blends TARGET WEIGHTS and nets costs on the "
    "already-blended book - the two disagree whenever turnover/borrow are nonlinear in "
    "weights). Read this result as 'is the weight choice stable', not as a stand-in for the "
    "netted book's own net_returns."
)
_WALK_FORWARD_NAN_TIEBREAK_NOTE = (
    "Whether any CHOSEN walk-forward step had a NaN training Sharpe (which would lock in the "
    "first grid weight regardless of the others - see walk_forward.py's module docstring) "
    "cannot be checked from a WalkForwardResult alone: per-step training Sharpes are not "
    "retained on the object. Left as an open item for whoever runs the walk-forward "
    "experiment to verify independently."
)
_REGISTRY_BASE_POINT_NOTE = (
    "n_trials for this family may double-count the strategy's own headline run against a "
    "sensitivity grid's base point at the same parameters - the two use independent id "
    "schemes and the registry does not reconcile them (registry.py's module docstring). This "
    "over-counts N by one trial; unlike an earlier version of this note claimed, over-counting "
    "N is NOT generally conservative for DSR once var_sr_trials is estimated from the same "
    "trial set (quant-gate VERDICT.md M06 cycle-1 finding 1) - it is disclosed here because it "
    "is a small, one-trial effect, not because its direction is guaranteed safe."
)
_SUBPERIOD_OOF_CAVEAT = (
    "subperiod_oof_sharpe (mean Sharpe over contiguous sub-periods) is a consistency check on "
    "a FIXED-PARAMETER strategy, not a purged cross-validation: no model is refit per fold, so "
    "purge/embargo cannot change its value (quant-gate VERDICT.md M06 cycle-1 finding 4) - "
    "purged_kfold_splits itself remains correct and is kept for a future fitted strategy."
)
_DIRTY_TRIAL_CAVEAT = (
    "at least one trial counted toward this family's N (or its dispersion estimate) was "
    "recorded from a dirty (uncommitted-changes) working tree - see the provenance section's "
    "dirty trial count."
)

# quant-gate VERDICT.2.md M06 cycle-2 finding B (non-blocking, carried): the
# series_hash dedup + variance floor (registry.py) fully flatten DSR against
# BYTE-IDENTICAL reruns, but a narrower residual survives - near-duplicate
# (not byte-identical) reruns of one grid point, e.g. successive 1bp cost
# bumps on the headline, each hash as a NEW distinct trial and can still
# move DSR across a threshold before the variance floor binds. Disclosed
# beside the DSR badge rather than "fixed" further, since the underlying
# mechanism (more genuinely distinct trials changing N and var_sr_trials)
# is doing exactly what it is supposed to do - it is DSR's own N-dependence
# that is not monotone, not a registry bug.
_DSR_MONOTONICITY_NOTE = (
    "DSR is not monotone in N above the variance floor; near-duplicate reruns of one grid "
    "point can move it."
)


def _extreme_return_caveat(qf: QualityFlags) -> str | None:
    if not (qf.extreme_returns_long or qf.extreme_returns_short):
        return None
    parts = []
    if qf.extreme_returns_long:
        parts.append(
            f"{qf.extreme_returns_long} long-book exclusion(s) (CONSERVATIVE: truncates a "
            "genuine right tail, understating skew/kurtosis in this direction)"
        )
    if qf.extreme_returns_short:
        parts.append(
            f"{qf.extreme_returns_short} short-book exclusion(s) (ANTI-CONSERVATIVE: hides an "
            "adverse move, flattering skew/kurtosis)"
        )
    return "the extreme-return guard affected this same net_returns series: " + "; ".join(parts)


def _max_negative_rolling_fraction(rolling: dict[int, pd.DataFrame]) -> float:
    """The WORST (highest) fraction of negative-CAGR rolling windows across
    every configured window length in `basic.rolling` - conservative in the
    same spirit as `CoverageReport.overall_bound` ("worst year", not an
    average). NaN if `rolling` is empty (e.g. every configured window was
    longer than the result's own history - `validate_basic` skips those with
    a flag rather than raising)."""
    if not rolling:
        return float("nan")
    fractions = [(table["CAGR"] < 0).mean() for table in rolling.values() if not table.empty]
    if not fractions:
        return float("nan")
    return float(max(fractions))


def _walk_forward_stability_fraction(wf: WalkForwardResult) -> float:
    """Fraction of walk-forward steps whose chosen weight tuple equals the
    MODAL chosen tuple - 1.0 means the walk-forward always picked the same
    weights, low values mean the "best" weight kept changing (the
    instability REVIEW_PHASE5.md's own walk-forward found: "50%, 50%, 25%,
    75%, 50%, 100%, 75%, 75%, 0%, 25%" - a fixed weight, not this metric,
    but the same instability concept)."""
    rows = [tuple(row) for row in wf.chosen_weights.itertuples(index=False)]
    if not rows:
        return float("nan")
    counts = Counter(rows)
    mode_count = counts.most_common(1)[0][1]
    return mode_count / len(rows)


@dataclass(frozen=True)
class GateResult:
    name: str
    kind: str  # "hard" | "soft"
    value: float
    threshold: float
    passed: bool
    reason: str

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "value": self.value,
            "threshold": self.threshold,
            "passed": self.passed,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ReportCardProvenance:
    """quant-gate VERDICT.md M06 cycle-1 finding 6 - closes the carried M04
    item that a dirty-tree trial must be flagged all the way to the report
    card's provenance section, which it previously was not."""

    strategy_id: str
    data_semantics_version: str
    quantlab_git_sha: str
    dirty: bool
    dirty_source: str
    n_trials: int
    n_trials_raw: int
    dirty_trial_count: int
    rc_trial_count: int | None
    rc_spa_benchmark_source: str
    # quant-gate VERDICT.md M06 cycle-1 item 9: the HEADLINE trial's own
    # fraction of its window retained in the RC/SPA common-date range -
    # None when RC/SPA didn't run at all (fewer than 2 trials) or the
    # overlap floor is disabled (min_overlap_fraction<=0.0, so nothing was
    # measured).
    headline_retained_fraction: float | None
    untrusted_fraction_line: str
    sharpe_sortino_convention: str

    def to_json(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "data_semantics_version": self.data_semantics_version,
            "quantlab_git_sha": self.quantlab_git_sha,
            "dirty": self.dirty,
            "dirty_source": self.dirty_source,
            "n_trials": self.n_trials,
            "n_trials_raw": self.n_trials_raw,
            "dirty_trial_count": self.dirty_trial_count,
            "rc_trial_count": self.rc_trial_count,
            "rc_spa_benchmark_source": self.rc_spa_benchmark_source,
            "headline_retained_fraction": self.headline_retained_fraction,
            "untrusted_fraction_line": self.untrusted_fraction_line,
            "sharpe_sortino_convention": self.sharpe_sortino_convention,
        }


_SHARPE_SORTINO_CONVENTION = (
    "Sharpe: pandas ddof=1 (sample std), annualized by sqrt(periods_per_year). Sortino: "
    "target return 0, FULL-SAMPLE N at ddof=0 (not losing-periods-only N). The two "
    "denominators are on DIFFERENT footings (M05 carried item 8) - do not compare them via "
    "their raw values alone."
)


@dataclass(frozen=True)
class ReportCard:
    basic: ValidationBasic
    psr: float
    dsr: float
    min_trl: float
    n_trials: int
    cv: SubperiodOOFResult
    rc: RealityCheckResult | None
    spa: RealityCheckResult | None
    monte_carlo: MonteCarloResult
    capacity: CapacityResult | None
    coverage_bound: float
    quality_flags_summary: dict[str, Any]
    known_caveats: list[str]
    gates: list[GateResult]
    verdict: Verdict
    provenance: ReportCardProvenance

    def to_json(self) -> dict[str, Any]:
        return {
            "basic": self.basic.to_json(),
            "psr": self.psr,
            "dsr": self.dsr,
            "min_trl": self.min_trl,
            "n_trials": self.n_trials,
            "cv": self.cv.to_json(),
            "rc": self.rc.to_json() if self.rc is not None else None,
            "spa": self.spa.to_json() if self.spa is not None else None,
            "monte_carlo": self.monte_carlo.to_json(),
            "capacity": self.capacity.to_json() if self.capacity is not None else None,
            "coverage_bound": self.coverage_bound,
            "quality_flags_summary": self.quality_flags_summary,
            "known_caveats": list(self.known_caveats),
            "gates": [g.to_json() for g in self.gates],
            "verdict": self.verdict,
            "provenance": self.provenance.to_json(),
        }


def build_report_card(
    result: BacktestResult,
    benchmark_result: BacktestResult | None,
    registry: TrialsRegistry,
    config: ValidationConfig,
    *,
    walk_forward: WalkForwardResult | None = None,
    sensitivity: SensitivityResult | None = None,
    price_panel: dict[str, pd.DataFrame] | None = None,
    price_panel_missing_tickers: list[str] | None = None,
    family: str | None = None,
) -> ReportCard:
    """Build the full report card for `result`. Registers `result` itself
    into `registry` (idempotent by key - see registry.py) so the current
    run is always counted in its own family's N, even if the caller never
    called `record_backtest` separately.

    `price_panel`, if supplied, is forwarded to `capacity_estimate` (which
    needs OHLCV data no `BacktestResult` carries); omitted, the capacity
    soft gate is treated as a failure (see module docstring).
    `price_panel_missing_tickers` (new - `cli.py`'s `validate --full` builds
    `price_panel` from the platform's own cache-backed price provider over
    every ticker the strategy ever held) names any of THOSE held tickers the
    provider could not supply data for, so the capacity gate's reason can
    say which ones rather than a generic "no panel" message.
    """
    basic = validate_basic(
        result, benchmark_result, config, walk_forward=walk_forward, sensitivity=sensitivity
    )
    m = basic.metrics
    net_returns = result.net_returns
    n = len(net_returns)

    # PER-PERIOD Sharpe/skew/kurt (quant-gate REVIEW.md, M06 cycle-1
    # blocker 1): `deflated_sharpe.py`'s formulas are derived for a Sharpe
    # estimated from `n` iid PER-PERIOD draws, on the SAME footing as `n`
    # itself and as `skew`/`kurt` computed on the raw per-period series.
    # `m.net_sharpe` is ANNUALIZED (`sharpe_ratio(..., periods_per_year=)`)
    # - passing that alongside a raw period count silently breaks the
    # footing (measured at the gate: ~9x DSR error on a realistic example).
    # `sr_per_period` (metrics.raw_sharpe) is what actually goes into PSR/
    # DSR/MinTRL; `m.net_sharpe` is kept only for gate labels/reasons.
    sr_per_period = raw_sharpe(net_returns)
    # skew/kurt: plain method-of-moments estimators (scipy `bias=True`),
    # NOT pandas' bias-corrected G1/G2 - the DSR literature (and this
    # module's own closed-form tests) assume the method-of-moments
    # convention (quant-gate REVIEW.md finding 2).
    skew = float(stats.skew(net_returns.to_numpy(), bias=True))
    kurt = float(stats.kurtosis(net_returns.to_numpy(), fisher=False, bias=True))

    psr = probabilistic_sharpe_ratio(sr_per_period, 0.0, n, skew, kurt)

    strategy_id = result.provenance["strategy_id"]
    fam = family or strategy_id.rsplit("-", 1)[0]
    headline_record = registry.record_backtest(result, family=fam)
    headline_label = "|".join(headline_record.key)
    n_trials = registry.n_trials(fam)
    n_trials_raw = registry.n_trials_raw(fam)
    var_sr_trials = registry.var_sr_trials(fam, n)  # already per-period + floored - registry.py
    dsr = deflated_sharpe_ratio(sr_per_period, n_trials, var_sr_trials, n, skew, kurt)

    benchmark_returns_for_trl = (
        benchmark_result.net_returns if benchmark_result is not None else result.benchmark_returns
    )
    benchmark_sr_per_period = raw_sharpe(benchmark_returns_for_trl)
    if not math.isfinite(benchmark_sr_per_period):
        benchmark_sr_per_period = 0.0
    trl_confidence = config.thresholds.get("min_track_record_confidence", 0.95)
    min_trl = min_track_record_length(
        sr_per_period, benchmark_sr_per_period, skew, kurt, confidence=trl_confidence
    )

    bs = config.bootstrap
    splits = purged_kfold_splits(net_returns.index, bs.purged_cv_n_splits, bs.purged_cv_embargo)
    cv = subperiod_oof_sharpe(net_returns, splits, periods_per_year=m.periods_per_year)

    # quant-gate VERDICT.md M06 cycle-1 finding 3: the RC/SPA benchmark is a
    # STATED CHOICE (config), not an accident of whether `--benchmark` was
    # passed. A separately-supplied `benchmark_result` always overrides
    # (with a named reason); otherwise the config's `reality_check.benchmark`
    # decides between the embedded series (default, matching every other
    # benchmark gate) and an explicit zero benchmark.
    if benchmark_result is not None:
        benchmark_for_rc = benchmark_result.net_returns
        rc_benchmark_source = "cli --benchmark override"
    elif config.reality_check.benchmark == "zero":
        benchmark_for_rc = None
        rc_benchmark_source = "zero (configs/validation.yaml: reality_check.benchmark=zero)"
    else:
        benchmark_for_rc = result.benchmark_returns
        rc_benchmark_source = "embedded (result.benchmark_returns) - validation.yaml default"

    rc: RealityCheckResult | None = None
    spa: RealityCheckResult | None = None
    rc_excluded: list[str] = []
    retained_fractions: dict[str, float] = {}
    rc_none_reason: str | None = None
    try:
        matrix, rc_excluded, retained_fractions = build_trial_matrix(
            registry,
            fam,
            benchmark_for_rc,
            min_overlap_fraction=config.min_overlap_fraction,
            headline_label=headline_label,
        )
        # quant-gate VERDICT.2.md M06 cycle-2 finding A item 1: a CODE-LEVEL
        # invariant, not only a test - `build_trial_matrix` is documented to
        # raise rather than return a matrix missing the headline, but the
        # honest defence-in-depth check is asserting the actual output.
        assert headline_label in matrix.columns, (
            f"invariant violated: Reality Check/SPA matrix for family {fam!r} does not contain "
            f"the headline trial {headline_label!r} - a non-None `rc`/`spa` result must always "
            "have the headline as a matrix column; build_trial_matrix should have raised instead."
        )
        rc = white_reality_check(matrix, bs.b, bs.block_len, bs.seed)
        spa = hansen_spa(matrix, bs.b, bs.block_len, bs.seed)
    except ValueError as exc:
        rc_excluded = getattr(exc, "excluded", rc_excluded)
        retained_fractions = getattr(exc, "retained_fractions", retained_fractions)
        reason_kind = getattr(exc, "reason_kind", "too_few_trials_recorded")
        # quant-gate VERDICT.2.md M06 cycle-2 finding A item 2: three
        # distinguishable causes rather than one generic "fewer than 2
        # trials" message regardless of what actually happened.
        rc_none_reason = {
            "too_few_trials_recorded": (
                "Reality Check could not be run: fewer than 2 registered trials in this family "
                "have a stored return series - treated as a FAILURE, not a pass by default."
            ),
            "excluded_by_overlap_floor": f"Reality Check could not be run: {exc}",
            "no_common_dates": f"Reality Check could not be run: {exc}.",
        }.get(reason_kind, f"Reality Check could not be run: {exc}")
    headline_retained_fraction = retained_fractions.get(headline_label)

    monte_carlo = monte_carlo_summary(
        net_returns,
        bs.monte_carlo_n_paths,
        bs.block_len,
        bs.monte_carlo_seed,
        periods_per_year=m.periods_per_year,
    )

    capacity: CapacityResult | None = None
    if price_panel is not None:
        try:
            capacity = capacity_estimate(result, price_panel)
        except ValueError:
            # e.g. an empty/all-zero result.holdings_history with no
            # explicit position_frac - the capacity soft gate below already
            # treats capacity=None as a documented failure, not a crash.
            capacity = None

    gates, verdict = _evaluate_gates(
        basic=basic,
        psr=psr,
        dsr=dsr,
        min_trl=min_trl,
        n=n,
        n_trials=n_trials,
        sr_per_period=sr_per_period,
        cv=cv,
        rc=rc,
        spa=spa,
        rc_benchmark_source=rc_benchmark_source,
        rc_none_reason=rc_none_reason,
        monte_carlo=monte_carlo,
        capacity=capacity,
        result=result,
        config=config,
        price_panel_missing_tickers=price_panel_missing_tickers,
    )

    distinct_trials = registry.distinct_trials(fam)
    dirty_trial_count = sum(1 for r in distinct_trials if r.dirty)
    prov = result.provenance
    provenance = ReportCardProvenance(
        strategy_id=strategy_id,
        data_semantics_version=prov.get("data_semantics_version", "unknown"),
        quantlab_git_sha=prov.get("quantlab_git_sha", "unknown"),
        dirty=bool(prov.get("dirty", False)),
        dirty_source="provenance" if prov.get("dirty") is not None else "registry_at_record_time",
        n_trials=n_trials,
        n_trials_raw=n_trials_raw,
        dirty_trial_count=dirty_trial_count,
        rc_trial_count=rc.n_trials if rc is not None else None,
        rc_spa_benchmark_source=rc_benchmark_source,
        headline_retained_fraction=headline_retained_fraction,
        untrusted_fraction_line=basic.flags[0] if basic.flags else "",
        sharpe_sortino_convention=_SHARPE_SORTINO_CONVENTION,
    )

    known_caveats = list(result.provenance.get("known_caveats", []))
    known_caveats.append(_PURGE_VS_WALK_FORWARD_NOTE)
    known_caveats.append(_REGISTRY_BASE_POINT_NOTE)
    known_caveats.append(_SUBPERIOD_OOF_CAVEAT)
    if walk_forward is not None:
        known_caveats.append(_WALK_FORWARD_RANKING_NOTE)
        known_caveats.append(_WALK_FORWARD_NAN_TIEBREAK_NOTE)
    if dirty_trial_count > 0:
        known_caveats.append(_DIRTY_TRIAL_CAVEAT)
    known_caveats.extend(rc_excluded)

    return ReportCard(
        basic=basic,
        psr=psr,
        dsr=dsr,
        min_trl=min_trl,
        n_trials=n_trials,
        cv=cv,
        rc=rc,
        spa=spa,
        monte_carlo=monte_carlo,
        capacity=capacity,
        coverage_bound=result.coverage_report.overall_bound,
        quality_flags_summary=result.quality_flags.to_json(),
        known_caveats=known_caveats,
        gates=gates,
        provenance=provenance,
        verdict=verdict,
    )


def _evaluate_gates(
    *,
    basic: ValidationBasic,
    psr: float,
    dsr: float,
    min_trl: float,
    n: int,
    n_trials: int,
    sr_per_period: float,
    cv: SubperiodOOFResult,
    rc: RealityCheckResult | None,
    spa: RealityCheckResult | None,
    rc_benchmark_source: str,
    rc_none_reason: str | None = None,
    monte_carlo: MonteCarloResult,
    capacity: CapacityResult | None,
    result: BacktestResult,
    config: ValidationConfig,
    price_panel_missing_tickers: list[str] | None = None,
) -> tuple[list[GateResult], Verdict]:
    thresholds = config.thresholds
    m = basic.metrics
    qf = result.quality_flags
    extreme_caveat = _extreme_return_caveat(qf)
    gates: list[GateResult] = []

    # --- hard gates ---

    min_dsr = float(thresholds.get("min_dsr", 0.95))
    dsr_ok = pd.notna(dsr) and dsr >= min_dsr
    if pd.isna(dsr):
        reason = (
            f"DSR could not be computed - fewer than 2 distinct trials are registered for this "
            f"family (N={n_trials}); this is the registry being too thin, NOT a statistical "
            "failure - treated as a FAILURE (not a pass) until more genuinely distinct trials "
            "are recorded."
        )
    else:
        reason = (
            f"DSR={dsr:.4f} against the {min_dsr:.2f} bar for significance after correcting for "
            f"N={n_trials} distinct trials (computed on the PER-PERIOD Sharpe "
            f"{sr_per_period:.4f}, not the annualized {m.net_sharpe:.2f} - see "
            "deflated_sharpe.py's 'same footing' contract). " + _DSR_MONOTONICITY_NOTE
        )
    if extreme_caveat:
        reason += " " + extreme_caveat
    gates.append(
        GateResult("deflated_sharpe_ratio", "hard", float(dsr), min_dsr, bool(dsr_ok), reason)
    )

    max_rc_pvalue = float(thresholds.get("max_rc_pvalue", 0.10))
    if rc is not None:
        rc_ok = rc.p_value <= max_rc_pvalue
        reason = (
            f"White Reality Check p={rc.p_value:.4f} against the {max_rc_pvalue:.2f} bar, over "
            f"K={rc.n_trials} realised trials, benchmark={rc_benchmark_source}."
        )
        rc_value = rc.p_value
    else:
        rc_ok = False
        rc_value = float("nan")
        reason = rc_none_reason or (
            "Reality Check could not be run (fewer than 2 registered trials with a stored "
            "return series) - treated as a FAILURE, not a pass by default."
        )
    gates.append(
        GateResult("reality_check_pvalue", "hard", rc_value, max_rc_pvalue, bool(rc_ok), reason)
    )

    bench_ok = pd.notna(m.benchmark_sharpe) and m.net_sharpe >= m.benchmark_sharpe
    if pd.isna(m.benchmark_sharpe):
        reason = (
            "no usable benchmark Sharpe (NaN) - cannot compare to strategy Sharpe; treated as "
            "a failure."
        )
    else:
        reason = f"net Sharpe {m.net_sharpe:.2f} vs benchmark Sharpe {m.benchmark_sharpe:.2f}."
    gates.append(
        GateResult(
            "net_sharpe_vs_benchmark",
            "hard",
            float(m.net_sharpe),
            float(m.benchmark_sharpe),
            bool(bench_ok),
            reason,
        )
    )

    max_coverage = float(thresholds.get("max_coverage_bound_pct", 15.0))
    coverage_bound = result.coverage_report.overall_bound
    coverage_ok = coverage_bound <= max_coverage
    gates.append(
        GateResult(
            "coverage_bound",
            "hard",
            coverage_bound,
            max_coverage,
            bool(coverage_ok),
            f"worst-year coverage bound {coverage_bound:.1f}% against the {max_coverage:.1f}% "
            "ceiling.",
        )
    )

    trl_ok = pd.notna(min_trl) and min_trl <= n
    reason = (
        f"needs >= {min_trl:.0f} observations for significance; {n} are available (computed on "
        f"the PER-PERIOD Sharpe {sr_per_period:.4f}, not the annualized {m.net_sharpe:.2f})."
    )
    if extreme_caveat:
        reason += " " + extreme_caveat
    gates.append(
        GateResult(
            "min_track_record_length", "hard", float(min_trl), float(n), bool(trl_ok), reason
        )
    )

    # --- soft gates ---

    min_psr = float(thresholds.get("min_psr", 0.95))
    psr_ok = pd.notna(psr) and psr >= min_psr
    psr_reason = (
        f"PSR={psr:.4f} against the {min_psr:.2f} bar (computed on the PER-PERIOD Sharpe "
        f"{sr_per_period:.4f}, not the annualized {m.net_sharpe:.2f})."
    )
    if extreme_caveat:
        # quant-gate VERDICT.md M06 cycle-1 carried item 10: PSR consumes
        # the same truncated skew/kurt as DSR/MinTRL, whose reasons already
        # carry this caveat - PSR's own was previously missing it.
        psr_reason += " " + extreme_caveat
    gates.append(
        GateResult(
            "probabilistic_sharpe_ratio", "soft", float(psr), min_psr, bool(psr_ok), psr_reason
        )
    )

    min_cv_sharpe = float(thresholds.get("min_subperiod_oof_sharpe", 0.0))
    cv_ok = pd.notna(cv.mean_oof_sharpe) and cv.mean_oof_sharpe > min_cv_sharpe
    gates.append(
        GateResult(
            "subperiod_oof_sharpe",
            "soft",
            float(cv.mean_oof_sharpe),
            min_cv_sharpe,
            bool(cv_ok),
            f"mean Sharpe {cv.mean_oof_sharpe:.2f} over {len(cv.fold_sharpes)} contiguous "
            "sub-periods of a strategy with NO FITTED PARAMETERS - purge/embargo have no "
            "effect on this value by construction (quant-gate VERDICT.md M06 cycle-1 finding "
            "4); NOT a purged cross-validation.",
        )
    )

    # M05 carried item 2 (binding): no_cliff_score is NEVER quoted alone -
    # min_net_sharpe is evaluated alongside it, both gating the verdict.
    # quant-gate VERDICT.md M06 cycle-1 carried item 11: the sensitivity
    # result's own edge/nan_points flags must be respected in BOTH gate
    # reasons - an edge-truncated or NaN-contaminated no_cliff_score was
    # previously quoted with the same confidence as a clean interior one.
    sensitivity_flags_note = (
        f"(neighbourhood_size={basic.sensitivity.neighbourhood_size}, "
        f"neighbourhood_truncated={basic.sensitivity.neighbourhood_truncated}, "
        f"nan_points={basic.sensitivity.nan_points})"
        if basic.sensitivity is not None
        else ""
    )
    min_no_cliff = float(thresholds.get("min_no_cliff_score", 0.5))
    if basic.sensitivity is not None:
        score = basic.sensitivity.no_cliff_score
        no_cliff_ok = pd.notna(score) and score >= min_no_cliff
        reason = (
            f"no_cliff_score={score:.4f} against {min_no_cliff:.2f} {sensitivity_flags_note} - a "
            "RELATIVE-SPREAD statistic only, never evidence of quality by itself (see "
            "min_net_sharpe below)."
        )
    else:
        score = float("nan")
        no_cliff_ok = False
        reason = "no sensitivity grid was supplied - treated as a FAILURE, not a pass by default."
    gates.append(
        GateResult("no_cliff_score", "soft", score, min_no_cliff, bool(no_cliff_ok), reason)
    )

    min_net_sharpe = float(thresholds.get("min_net_sharpe", 0.3))
    net_sharpe_ok = pd.notna(m.net_sharpe) and m.net_sharpe >= min_net_sharpe
    min_net_sharpe_reason = (
        f"net Sharpe {m.net_sharpe:.2f} against {min_net_sharpe:.2f} - gated ALONGSIDE "
        "no_cliff_score per the M05 carried item (a flat-but-bad neighbourhood must not "
        "pass on no_cliff_score alone)."
    )
    if sensitivity_flags_note:
        min_net_sharpe_reason += f" Sensitivity grid: {sensitivity_flags_note}."
    gates.append(
        GateResult(
            "min_net_sharpe",
            "soft",
            float(m.net_sharpe),
            min_net_sharpe,
            bool(net_sharpe_ok),
            min_net_sharpe_reason,
        )
    )

    # Orchestrator decision (2026-09-11): wire the two M05-pre-seeded
    # thresholds the packet's own verdict bullets omitted, as SOFT gates
    # only (RESEARCH_ONLY at worst, never REJECTED).
    max_dd_floor = float(thresholds.get("max_drawdown_floor", -0.5))
    dd_ok = pd.notna(m.net_max_drawdown) and m.net_max_drawdown >= max_dd_floor
    gates.append(
        GateResult(
            "max_drawdown_floor",
            "soft",
            float(m.net_max_drawdown),
            max_dd_floor,
            bool(dd_ok),
            f"FULL-SAMPLE net max drawdown {m.net_max_drawdown:.2%} against the "
            f"{max_dd_floor:.2%} floor (never a rolling column - see "
            "max_negative_rolling_window_fraction below for that).",
        )
    )

    max_neg_rolling = float(thresholds.get("max_negative_rolling_window_fraction", 0.5))
    rolling_fraction = _max_negative_rolling_fraction(basic.rolling)
    rolling_ok = pd.notna(rolling_fraction) and rolling_fraction <= max_neg_rolling
    if basic.rolling:
        reason = (
            f"{rolling_fraction:.0%} of rolling windows had negative CAGR against the "
            f"{max_neg_rolling:.0%} bar - computed from the FROZEN ported "
            "rolling_window_metrics table, whose CAGR is blind to each window's own first "
            "return (ported convention, see rolling.py's module docstring)."
        )
    else:
        reason = (
            "no rolling window table was available - treated as a FAILURE, not a pass by default."
        )
    gates.append(
        GateResult(
            "max_negative_rolling_window_fraction",
            "soft",
            rolling_fraction,
            max_neg_rolling,
            bool(rolling_ok),
            reason,
        )
    )

    mc_max = float(thresholds.get("mc_max_prob_drawdown_worse_than_observed", 0.5))
    mc_ok = monte_carlo.prob_drawdown_worse_than_observed <= mc_max
    gates.append(
        GateResult(
            "monte_carlo_drawdown",
            "soft",
            monte_carlo.prob_drawdown_worse_than_observed,
            mc_max,
            bool(mc_ok),
            "P(bootstrap drawdown worse than observed)="
            f"{monte_carlo.prob_drawdown_worse_than_observed:.2f}.",
        )
    )

    capacity_multiple = float(thresholds.get("capacity_min_multiple_of_intended_capital", 100.0))
    # quant-gate VERDICT.md M06 cycle-1 finding 9: "intended capital" is
    # Alex's REAL stake (configs/validation.yaml intended_capital_usd), NOT
    # the backtest's own notional (BacktestConfig.initial_capital, which
    # defaults to $1,000,000 and means "the simulated book size", a
    # different thing entirely - using it made the 100x bar a $100M floor,
    # the MOST conservative of the four capacity ceilings, regardless of
    # what Alex actually intends to trade).
    intended_capital = float(config.intended_capital_usd)
    missing_tickers = sorted(price_panel_missing_tickers or [])
    missing_note = (
        f" ({len(missing_tickers)} held ticker(s) had no price cache and were excluded: "
        f"{missing_tickers})"
        if missing_tickers
        else ""
    )
    if capacity is not None and intended_capital > 0:
        cap_multiple = capacity.capacity_ceiling_min / intended_capital
        capacity_ok = cap_multiple >= capacity_multiple
        reason = (
            f"worst-case capacity ceiling is {cap_multiple:.0f}x the resolved intended capital "
            f"(${intended_capital:,.0f}, configs/validation.yaml intended_capital_usd) against "
            f"the {capacity_multiple:.0f}x bar.{missing_note}"
        )
        # quant-gate VERDICT.2.md M06 cycle-2 finding C (non-blocking): at a
        # small retail stake, clearing the bar by an order of magnitude or
        # more says nothing about edge - it says the stake is small relative
        # to the instrument's liquidity. State that plainly rather than let
        # a green badge imply the strategy itself has capacity headroom.
        if capacity_ok and cap_multiple > 10 * capacity_multiple:
            reason += (
                f" NOTE: the capacity gate is trivially passable at this stake "
                f"({cap_multiple:.0f}x against a {capacity_multiple:.0f}x bar) - this is not "
                "evidence of edge, only that the resolved intended capital is small relative to "
                "the instrument's liquidity."
            )
    else:
        cap_multiple = float("nan")
        capacity_ok = False
        if missing_tickers:
            reason = (
                f"capacity could not be estimated - {len(missing_tickers)} held ticker(s) "
                f"missing from the price cache: {missing_tickers}."
            )
        else:
            reason = (
                "no price panel was supplied - capacity was not estimated - treated as a "
                "FAILURE, not a pass by default."
            )
    gates.append(
        GateResult(
            "capacity_ceiling", "soft", cap_multiple, capacity_multiple, bool(capacity_ok), reason
        )
    )

    max_spa = float(thresholds.get("max_spa_pvalue", 0.10))
    if spa is not None:
        spa_ok = spa.p_value <= max_spa
        spa_value = spa.p_value
        reason = (
            f"Hansen SPA p={spa.p_value:.4f} against the {max_spa:.2f} bar, over "
            f"K={spa.n_trials} realised trials, benchmark={rc_benchmark_source}."
        )
    else:
        spa_ok = False
        spa_value = float("nan")
        reason = (
            "SPA could not be run (fewer than 2 registered trials with a stored return "
            "series) - treated as a FAILURE, not a pass by default."
        )
    gates.append(GateResult("spa_pvalue", "soft", spa_value, max_spa, bool(spa_ok), reason))

    min_wf_stability = float(thresholds.get("min_walk_forward_stability_fraction", 0.5))
    if basic.walk_forward is not None:
        stability = _walk_forward_stability_fraction(basic.walk_forward)
        wf_ok = pd.notna(stability) and stability >= min_wf_stability
        reason = (
            f"walk-forward chose the modal weight tuple in {stability:.0%} of steps against "
            f"the {min_wf_stability:.0%} bar."
        )
    else:
        stability = float("nan")
        wf_ok = True  # "if present" - absence does not block eligibility.
        reason = "no walk-forward result was supplied - vacuously satisfied per 'if present'."
    gates.append(
        GateResult(
            "walk_forward_stability", "soft", stability, min_wf_stability, bool(wf_ok), reason
        )
    )

    hard_failed = any(not g.passed for g in gates if g.kind == "hard")
    soft_failed = any(not g.passed for g in gates if g.kind == "soft")

    verdict: Verdict
    if hard_failed:
        verdict = "REJECTED"
    elif not soft_failed:
        verdict = "ELIGIBLE_FOR_PAPER"
    else:
        verdict = "RESEARCH_ONLY"

    return gates, verdict
