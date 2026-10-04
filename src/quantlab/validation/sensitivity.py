"""Parameter-sensitivity ("no-cliff") checks: rerun a strategy over a small
grid of one or two parameters and ask whether the result is a smooth ridge
or a cliff edge around the chosen (base) point - a strategy whose Sharpe
collapses from a one-step parameter nudge is fragile even if its own
headline number looks good.

The backtest runner is INJECTED (`SensitivityRunner`) so the offline test
suite never runs a real backtest - tests use a fake runner that returns
canned results. `sensitivity_grid` itself never imports `quantlab.
strategies`/`quantlab.backtest.engine`; it treats `strategy_config` as an
opaque identifier forwarded to the runner, and builds its own per-point
`strategy_id` (a family id derived from `strategy_config` plus a hash of
that point's params - independent of, and not to be confused with,
`Strategy.strategy_id`'s own id scheme in strategies/base.py, which this
module has no access to per its Context restriction and does not need:
the runner owns actually constructing/running the real strategy). Every
point is recorded as a trial with a DISTINCT strategy_id, ready for M06's
trials registry to consume via `SensitivityResult.trials`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import product
from pathlib import Path
from typing import Any, Protocol

import pandas as pd

from quantlab.backtest.config import BacktestConfig
from quantlab.core.semantics import DATA_SEMANTICS_VERSION
from quantlab.validation.metrics import PERIODS_PER_YEAR, sharpe_ratio

logger = logging.getLogger(__name__)


class SensitivityGridError(RuntimeError):
    """Raised by `sensitivity_grid` when EVERY grid point's `runner()` call
    failed - i.e. there is nothing to report at all (see `sensitivity_grid`'s
    docstring's "loud grid-point failures" section). Distinct from a bare
    `Exception` so a caller (`cli.py`'s `_build_sensitivity_result`) can
    still degrade `--full` to "no sensitivity result" without a broad
    `except Exception` also hiding an unrelated programming error - and so
    the message ALWAYS names every failing point and its own reason,
    never just the first one encountered."""


class HasNetReturns(Protocol):
    """Structural type for whatever the injected runner returns - a real
    `BacktestResult` satisfies this, and so does a minimal test fake with
    just a `net_returns` attribute."""

    net_returns: pd.Series


SensitivityRunner = Callable[[str | Path, dict[str, Any], BacktestConfig], HasNetReturns]


@dataclass(frozen=True)
class SensitivityTrial:
    strategy_id: str
    params: dict[str, Any]
    net_sharpe: float

    def to_json(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "params": self.params,
            "net_sharpe": self.net_sharpe,
        }


@dataclass(frozen=True)
class SensitivityResult:
    param_axes: dict[str, list[Any]]
    base_point: dict[str, Any]
    trials: list[SensitivityTrial]
    surface: pd.Series
    no_cliff_score: float
    # quant-gate VERDICT.md cycle-1 finding 2: `no_cliff_score`'s
    # neighbourhood silently narrows to 2 points (instead of 3) when the
    # base point sits at a grid edge on any axis, which mechanically raises
    # the score - a reader with only `no_cliff_score` cannot tell an edge
    # score from an interior one. These two fields make that inspectable.
    neighbourhood_size: int
    neighbourhood_truncated: bool
    # quant-gate carried item 8: a NaN Sharpe in the neighbourhood (e.g. a
    # zero-volatility grid point) is excluded before computing
    # `no_cliff_score`, rather than left in for builtin `max`/`min` to
    # silently mishandle - see `sensitivity_grid`'s docstring. Counts how
    # many were excluded, so a caller can tell "flat because the surface
    # is genuinely flat" from "flat because most of the sample was NaN".
    nan_points: int = 0
    # M09 fix (orchestrator-directed): `record_sensitivity` (registry.py)
    # can only store a grid point's return series when the CALLER supplies
    # one via `net_returns_by_strategy_id` - before this field existed,
    # `sensitivity_grid` (below) discarded each point's `result.net_returns`
    # right after extracting its Sharpe, so every sensitivity trial was
    # PERMANENTLY series-less and `build_trial_matrix` (reality_check.py)
    # could never find enough trials WITH a series to run White's Reality
    # Check / Hansen SPA (K stays 0 or 1 forever, regardless of how many
    # grid points ran) - a silent, structural hard-gate failure, not a
    # missing-data one. Populated automatically by `sensitivity_grid`
    # (keyed by each trial's own `strategy_id`, matching `SensitivityTrial.
    # strategy_id`); deliberately excluded from `to_json()` (a raw
    # `pd.Series` per grid point, not meant for the report card's JSON) -
    # `cli.py`'s `_record_sensitivity_result` reads this field directly and
    # forwards it to `TrialsRegistry.record_sensitivity`.
    net_returns_by_strategy_id: dict[str, pd.Series] = field(default_factory=dict)
    # M09 fix (orchestrator-directed, "make grid-point failures loud"):
    # before this field existed, `sensitivity_grid` let the FIRST
    # `runner()` exception from ANY point propagate uncaught, which killed
    # the ENTIRE grid - including every point that would have succeeded -
    # and `cli.py`'s `_build_sensitivity_result` then swallowed that single
    # exception into a quiet stderr echo with `return None`, so a whole
    # family's sensitivity check could silently vanish (N stuck at 1,
    # DSR/no_cliff both NaN) from ONE bad grid point (e.g. an axis name that
    # is not actually a field on the strategy's own params model). Now each
    # point's failure is caught individually, logged immediately (loud, not
    # deferred), and recorded here keyed by the point's own params repr;
    # the grid continues with whatever points DID succeed. Only when EVERY
    # point fails does `sensitivity_grid` raise (`SensitivityGridError`,
    # naming every point and its own reason - never just the first).
    failed_points: dict[str, str] = field(default_factory=dict)
    # M09 orchestrator-directed item: one entry per grid point whose OWN
    # backtest made MORE provider calls (see `_wrap_providers_for_call_
    # counting` in backtest/engine.py) than the `base_provider_calls` this
    # call of `sensitivity_grid` was given - a caching/memoisation
    # regression signal (the SAME strategy family rerun over the SAME
    # window should never need materially more provider calls than the
    # headline run), not evidence about the strategy itself. Populated by
    # `sensitivity_grid` from each point's own `result.provenance` when the
    # runner returns a real `BacktestResult` (a test fake with only
    # `net_returns` simply never triggers this - `getattr` degrades
    # cleanly); logged immediately, same as `failed_points`.
    provider_call_warnings: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "param_axes": self.param_axes,
            "base_point": self.base_point,
            "trials": [t.to_json() for t in self.trials],
            "surface": {str(k): v for k, v in self.surface.items()},
            "no_cliff_score": self.no_cliff_score,
            "neighbourhood_size": self.neighbourhood_size,
            "neighbourhood_truncated": self.neighbourhood_truncated,
            "nan_points": self.nan_points,
            "failed_points": self.failed_points,
            "provider_call_warnings": self.provider_call_warnings,
        }


def _strategy_id_for_point(
    strategy_config: str | Path, params: dict[str, Any], backtest_config: BacktestConfig
) -> str:
    """A distinct id per grid point within the same strategy_config
    "family" - a family prefix (the config path/name) plus a short hash of
    that point's params AND the parts of `backtest_config` that change what
    a rerun MEANS: the window (`start`/`end`), `execution` mode, and the
    cost model's own parameters (`cost_model`, `one_way_cost_bps`,
    `corwin_schultz_lookback_days`, `borrow_fee_annual_bps`), plus
    `DATA_SEMANTICS_VERSION` (core/semantics.py). Mirrors the
    `f"{name}-{digest}"` convention `strategies/blend.py`'s own
    `strategy_id` uses, without depending on that module.

    Quant-gate carried item 7: without the `backtest_config`/semantics
    fingerprint, the SAME grid of `params` rerun over a DIFFERENT backtest
    window (or cost assumption, or after a data-semantics change) produced
    an IDENTICAL id - M06's trials registry would then treat two genuinely
    different runs as repeats of the same trial."""
    family = Path(strategy_config).stem
    fingerprint = {
        "params": params,
        "start": str(backtest_config.start),
        "end": str(backtest_config.end),
        "execution": backtest_config.execution,
        "cost_model": backtest_config.cost_model,
        "one_way_cost_bps": backtest_config.one_way_cost_bps,
        "corwin_schultz_lookback_days": backtest_config.corwin_schultz_lookback_days,
        "borrow_fee_annual_bps": backtest_config.borrow_fee_annual_bps,
        "data_semantics_version": DATA_SEMANTICS_VERSION,
    }
    canonical = json.dumps(fingerprint, sort_keys=True, default=str)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:10]
    return f"{family}-{digest}"


def _grid_points(param_axes: dict[str, list[Any]]) -> list[dict[str, Any]]:
    names = list(param_axes.keys())
    return [dict(zip(names, combo, strict=True)) for combo in product(*param_axes.values())]


def _neighbourhood_mask(
    param_axes: dict[str, list[Any]], base_point: dict[str, Any], point: dict[str, Any]
) -> bool:
    """Chebyshev ball of radius 1 around `base_point`, in GRID-INDEX space
    (not value space) for each axis - "the base point and its immediate
    neighbours" generalized to N axes. For one axis this is exactly "the
    base value and its left/right neighbours in the axis list"."""
    for name, values in param_axes.items():
        base_idx = values.index(base_point[name])
        point_idx = values.index(point[name])
        if abs(point_idx - base_idx) > 1:
            return False
    return True


def _axis_has_full_neighbourhood(values: list[Any], base_value: Any) -> bool:
    """True when `base_value`'s index has both a left AND a right neighbour
    in `values` (the "interior", 3-point case); False at either end (a
    2-point edge) or for a single-element axis (a 1-point axis, trivially
    an edge). Used to detect when `no_cliff_score`'s neighbourhood was
    truncated by a grid edge on at least one axis (quant-gate VERDICT.md
    cycle-1 finding 2)."""
    idx = values.index(base_value)
    return 0 < idx < len(values) - 1


def sensitivity_grid(
    strategy_config: str | Path,
    param_axes: dict[str, list[Any]],
    backtest_config: BacktestConfig,
    runner: SensitivityRunner,
    base_point: dict[str, Any] | None = None,
    base_provider_calls: int | None = None,
) -> SensitivityResult:
    """Rerun (via `runner`) over the Cartesian product of `param_axes`
    (1 or 2 parameters; more raises `ValueError` - the work packet's own
    examples never go beyond two) and report the net-Sharpe surface plus a
    `no_cliff_score`.

    `runner(strategy_config, params, backtest_config) -> HasNetReturns` is
    called once per grid point, where `params` is that point's full
    parameter dict (one value per axis). `periods_per_year` for the Sharpe
    computation comes from `backtest_config.rebalance_freq`, exactly as
    `metrics.summary()` derives it.

    A point whose `runner()` call raises is caught, logged immediately, and
    recorded in the result's `failed_points` rather than aborting the whole
    grid (M09 fix, "make grid-point failures loud" - see `SensitivityResult.
    failed_points`'s own docstring for why this matters); `SensitivityGridError`
    is raised only if EVERY point fails. `base_provider_calls`, when given,
    is compared against each SUCCESSFUL point's own `result.provenance
    ["total_provider_calls"]` (only meaningful when `runner` returns a real
    `BacktestResult`) and any point exceeding it is recorded in
    `provider_call_warnings`.

    `base_point` defaults to the middle value of each axis (e.g. the middle
    of [9, 12, 15] is 12) when omitted, but ONLY for ODD-length axes, which
    have an unambiguous middle element. An EVEN-length axis (e.g. [30, 50])
    has no true center - `values[len//2]` would silently pick the LAST
    element, i.e. a grid edge, which mechanically inflates `no_cliff_score`
    (quant-gate VERDICT.md cycle-1 finding 2). `base_point` is therefore
    REQUIRED (raises `ValueError` if omitted) whenever any axis has an even
    length.

    `no_cliff_score = 1 - (max - min) / |median|` of net Sharpe over the
    grid's immediate neighbours of the base point (see
    `_neighbourhood_mask`): 1.0 means perfectly flat across the
    neighbourhood, and it falls toward/below 0 as the neighbourhood's worst
    and best points diverge relative to the neighbourhood's typical
    (median) Sharpe - i.e. the base point sits on a cliff. NaN when the
    neighbourhood's median Sharpe is exactly zero (the ratio is undefined,
    not "perfectly flat"). The neighbourhood itself can be truncated to 2
    points (instead of 3) when the base point sits at an axis edge, which
    mechanically raises the score from a smaller sample - `neighbourhood_
    size`/`neighbourhood_truncated` on the returned `SensitivityResult`
    make that inspectable rather than silent. A neighbour with a NaN
    Sharpe (e.g. a zero-volatility grid point) is excluded before the
    max/min/median computation, regardless of grid enumeration order -
    `nan_points` records how many were excluded.
    """
    if len(param_axes) not in (1, 2):
        raise ValueError(f"sensitivity_grid supports 1 or 2 parameter axes, got {len(param_axes)}")

    if base_point is None:
        even_axes = [name for name, values in param_axes.items() if len(values) % 2 == 0]
        if even_axes:
            raise ValueError(
                f"base_point must be given explicitly for even-length axis/axes "
                f"{even_axes} - there is no unambiguous middle value to default to "
                "(values[len//2] would silently pick a grid edge)"
            )
        base_point = {name: values[len(values) // 2] for name, values in param_axes.items()}

    freq = backtest_config.rebalance_freq
    periods_per_year = PERIODS_PER_YEAR[freq]

    points = _grid_points(param_axes)
    trials: list[SensitivityTrial] = []
    surface_index: list[tuple[Any, ...]] = []
    surface_values: list[float] = []
    neighbourhood_sharpes: list[float] = []
    net_returns_by_strategy_id: dict[str, pd.Series] = {}
    failed_points: dict[str, str] = {}
    provider_call_warnings: list[str] = []

    for point in points:
        strategy_id = _strategy_id_for_point(strategy_config, point, backtest_config)
        try:
            result = runner(strategy_config, point, backtest_config)
        except Exception as exc:  # noqa: BLE001 - deliberately broad; see below
            # M09 fix ("make grid-point failures loud"): caught HERE, per
            # point, rather than letting the first bad point kill the
            # WHOLE grid (the pre-fix behaviour) or letting a caller's
            # broad except silently discard every point that already
            # succeeded. Logged immediately - a real multi-hour grid run
            # must not have to wait for the end, or for someone to notice a
            # quiet stderr line, to learn a point failed and why.
            reason = f"{type(exc).__name__}: {exc}"
            logger.warning("sensitivity grid point %r failed: %s", point, reason)
            failed_points[repr(point)] = reason
            continue
        net_sharpe = sharpe_ratio(result.net_returns, periods_per_year=periods_per_year)
        trials.append(
            SensitivityTrial(strategy_id=strategy_id, params=point, net_sharpe=net_sharpe)
        )
        # M09 fix: capture the series HERE, while `result` is still in hand
        # - the whole point of `SensitivityResult.net_returns_by_strategy_id`
        # (see its own docstring) is that this is the ONLY place a grid
        # point's real return series is ever available at all.
        net_returns_by_strategy_id[strategy_id] = result.net_returns
        surface_index.append(tuple(point[name] for name in param_axes))
        surface_values.append(net_sharpe)
        if _neighbourhood_mask(param_axes, base_point, point):
            neighbourhood_sharpes.append(net_sharpe)

        # M09 orchestrator-directed item: only meaningful when `runner`
        # returns a real `BacktestResult` (a test fake with just
        # `net_returns` has no `.provenance` - `getattr` degrades cleanly).
        point_provenance = getattr(result, "provenance", None)
        if base_provider_calls is not None and isinstance(point_provenance, dict):
            point_calls = point_provenance.get("total_provider_calls")
            if point_calls is not None and point_calls > base_provider_calls:
                warning = (
                    f"sensitivity grid point {point} made {point_calls} provider call(s) "
                    f"against {base_provider_calls} for the headline run - possible "
                    "caching/memoisation regression, not evidence about the strategy"
                )
                logger.warning(warning)
                provider_call_warnings.append(warning)

    if not trials:
        detail = "; ".join(f"{params}: {reason}" for params, reason in failed_points.items())
        raise SensitivityGridError(
            f"every grid point failed ({len(failed_points)}/{len(points)}) - nothing to report: "
            f"{detail}"
        )

    surface = pd.Series(
        surface_values,
        index=pd.Index(surface_index, name=tuple(param_axes.keys())),
        name="net_sharpe",
    )

    # Quant-gate carried item 8: builtin `max`/`min` keep a NaN if it is
    # encountered FIRST (every subsequent `x > nan`/`x < nan` comparison is
    # False, so the running max/min never updates away from it) but skip
    # over one encountered later (`nan > current` is also False, so the
    # existing running max/min survives) - `pandas.Series.median()`, by
    # contrast, always skips NaN. Mixing the two makes `no_cliff_score`
    # depend on grid ENUMERATION ORDER whenever a neighbour's Sharpe is
    # NaN (e.g. a zero-volatility point). Filtering NaN out explicitly,
    # once, before any of max/min/median see the list, removes that
    # order-dependence entirely.
    finite_sharpes = [s for s in neighbourhood_sharpes if not math.isnan(s)]
    nan_points = len(neighbourhood_sharpes) - len(finite_sharpes)

    if not finite_sharpes:
        no_cliff_score = float("nan")
    else:
        median = pd.Series(finite_sharpes).median()
        if median == 0:
            no_cliff_score = float("nan")
        else:
            spread = max(finite_sharpes) - min(finite_sharpes)
            no_cliff_score = 1 - spread / abs(median)

    neighbourhood_truncated = any(
        not _axis_has_full_neighbourhood(values, base_point[name])
        for name, values in param_axes.items()
    )

    return SensitivityResult(
        param_axes=param_axes,
        base_point=base_point,
        trials=trials,
        surface=surface,
        no_cliff_score=no_cliff_score,
        neighbourhood_size=len(neighbourhood_sharpes),
        neighbourhood_truncated=neighbourhood_truncated,
        nan_points=nan_points,
        net_returns_by_strategy_id=net_returns_by_strategy_id,
        failed_points=failed_points,
        provider_call_warnings=provider_call_warnings,
    )
