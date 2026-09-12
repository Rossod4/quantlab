"""`TrialsRegistry`: an append-only record of every backtest run and every
sensitivity grid point tried against this platform, feeding the
multiple-testing correction (`deflated_sharpe.py`'s DSR, `reality_check.py`'s
White RC / Hansen SPA) the trial count (N) and, where available, the trial
return series they need.

Identity key (binding, "From M05 verdict" item 1 in plans/QUANT-NOTES.md):
`(strategy_id, data_semantics_version, backtest_config_hash)`. Re-recording
the SAME key is idempotent for counting purposes - `n_trials()` counts
DISTINCT keys, not lines written - while the underlying JSONL file is
genuinely append-only (a rerun's record is still written, for audit, but
never overwrites or removes an earlier line). A changed param changes
`strategy_id` (`strategies/base.py`'s own hash); a changed backtest window,
cost model, or execution mode changes `backtest_config_hash`; a data-layer
change (core/semantics.py) changes `data_semantics_version` - any of the
three alone mints a new key, per the M03b verdict's original complaint that
`strategy_id` alone does not encode data semantics.

Sensitivity trials (`SensitivityResult.trials`, from sensitivity.py) use
their OWN id scheme (`_strategy_id_for_point`), deliberately independent of
`Strategy.strategy_id` (sensitivity.py's own module docstring) and already
folding in the backtest window/cost/semantics fingerprint. This registry
therefore records a sensitivity trial's key as
`(trial.strategy_id, DATA_SEMANTICS_VERSION, "sensitivity-point")` - the
third slot is a fixed sentinel rather than a real config hash, since the
fingerprint is already baked into `trial.strategy_id` itself and recomputing
it here would need the `BacktestConfig` object this registry never receives.

Base-point double counting (carried M05 item, stated rather than silently
left, per the packet's own instruction): a sensitivity grid's base point and
the strategy's own headline backtest run are typically the SAME parameters,
but they mint DIFFERENT keys (one via `Strategy.strategy_id`, one via
`_strategy_id_for_point`) and this registry makes NO attempt to reconcile
them - `n_trials()` counts both. **This is NOT, as an earlier version of this
docstring claimed, "the conservative direction for DSR" - quant-gate
VERDICT.md M06 cycle-1 finding 1 measured the opposite: recording MORE
trials whose Sharpes cluster near the existing sample mean simultaneously
raises N and SHRINKS `var_sr_trials()`'s estimate of dispersion, and the
shrinkage in `SR* = sqrt(V)*[...]` beats the `Phi^-1` growth from N -
byte-identical reruns differing only in `initial_capital` moved a real
report card's DSR from FAIL to PASS with the strategy completely unchanged.
Over-counting N is conservative ONLY holding `V[SR]` fixed, which this
registry does not do, since it estimates V from the same trial set it counts
N over.** The base-point double count is left as-is because it is a small,
disclosed, one-trial effect, NOT because its direction is safe in general -
see the "Distinct-trial deduplication" section below for what actually
keeps `n_trials()`/`var_sr_trials()` from being gamed by rerecording.

Distinct-trial deduplication (quant-gate VERDICT.md M06 cycle-1 finding 1,
remedy b/c): `n_trials()`/`var_sr_trials()` no longer operate on raw
registry KEYS. Two records whose `net_returns` values are byte-identical
cannot represent an independent search - they are the SAME trial recorded
twice under different keys (e.g. a config change that does not touch the
strategy's actual decisions, like `initial_capital`) - so `TrialRecord`
carries a `series_hash` (sha256 of the return values only, not the dates:
two GENUINELY different trials producing byte-identical return sequences by
chance is not a realistic concern at this platform's scale) and
`distinct_trials()` collapses same-hash records to one, keeping the
first-seen. Records with no stored series (`series_hash=None` - every
sensitivity trial without a supplied return series, and every historical
entry) cannot be deduplicated this way and are each kept as their own
distinct trial. `n_trials_raw()` keeps the OLD per-key count for
transparency/display (the report shows both numbers); only the
DEDUPLICATED count and variance ever reach `deflated_sharpe_ratio`.

`var_sr_trials()` also FLOORS its estimate at the sampling variance of a
single per-period Sharpe estimate under the null (Lo 2002 / Mertens:
Var(SR_hat) -> 1/n as the true SR -> 0 for i.i.d. Gaussian per-period
returns, small-sample-corrected to `1/(n_periods-1)`). Without this floor, a
handful of DISTINCT trials that happen to share a similar or identical
realised Sharpe reads as "zero true dispersion in the search", which is not
credible evidence - it is exactly as likely to mean "too few genuinely
different trials were recorded yet". An unfloored `V_hat=0` sent `SR*=0` at
ANY N (see `deflated_sharpe.py`'s own restricted special case below), making
DSR invariant to how many more trials get recorded - measured at the gate on
a real run. The floor makes `SR*` strictly positive and GROWING with N
whenever the observed dispersion is at or below the null's own sampling
noise, restoring genuine multiple-testing behaviour even in the degenerate
case.

Dirty-tree flag (carried M04 verdict item 1): at the time this module was
first written, `BacktestResult.provenance` carried `quantlab_git_sha` but no
companion `dirty` flag (the M04 verdict's item was left open at the M04
gate). M04b (a concurrent milestone) is adding `provenance["dirty"]` to the
engine itself - once merged, this registry PREFERS that value (the true
state of the tree that actually PRODUCED the result) over its own proxy.
`record_backtest` therefore reads `prov.get("dirty")`: when present (M04b
merged), `dirty`/`dirty_source="provenance"`; when absent (pre-M04b, or any
`BacktestResult` from a session that predates it), this registry falls back
to computing `dirty` itself, independently, via `git status --porcelain` AT
RECORD TIME (mirroring `engine.py`'s own `_git_sha` helper) -
`dirty_source="registry_at_record_time"`, a proxy for "at record time", not
"at run time": if a result is registered in a different process/session from
the one that produced it, this reflects the CURRENT tree, not necessarily
the tree that ran the backtest. `TrialRecord.dirty_source` makes which of the
two is in play always inspectable rather than silently assumed. A dirty-tree
trial is still recorded (never dropped), just flagged - `report_card.py`
surfaces it in the provenance section.

The registry is, by construction, a LOWER BOUND on trials actually tried: it
cannot see what a human tried in a notebook, in a REPL, or in a config that
was never run through `record_backtest`/`record_sensitivity`. N from this
registry should be read as "at least this many", never "exactly this many".

Per-period vs. annualized Sharpe (quant-gate REVIEW.md, M06 cycle-1 blocker
1): every `net_sharpe` this registry stores is now `net_sharpe_per_period`
(`metrics.raw_sharpe` - mean/std(ddof=1), NO annualization) ALONGSIDE the
existing annualized `net_sharpe` (kept for display only). `var_sr_trials()`
reads the PER-PERIOD field exclusively, because `deflated_sharpe.py`'s SR*
formula must be on the same footing as the `sr` `report_card.py` compares it
against - `report_card.py` also switched to a per-period `sr`, so this was a
two-sided fix (see report_card.py's own module docstring for the other
side). `record_sensitivity` computes the per-period figure directly from a
supplied return series when one is available, or from `trial.net_sharpe /
sqrt(periods_per_year)` (an EXACT algebraic inverse of `metrics.sharpe_
ratio`'s own annualization, not an approximation) when a caller passes
`periods_per_year` instead; with neither, `net_sharpe_per_period` is NaN
(documented, excluded from `var_sr_trials` exactly like a NaN annualized
Sharpe would be).

Historical trials: the old repo's Phase 3 momentum/value blend sweep (five
weights: 100/0, 75/25, 50/50, 25/75, 0/100 momentum/value, exactly
`DEFAULT_SWEEP_WEIGHTS` in `..\\MomentumValueStrategy\\src\\evaluation\\
comparison.py`) tried five blend configurations on the SAME window this
platform's blend strategy now covers, before this registry existed to record
them. `seed_historical_blend_trials()` pre-loads them as five distinct keys
under the "blend" family so `n_trials("blend")` does not understate how many
blend configurations were actually tried. Their exact full-sample Sharpe
ratios are NOT reproduced here: REVIEW_PHASE5.md quotes only the two
endpoints' OUT-OF-SAMPLE walk-forward Sharpe (100% momentum and 50/50 both
~+0.85) and a range for the full five (+0.76 to +0.86), not each weight's
own original Phase 3 full-sample figure - inventing precise numbers for the
other three would be false precision. Historical trials are therefore
recorded with `net_sharpe=NaN` (and, per the per-period note above,
`net_sharpe_per_period=NaN` too - `NaN / sqrt(4)` is still NaN, but the
`/ sqrt(4)` quarterly-to-per-period conversion is applied for the record,
documenting what WOULD be needed if a real number is ever substituted in -
the Phase 3 sweep ran at QUARTERLY frequency, `..\\MomentumValueStrategy\\
src\\evaluation\\comparison.py`'s own `QUARTERS_PER_YEAR=4`) and no return
series: they count toward `n_trials()` (the honest, intended effect) but are
excluded from `var_sr_trials` and from `reality_check.py`'s resampling
matrix (both of which need a real number/series), which is exactly what
`trials(..., with_series_only=True)` and NaN-filtering give for free.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from quantlab.backtest.result import BacktestResult
from quantlab.core.semantics import DATA_SEMANTICS_VERSION
from quantlab.validation.metrics import PERIODS_PER_YEAR, raw_sharpe, sharpe_ratio
from quantlab.validation.sensitivity import SensitivityResult

_JSONL_NAME = "trials.jsonl"
_SERIES_SUBDIR = "series"
_SENSITIVITY_CONFIG_SENTINEL = "sensitivity-point"
_HISTORICAL_CONFIG_SENTINEL = "phase3-blend-sweep"
_HISTORICAL_SEMANTICS_SENTINEL = "pre-quantlab"

# Old repo's `src/evaluation/comparison.py::DEFAULT_SWEEP_WEIGHTS` - the
# momentum-weight side of each of the five Phase 3 blend configurations
# (value weight is `1 - w`). Reproduced as a literal, not imported: the old
# repo is a separate, frozen project (CLAUDE.md invariant #4), not a runtime
# dependency of quantlab.
_HISTORICAL_BLEND_MOMENTUM_WEIGHTS = (1.0, 0.75, 0.5, 0.25, 0.0)
# The Phase 3 blend sweep's own working frequency (comparison.py's
# QUARTERS_PER_YEAR) - see seed_historical_blend_trials.
_HISTORICAL_PERIODS_PER_YEAR = 4

Key = tuple[str, str, str]


def _canonical_hash(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:10]


def _family_from_strategy_id(strategy_id: str) -> str:
    """`{name}-{hash}` -> `{name}` - the registered strategy name (momentum /
    value_composite / blend), matching `strategies/base.py::strategy_id` and
    `sensitivity._strategy_id_for_point`'s identical convention."""
    return strategy_id.rsplit("-", 1)[0]


