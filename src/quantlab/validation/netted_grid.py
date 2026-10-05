"""Inputs for the walk-forward "ranking agreement under both cost
conventions" check (plans/M09-end-to-end.md carried item 7), assembled from
REAL engine runs rather than supplied as bare numbers.

Why this exists. `walk_forward_blend` ranks a blend-weight grid by blending
the children's NET returns (each sleeve already charged its own costs, so
offsetting trades across sleeves are charged twice). The engine instead costs
the NETTED book. `walk_forward_ranking_agreement` compares the two rankings
but needs one netted-book Sharpe per grid point; this module builds that dict
from saved `BacktestResult` directories and records, for every one of the
grid points, which run it came from.

The five grid points (for the default 2-child grid) come from:

- the one-hot endpoints (1, 0) and (0, 1): the standalone CHILD runs. A
  blend with weight 1.0 on one child targets exactly that child's weights, so
  the engine books the same trades and the same costs - the child run IS the
  netted-book result at that point. That equivalence only holds if the child
  run used the same window, rebalance frequency, execution mode and cost
  config as the blend run, so `_check_comparable` REFUSES (degrades to "not
  checked") when any of those differ.
- every interior point: a dedicated blend backtest at those weights
  (`--netted-grid-result "0.25,0.75=<dir>"`). Its `strategy_params` must carry
  exactly the claimed weights and the same child strategies/params as the
  headline blend, or the point is refused.

Window choice (deliberate): both conventions are measured on the
walk-forward's OUT-OF-SAMPLE window - exactly the dates over which
`WalkForwardResult.comparison` computes its per-grid-point "Sharpe Ratio"
(the stitched test blocks, i.e. after the first `train_years`). That is the
window the walk-forward conclusion is about, and it guarantees the two
rankings use the identical date index and annualisation
(`PERIODS_PER_YEAR[rebalance_freq]`, `sharpe_ratio` with rf=0, the same
function `standard_metrics` calls). The full-common-sample alternative would
mix 5 in-sample training years into one convention only and make the two
Sharpes non-comparable. The card states which window was used.

Nothing here raises: any missing or mismatched input yields an outcome with
`reason` set, which the report card renders as "not checked: <reason>".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd

from quantlab.core.paths import portable_path
from quantlab.validation.metrics import PERIODS_PER_YEAR, sharpe_ratio

if TYPE_CHECKING:
    from quantlab.backtest.result import BacktestResult
    from quantlab.validation.walk_forward import WalkForwardResult

_WEIGHT_TOL = 1e-9

# `provenance["backtest_config"]` keys that must match between the blend run
# and every run supplying a grid point: anything that changes the realised
# return series for the same targets.
_COMPARABLE_CONFIG_KEYS = (
    "start",
    "end",
    "rebalance_freq",
    "execution",
    "cost_model",
    "one_way_cost_bps",
    "borrow_fee_annual_bps",
    "delisting_haircut",
    "extreme_return_policy",
    "extreme_return_bound",
    "corwin_schultz_lookback_days",
)


_VINTAGE_KEYS = (
    "quantlab_git_sha",
    "dirty",
    "actions_cache_fetched_at",
    "fundamentals_cache_fetched_at",
    "quarantined_count",
)


def _vintage_mismatches(label: str, headline: BacktestResult, other: BacktestResult) -> list[str]:
    """Data/code vintage differences between the headline blend run and a run
    supplying a grid point. DISCLOSED, not refused: a child run from another
    code or cache state is still the same strategy on the same window, but a
    reader must be able to see that the five Sharpes do not share one vintage."""
    out = []
    for key in _VINTAGE_KEYS:
        h, o = headline.provenance.get(key), other.provenance.get(key)
        if h != o:
            out.append(f"{label}: {key} {o!r} vs the headline's {h!r}")
    return out


@dataclass
class NettedGridOutcome:
    """`sharpes`/`inputs`/`window` are set when every grid point resolved;
    otherwise `reason` says why the check was not run."""

    sharpes: dict[tuple[float, ...], float] | None = None
    inputs: list[dict[str, Any]] = field(default_factory=list)
    window: dict[str, Any] | None = None
    reason: str | None = None
    vintage_mismatches: list[str] = field(default_factory=list)


def parse_grid_spec(spec: str) -> tuple[tuple[float, ...], Path]:
    """`"0.25,0.75=reports/netted_grid/blend_25_75"` -> ((0.25, 0.75), Path).
    Raises ValueError on a malformed spec."""
    if "=" not in spec:
        raise ValueError(f"expected 'w1,w2,...=<dir>', got {spec!r}")
    weights_part, dir_part = spec.split("=", 1)
    weights = tuple(float(w) for w in weights_part.split(",") if w.strip())
    if not weights or not dir_part.strip():
        raise ValueError(f"expected 'w1,w2,...=<dir>', got {spec!r}")
    return weights, Path(dir_part.strip())


def _same_weights(a: tuple[float, ...], b: tuple[float, ...]) -> bool:
    return len(a) == len(b) and all(abs(x - y) <= _WEIGHT_TOL for x, y in zip(a, b, strict=True))


def _one_hot_index(weights: tuple[float, ...]) -> int | None:
    ones = [i for i, w in enumerate(weights) if abs(w - 1.0) <= _WEIGHT_TOL]
    zeros = [i for i, w in enumerate(weights) if abs(w) <= _WEIGHT_TOL]
    if len(ones) == 1 and len(zeros) == len(weights) - 1:
        return ones[0]
    return None


def _check_comparable(label: str, headline: BacktestResult, other: BacktestResult) -> str | None:
    h_cfg = headline.provenance.get("backtest_config", {})
    o_cfg = other.provenance.get("backtest_config", {})
    for key in _COMPARABLE_CONFIG_KEYS:
        if key not in h_cfg or key not in o_cfg:
            return f"{label}: backtest_config.{key} missing from provenance, cannot verify"
        if h_cfg[key] != o_cfg[key]:
            return (
                f"{label}: backtest_config.{key} differs from the headline blend run "
                f"({o_cfg[key]!r} vs {h_cfg[key]!r})"
            )
    h_ver = headline.provenance.get("data_semantics_version")
    o_ver = other.provenance.get("data_semantics_version")
    if h_ver != o_ver:
        return f"{label}: data_semantics_version differs ({o_ver!r} vs {h_ver!r})"
    return None


def _blend_children(result: BacktestResult) -> list[dict[str, Any]] | None:
    params = result.provenance.get("strategy_params")
    if not isinstance(params, dict):
        return None
    children = params.get("children")
    return children if isinstance(children, list) else None


def _family(result: BacktestResult) -> str:
    strategy_id = str(result.provenance.get("strategy_id", ""))
    return strategy_id.rsplit("-", 1)[0]


def _interior_point_problem(
    label: str, headline: BacktestResult, other: BacktestResult, weights: tuple[float, ...]
) -> str | None:
    h_children = _blend_children(headline)
    o_children = _blend_children(other)
    if h_children is None or o_children is None:
        return f"{label}: strategy_params.children missing from provenance, cannot verify weights"
    if len(h_children) != len(o_children) or len(o_children) != len(weights):
        return f"{label}: child count differs from the headline blend"
    for h, o, w in zip(h_children, o_children, weights, strict=True):
        if (h.get("strategy"), h.get("params")) != (o.get("strategy"), o.get("params")):
            return f"{label}: child strategy/params differ from the headline blend"
        if abs(float(o.get("weight", float("nan"))) - w) > _WEIGHT_TOL:
            return (
                f"{label}: run's own blend weights {[c.get('weight') for c in o_children]} do not "
                f"match the claimed {list(weights)}"
            )
    return None


def build_netted_book_grid(
    *,
    headline: BacktestResult,
    walk_forward: WalkForwardResult,
    weight_grid: list[tuple[float, ...]],
    child_results: list[BacktestResult],
    child_dirs: list[Path],
    grid_specs: list[tuple[tuple[float, ...], Path]],
) -> NettedGridOutcome:
    """Resolve one netted-book Sharpe per `weight_grid` point (module
    docstring). Never raises; see `NettedGridOutcome.reason`."""
    from quantlab.backtest.result import BacktestResult

    if not grid_specs:
        return NettedGridOutcome(
            reason="no --netted-grid-result supplied (the interior grid points need "
            "dedicated blend backtests)"
        )
    if len(child_results) != len(child_dirs) or not child_results:
        return NettedGridOutcome(reason="child sleeve results not supplied (--child-result)")

    try:
        loaded_specs: list[tuple[tuple[float, ...], Path, BacktestResult]] = []
        for weights, directory in grid_specs:
            loaded_specs.append((weights, directory, BacktestResult.load(directory)))
    except Exception as exc:  # noqa: BLE001 - degrade, never crash --full
        return NettedGridOutcome(reason=f"could not load a netted-grid result: {exc}")

    oos_dates = walk_forward.oos_returns.index
    ppy = PERIODS_PER_YEAR.get(headline.provenance.get("backtest_config", {}).get("rebalance_freq"))
    if ppy is None:
        return NettedGridOutcome(reason="headline rebalance_freq unknown, cannot annualise")

    sharpes: dict[tuple[float, ...], float] = {}
    inputs: list[dict[str, Any]] = []
    vintage: list[str] = []
    for weights in weight_grid:
        weights = tuple(weights)
        label = f"grid point {list(weights)}"
        hot = _one_hot_index(weights)
        if hot is not None:
            if hot >= len(child_results):
                return NettedGridOutcome(reason=f"{label}: no child result at index {hot}")
            source, directory, kind = child_results[hot], child_dirs[hot], "standalone child run"
            problem = _check_comparable(f"{label} ({directory.name})", headline, source)
            if problem is None:
                h_children = _blend_children(headline)
                if h_children is not None and hot < len(h_children):
                    expected = h_children[hot].get("strategy")
                    if expected and _family(source) != str(expected):
                        problem = (
                            f"{label} ({directory.name}): strategy {_family(source)!r} is not the "
                            f"headline blend's child {expected!r}"
                        )
                    own = source.provenance.get("strategy_params")
                    for key, want in (
                        (h_children[hot].get("params") or {}).items() if problem is None else ()
                    ):
                        if not isinstance(own, dict) or key not in own:
                            problem = (
                                f"{label} ({directory.name}): strategy param {key} missing from "
                                "the child run's provenance, cannot verify it matches the blend's "
                                "child"
                            )
                            break
                        if own[key] != want:
                            problem = (
                                f"{label} ({directory.name}): strategy param {key}="
                                f"{own[key]!r} differs from the blend's child ({want!r})"
                            )
                            break
        else:
            match = [(d, r) for w, d, r in loaded_specs if _same_weights(w, weights)]
            if not match:
                return NettedGridOutcome(
                    reason=f"{label}: no --netted-grid-result supplied for these weights"
                )
            directory, source = match[0]
            kind = "netted blend backtest"
            problem = _check_comparable(f"{label} ({directory.name})", headline, source)
            if problem is None:
                problem = _interior_point_problem(
                    f"{label} ({directory.name})", headline, source, weights
                )
        if problem is not None:
            return NettedGridOutcome(reason=problem)

        returns = source.net_returns
        if not oos_dates.isin(returns.index).all():
            return NettedGridOutcome(
                reason=f"{label} ({directory.name}): net returns do not cover the walk-forward "
                "out-of-sample window"
            )
        value = float(sharpe_ratio(returns.loc[oos_dates], 0.0, ppy))
        sharpes[weights] = value
        vintage.extend(_vintage_mismatches(f"{label} ({directory.name})", headline, source))
        inputs.append(
            {
                "weights": list(weights),
                "source": kind,
                "run_dir": portable_path(directory),
                "strategy_id": source.provenance.get("strategy_id"),
                "net_sharpe_oos": value,
            }
        )

    window = {
        "kind": "walk-forward out-of-sample window",
        "start": str(pd.Timestamp(oos_dates.min()).date()),
        "end": str(pd.Timestamp(oos_dates.max()).date()),
        "n_periods": int(len(oos_dates)),
        "periods_per_year": ppy,
    }
    return NettedGridOutcome(
        sharpes=sharpes, inputs=inputs, window=window, vintage_mismatches=vintage
    )
