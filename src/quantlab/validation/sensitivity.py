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
import math
from collections.abc import Callable
from dataclasses import dataclass
from itertools import product
from pathlib import Path
from typing import Any, Protocol

import pandas as pd

from quantlab.backtest.config import BacktestConfig
from quantlab.core.semantics import DATA_SEMANTICS_VERSION
from quantlab.validation.metrics import PERIODS_PER_YEAR, sharpe_ratio


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

    for point in points:
        strategy_id = _strategy_id_for_point(strategy_config, point, backtest_config)
        result = runner(strategy_config, point, backtest_config)
        net_sharpe = sharpe_ratio(result.net_returns, periods_per_year=periods_per_year)
        trials.append(
            SensitivityTrial(strategy_id=strategy_id, params=point, net_sharpe=net_sharpe)
        )
        surface_index.append(tuple(point[name] for name in param_axes))
        surface_values.append(net_sharpe)
        if _neighbourhood_mask(param_axes, base_point, point):
            neighbourhood_sharpes.append(net_sharpe)

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
    )