def _series_hash(net_returns: pd.Series) -> str:
    """sha256 of the return series' VALUES only (not its date index) - see
    module docstring's "Distinct-trial deduplication" section."""
    return hashlib.sha256(net_returns.to_numpy().tobytes()).hexdigest()


def _default_repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    return Path.cwd()


def _git_dirty(repo_root: Path) -> bool:
    """See module docstring's "Dirty-tree flag" section. Any failure to
    determine cleanliness (git missing, not a repo, timeout) is treated as
    dirty=True - the conservative, flagged side, never silently clean."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0:
            return bool(result.stdout.strip())
    except OSError:
        pass
    return True


@dataclass(frozen=True)
class TrialRecord:
    """One recorded trial, deduplicated by `key`. `series_path` is None for
    a trial with no stored net-return series (every sensitivity trial today,
    and every historical trial - see module docstring)."""

    key: Key
    family: str
    source: str  # "backtest" | "sensitivity" | "historical"
    net_sharpe: float  # ANNUALIZED - display/labels only, see module docstring
    # PER-PERIOD (metrics.raw_sharpe) - what var_sr_trials() actually reads;
    # see module docstring's "Per-period vs. annualized Sharpe" section.
    net_sharpe_per_period: float
    n_periods: int
    periods_per_year: int
    quantlab_git_sha: str
    dirty: bool
    # "provenance" (M04b's own `BacktestResult.provenance["dirty"]`, the
    # true state of the tree that PRODUCED the result), "registry_at_record_
    # time" (this registry's own `git status --porcelain` fallback, a proxy
    # for whatever tree happens to be checked out when `record_backtest`
    # runs), or "historical" (a pre-loaded entry with no real git state at
    # all - see `seed_historical_blend_trials`). See module docstring.
    dirty_source: str
    series_path: str | None
    # sha256 of the return series VALUES (not the dates) - None when no
    # series is stored (sensitivity trials without a supplied series,
    # historical entries). See module docstring's "Distinct-trial
    # deduplication" section.
    series_hash: str | None
    recorded_at: str

    def to_json(self) -> dict[str, Any]:
        return {
            "key": list(self.key),
            "family": self.family,
            "source": self.source,
            "net_sharpe": self.net_sharpe,
            "net_sharpe_per_period": self.net_sharpe_per_period,
            "n_periods": self.n_periods,
            "periods_per_year": self.periods_per_year,
            "quantlab_git_sha": self.quantlab_git_sha,
            "dirty": self.dirty,
            "dirty_source": self.dirty_source,
            "series_path": self.series_path,
            "series_hash": self.series_hash,
            "recorded_at": self.recorded_at,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> TrialRecord:
        return cls(
            key=tuple(data["key"]),
            family=data["family"],
            source=data["source"],
            net_sharpe=data["net_sharpe"],
            net_sharpe_per_period=data.get("net_sharpe_per_period", float("nan")),
            n_periods=data["n_periods"],
            periods_per_year=data["periods_per_year"],
            quantlab_git_sha=data["quantlab_git_sha"],
            dirty=data["dirty"],
            dirty_source=data.get("dirty_source", "registry_at_record_time"),
            series_path=data["series_path"],
            series_hash=data.get("series_hash"),
            recorded_at=data["recorded_at"],
        )


class TrialsRegistry:
    """Append-only JSONL trial log under `reports_dir/trials/trials.jsonl`,
    with a parquet sidecar per trial that has a real return series (under
    `reports_dir/trials/series/`)."""

    def __init__(self, reports_dir: str | Path, repo_root: str | Path | None = None) -> None:
        self.trials_dir = Path(reports_dir) / "trials"
        self.trials_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.trials_dir / _JSONL_NAME
        self.series_dir = self.trials_dir / _SERIES_SUBDIR
        self.series_dir.mkdir(parents=True, exist_ok=True)
        self._repo_root = Path(repo_root) if repo_root is not None else _default_repo_root()

    # --- raw log I/O ---------------------------------------------------

    def _append(self, record: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=True) + "\n")

    def _read_all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        text = self.path.read_text(encoding="utf-8")
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    def _existing_keys(self) -> set[Key]:
        return {tuple(r["key"]) for r in self._read_all()}

    def _write_series(self, key: Key, net_returns: pd.Series) -> Path:
        digest = hashlib.sha256("|".join(key).encode("utf-8")).hexdigest()[:16]
        path = self.series_dir / f"{digest}.parquet"
        frame = net_returns.rename("net_return").to_frame()
        frame.index.name = "date"
        frame.to_parquet(path)
        return path

    # --- recording -------------------------------------------------------

    def record_backtest(self, result: BacktestResult, *, family: str | None = None) -> TrialRecord:
        """Record one full backtest run. Always appends (audit trail); the
        key may already exist (idempotent for `n_trials()` purposes).

        `dirty`/`dirty_source`: prefers `result.provenance["dirty"]` (M04b)
        when present - the true state of the tree that PRODUCED this result
        - falling back to this registry's own `git status --porcelain` at
        record time otherwise (see module docstring)."""
        prov = result.provenance
        strategy_id = prov["strategy_id"]
        semantics = prov.get("data_semantics_version", "unknown")
        config_hash = _canonical_hash(prov.get("backtest_config", {}))
        key: Key = (strategy_id, semantics, config_hash)
        fam = family or _family_from_strategy_id(strategy_id)
        periods_per_year = PERIODS_PER_YEAR[prov["backtest_config"]["rebalance_freq"]]
        net_sharpe = sharpe_ratio(result.net_returns, periods_per_year=periods_per_year)
        net_sharpe_per_period = raw_sharpe(result.net_returns)
        series_path = self._write_series(key, result.net_returns)

        provenance_dirty = prov.get("dirty")
        if provenance_dirty is not None:
            dirty, dirty_source = bool(provenance_dirty), "provenance"
        else:
            dirty, dirty_source = _git_dirty(self._repo_root), "registry_at_record_time"

        record = TrialRecord(
            key=key,
            family=fam,
            source="backtest",
            net_sharpe=net_sharpe,
            net_sharpe_per_period=net_sharpe_per_period,
            n_periods=len(result.net_returns),
            periods_per_year=periods_per_year,
            quantlab_git_sha=prov.get("quantlab_git_sha", "unknown"),
            dirty=dirty,
            dirty_source=dirty_source,
            series_path=str(series_path),
            series_hash=_series_hash(result.net_returns),
            recorded_at=pd.Timestamp.now("UTC").isoformat(),
        )
        self._append(record.to_json())
        return record

    def record_sensitivity(
        self,
        sensitivity: SensitivityResult,
        *,
        family: str,
        net_returns_by_strategy_id: dict[str, pd.Series] | None = None,
        periods_per_year: int | None = None,
    ) -> list[TrialRecord]:
        """Record every grid point in `sensitivity.trials`. `sensitivity_grid`
        itself discards each point's raw result after extracting its Sharpe
        (sensitivity.py's own module docstring), so a return series is only
        available here if the CALLER separately captured one per
        `strategy_id` (e.g. from its own injected runner) and passes it via
        `net_returns_by_strategy_id` - omitted (the common case), every point
        is recorded Sharpe-only (`series_path=None`), which still counts
        correctly toward `n_trials()`.

        `net_sharpe_per_period` (see module docstring): computed directly
        from a supplied return series when available; else, if the caller
        passes `periods_per_year` (the grid's own `backtest_config.
        rebalance_freq`-derived value - this registry has no other way to
        know it), via `trial.net_sharpe / sqrt(periods_per_year)` - the
        EXACT algebraic inverse of `metrics.sharpe_ratio`'s own
        annualization, not an approximation. NaN when neither is available.
        """
        series_by_id = net_returns_by_strategy_id or {}
        dirty = _git_dirty(self._repo_root)
        now = pd.Timestamp.now("UTC").isoformat()
        records = []
        for trial in sensitivity.trials:
            key: Key = (trial.strategy_id, DATA_SEMANTICS_VERSION, _SENSITIVITY_CONFIG_SENTINEL)
            series_path: str | None = None
            series_hash: str | None = None
            net_returns = series_by_id.get(trial.strategy_id)
            if net_returns is not None:
                series_path = str(self._write_series(key, net_returns))
                series_hash = _series_hash(net_returns)
                net_sharpe_per_period = raw_sharpe(net_returns)
            elif periods_per_year is not None and periods_per_year > 0:
                net_sharpe_per_period = trial.net_sharpe / math.sqrt(periods_per_year)
            else:
                net_sharpe_per_period = float("nan")
            record = TrialRecord(
                key=key,
                family=family,
                source="sensitivity",
                net_sharpe=trial.net_sharpe,
                net_sharpe_per_period=net_sharpe_per_period,
                n_periods=len(net_returns) if net_returns is not None else 0,
                periods_per_year=periods_per_year or 0,
                quantlab_git_sha="n/a",
                dirty=dirty,
                dirty_source="registry_at_record_time",
                series_path=series_path,
                series_hash=series_hash,
                recorded_at=now,
            )
            self._append(record.to_json())
            records.append(record)
        return records

    def seed_historical_blend_trials(self, family: str = "blend") -> list[TrialRecord]:
        """Idempotently pre-load the old repo's Phase 3 blend sweep (see
        module docstring). Unlike `record_backtest`/`record_sensitivity`,
        this SKIPS keys already present - called once per registry lifetime
        (or many times harmlessly), it must not keep re-appending the same
        five historical entries."""
        existing = self._existing_keys()
        now = pd.Timestamp.now("UTC").isoformat()
        records = []
        for weight in _HISTORICAL_BLEND_MOMENTUM_WEIGHTS:
            strategy_id = f"blend-historical-phase3-mom{weight:.2f}"
            key: Key = (strategy_id, _HISTORICAL_SEMANTICS_SENTINEL, _HISTORICAL_CONFIG_SENTINEL)
            if key in existing:
                continue
            net_sharpe = float("nan")
            # The Phase 3 sweep ran at QUARTERLY frequency (comparison.py's
            # own QUARTERS_PER_YEAR=4) - this documents the annualized ->
            # per-period conversion that WOULD apply if a real net_sharpe is
            # ever substituted in (see module docstring); NaN / sqrt(4) is
            # still NaN today.
            net_sharpe_per_period = net_sharpe / math.sqrt(_HISTORICAL_PERIODS_PER_YEAR)
            record = TrialRecord(
                key=key,
                family=family,
                source="historical",
                net_sharpe=net_sharpe,
                net_sharpe_per_period=net_sharpe_per_period,
                n_periods=0,
                periods_per_year=_HISTORICAL_PERIODS_PER_YEAR,
                quantlab_git_sha="n/a",
                dirty=False,
                dirty_source="historical",
                series_path=None,
                series_hash=None,
                recorded_at=now,
            )
            self._append(record.to_json())
            records.append(record)
        return records

    # --- reading -----------------------------------------------------------

    def trials(
        self, family: str | None = None, *, with_series_only: bool = False
    ) -> list[TrialRecord]:
        """Deduplicated (by KEY, first occurrence) trial records, optionally
        filtered by family and/or to only those with a stored return series.
        This is the RAW, per-key view - see `n_trials_raw()`. For anything
        feeding DSR, use `n_trials()`/`var_sr_trials()`, which additionally
        collapse by return-series content (see module docstring)."""
        seen: dict[Key, TrialRecord] = {}
        for raw in self._read_all():
            record = TrialRecord.from_json(raw)
            seen.setdefault(record.key, record)
        results = list(seen.values())
        if family is not None:
            results = [r for r in results if r.family == family]
        if with_series_only:
            results = [r for r in results if r.series_path is not None]
        return results

    def distinct_trials(self, family: str) -> list[TrialRecord]:
        """`trials(family)`, further collapsed by `series_hash`: two records
        whose return series are byte-identical are ONE trial (quant-gate
        VERDICT.md M06 cycle-1 finding 1) - keeps the first-seen. Records
        with `series_hash=None` cannot be deduplicated this way and are each
        kept as their own distinct trial."""
        by_key = self.trials(family)
        seen_hashes: set[str] = set()
        distinct: list[TrialRecord] = []
        for record in by_key:
            if record.series_hash is None:
                distinct.append(record)
                continue
            if record.series_hash in seen_hashes:
                continue
            seen_hashes.add(record.series_hash)
            distinct.append(record)
        return distinct

    def n_trials(self, family: str) -> int:
        """Distinct trials recorded for `family`, AFTER return-series
        deduplication (`distinct_trials`) - the N that `deflated_sharpe_
        ratio`/White/Hansen consume. See module docstring for why this is a
        lower bound, why a sensitivity base point may double-count against
        the strategy's own headline run, and why raw KEY count alone (
        `n_trials_raw()`) is not safe to feed the DSR gate."""
        return len(self.distinct_trials(family))

    def n_trials_raw(self, family: str) -> int:
        """Distinct registry KEYS for `family`, WITHOUT return-series
        deduplication - kept for transparency/display only (the report shows
        both numbers). Never pass this to `deflated_sharpe_ratio` - see
        `n_trials()`."""
        return len(self.trials(family))

    def var_sr_trials(self, family: str, n_periods: int) -> float:
        """Sample variance (ddof=1) of PER-PERIOD net Sharpe (`net_sharpe_
        per_period` - NOT the annualized `net_sharpe`; see module docstring's
        "Per-period vs. annualized Sharpe" section) across every DISTINCT
        trial in `family` (`distinct_trials` - quant-gate VERDICT.md M06
        cycle-1 finding 1) that has a finite value. NaN if fewer than 2
        distinct finite trials exist (deliberately - see
        `deflated_sharpe_ratio`'s own `n_trials == 1` special case, which
        this feeds nothing into when there is only one distinct trial).

        FLOORED at `1/(n_periods - 1)` - the sampling variance of a single
        per-period Sharpe estimate under the null (Lo 2002 / Mertens:
        Var(SR_hat) -> 1/n as the true SR -> 0 for i.i.d. Gaussian per-period
        returns; `n_periods` is the CURRENT result's own period count, the
        relevant sample size for "how noisy is one Sharpe estimate here").
        Without this floor, several distinct trials that happen to share a
        similar or identical realised Sharpe read as "zero true dispersion",
        which is not credible evidence at any finite sample size - it makes
        `SR*` (and therefore DSR) invariant to N, exactly the failure mode
        this floor closes. `n_periods <= 1` returns NaN (the floor is
        undefined).
        """
        if n_periods <= 1:
            return float("nan")
        sharpes = [
            r.net_sharpe_per_period
            for r in self.distinct_trials(family)
            if pd.notna(r.net_sharpe_per_period)
        ]
        if len(sharpes) < 2:
            return float("nan")
        v_hat = float(pd.Series(sharpes).var(ddof=1))
        floor = 1.0 / (n_periods - 1)
        return max(v_hat, floor)

    def load_series(self, record: TrialRecord) -> pd.Series:
        if record.series_path is None:
            raise ValueError(f"trial {record.key!r} has no stored return series")
        frame = pd.read_parquet(record.series_path)
        series = frame["net_return"]
        series.index = pd.DatetimeIndex(series.index, name="date")
        return series
