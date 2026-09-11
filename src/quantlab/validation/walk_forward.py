"""Walk-forward test of a blend-weight choice, generalized from the old
repo's two-sleeve `walk_forward_blend` (..\\MomentumValueStrategy\\src\\
evaluation\\walk_forward.py) to N child return series via an explicit
`weight_grid: list[tuple[float, ...]]`. The 2-sleeve grid reproduces the old
result exactly - see tests/parity/test_walk_forward_parity.py.

Why this exists (from the old module's docstring, condensed): every result
in the old project was measured on one fixed window, and the choice of the
"best" momentum/value blend weight was read off a full-sample table - a
form of fitting. This module asks, honestly, whether that choice survives
being made out-of-sample: at each step, the best weight in a small grid is
picked using ONLY a rolling training window, then applied to the following
unseen test window, and the stitched-together test returns are then
genuinely out-of-sample for the weight choice.

IMPORTANT - this module's blend convention is the OLD one, not M04's:
`walk_forward_blend` blends each child's NET RETURN SERIES
(`weight[i] * child_net_returns[i]`, summed), exactly like the old repo's
`combine_strategies`/`blend_returns`. `quantlab.strategies.blend.
BlendStrategy` (M04) instead blends TARGET WEIGHTS and then nets costs on
the already-blended book (QUANT-NOTES.md "From M03 verdict" item 2 /
M04 verdict item 8) - a deliberately different, and NOT interchangeable,
number. The two conventions disagree whenever turnover/borrow are nonlinear
in weights, which they generally are. This module keeps the OLD
return-blend convention deliberately: a walk-forward over blend WEIGHT
CHOICE is asking "how stable is picking a weight from trailing data", not
"what does the netted-cost book return" - the weight-choice question is
answered correctly by re-mixing each sleeve's OWN net returns at each
candidate weight, which is exactly what the old convention does. Do not use
this module's `oos_returns` as a substitute for a real M04 blend backtest's
`net_returns`.

Training criterion, grid coarseness, and rolling (not expanding) training
window are all carried over unchanged from the old module - see its
docstring for the full argument for each.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import reduce
from typing import Any

import pandas as pd

from quantlab.validation.metrics import sharpe_ratio, standard_metrics

QUARTERS_PER_YEAR = 4
_WEIGHT_SUM_TOLERANCE = 1e-9


def compound_to(returns: pd.Series, freq: str) -> pd.Series:
    """Compound periodic returns into a coarser frequency (a pandas offset
    alias, e.g. "QE" quarterly, "ME" monthly, "YE" annual). Generalizes the
    old repo's `compound_to_quarterly` (comparison.py); growing at r1, then
    r2, ... over a bucket turns $1 into the product of (1 + r_i), so the
    bucket's return is that product minus 1. Nothing is approximated when
    the target frequency's boundaries coincide with the input's own dates
    (e.g. monthly input compounded to quarterly, since quarter-ends are
    month-ends)."""
    return (1 + returns).resample(freq).prod() - 1


def compound_to_quarterly(monthly_returns: pd.Series) -> pd.Series:
    """Ported verbatim (as `compound_to(returns, "QE")`) from the old
    repo's `comparison.compound_to_quarterly` - kept as a named function for
    parity-test familiarity and because "quarterly" is this module's own
    working frequency by default."""
    return compound_to(monthly_returns, "QE")


@dataclass
class WalkForwardResult:
    """Everything `walk_forward_blend` produces, generalized to N children.

    oos_returns:    the stitched out-of-sample returns - each period's
                    return came from a weight tuple chosen WITHOUT seeing
                    that period (or anything after it).
    chosen_weights: DataFrame indexed by the first test-period date of each
                    step, one column per child (`child_labels`), holding the
                    weight tuple picked at that step. For the legacy 2-sleeve
                    case with `weight_grid=[(w, 1-w), ...]`, column 0 is
                    exactly the old repo's scalar `chosen_weights` momentum
                    weight - see tests/parity/test_walk_forward_parity.py.
    comparison:     metrics table over the SAME out-of-sample window for the
                    walk-forward portfolio and every fixed grid point, so the
                    walk-forward result has an apples-to-apples baseline.
    child_labels:   the child series' labels, in `weight_grid` column order.
    """

    oos_returns: pd.Series
    chosen_weights: pd.DataFrame
    comparison: pd.DataFrame
    child_labels: tuple[str, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "child_labels": list(self.child_labels),
            "oos_returns": {str(d.date()): v for d, v in self.oos_returns.items()},
            "chosen_weights": {
                str(d.date()): row.tolist() for d, row in self.chosen_weights.iterrows()
            },
            "comparison": self.comparison.to_dict(orient="index"),
        }


def _blend(children: list[pd.Series], weights: tuple[float, ...]) -> pd.Series:
    total = children[0] * weights[0]
    for child, w in zip(children[1:], weights[1:], strict=True):
        total = total + child * w
    return total


def walk_forward_blend(
    child_returns: list[pd.Series],
    weight_grid: list[tuple[float, ...]],
    train_years: int = 5,
    test_years: int = 1,
    periods_per_year: int = QUARTERS_PER_YEAR,
    risk_free_rate: float = 0.0,
    child_labels: tuple[str, ...] | None = None,
) -> WalkForwardResult:
    """Walk-forward test of an N-child blend-weight choice.

    Mechanics (identical to the old repo's, generalized to N children):
    align every child series to their common dates, then repeat

        train  = the `train_years` * periods_per_year periods before the test block
        choose = the weight tuple in `weight_grid` with the highest training Sharpe
        test   = apply that tuple to the next `test_years` * periods_per_year periods

    stepping forward one test-block at a time, and stitch all the test
    blocks into one out-of-sample series. The final (possibly partial) test
    block is kept - real time doesn't arrive in tidy multiples of the test
    length, and dropping the tail would quietly discard the most recent
    data.

    All `child_returns` must already be at the SAME frequency implied by
    `periods_per_year` (pass momentum through `compound_to_quarterly`/
    `compound_to` first if blending against a quarterly value series, as the
    old repo did) - taking pre-aligned-frequency input, rather than
    resampling internally, keeps this function's job single and testable.

    Each `weight_grid` entry must have `len(child_returns)` weights summing
    to 1.0 (same tolerance as `strategies/blend.py`'s `BlendParams`).
    """
    if len(child_returns) < 1:
        raise ValueError("need at least one child return series")
    for weights in weight_grid:
        if len(weights) != len(child_returns):
            raise ValueError(
                f"weight_grid entry {weights!r} has {len(weights)} weights, "
                f"expected {len(child_returns)} (one per child series)"
            )
        total = sum(weights)
        if abs(total - 1.0) > _WEIGHT_SUM_TOLERANCE:
            raise ValueError(f"weight_grid entry {weights!r} sums to {total}, expected 1.0")

    labels = child_labels or tuple(f"sleeve_{i}" for i in range(len(child_returns)))

    common = reduce(lambda a, b: a.intersection(b), (s.index for s in child_returns))
    aligned = [s.loc[common] for s in child_returns]

    train_len = train_years * periods_per_year
    test_len = test_years * periods_per_year
    if len(common) < train_len + 1:
        raise ValueError(
            f"Need more than {train_len} common periods ({train_years} training "
            f"years at {periods_per_year}/year) to run at least one walk-forward "
            f"step; got {len(common)}."
        )

    oos_chunks = []
    chosen: dict[pd.Timestamp, tuple[float, ...]] = {}
    for test_start in range(train_len, len(common), test_len):
        train_slice = slice(test_start - train_len, test_start)
        test_slice = slice(test_start, min(test_start + test_len, len(common)))

        # Pick the grid weight tuple with the best TRAINING-window Sharpe.
        # Ties go to the first tuple in the grid.
        best_weights, best_sharpe = None, None
        for weights in weight_grid:
            train_returns = _blend([s.iloc[train_slice] for s in aligned], weights)
            s = sharpe_ratio(train_returns, risk_free_rate, periods_per_year)
            if best_sharpe is None or s > best_sharpe:
                best_weights, best_sharpe = weights, s

        test_returns = _blend([s.iloc[test_slice] for s in aligned], best_weights)
        chosen[common[test_start]] = best_weights
        oos_chunks.append(test_returns)

    oos_returns = pd.concat(oos_chunks)
    chosen_weights = pd.DataFrame.from_dict(chosen, orient="index", columns=list(labels))
    chosen_weights = chosen_weights.sort_index()

    # Baselines over the SAME out-of-sample window: every fixed grid point,
    # so "did adapting the weight beat just picking one and holding it?" is
    # directly answerable.
    oos_dates = oos_returns.index
    columns = {"Walk-Forward": standard_metrics(oos_returns, periods_per_year, risk_free_rate)}
    for weights in weight_grid:
        fixed = _blend([s.loc[oos_dates] for s in aligned], weights)
        parts = (f"{w:.0%} {name}" for w, name in zip(weights, labels, strict=True))
        label = "Fixed " + "/".join(parts)
        columns[label] = standard_metrics(fixed, periods_per_year, risk_free_rate)
    comparison = pd.DataFrame(columns)

    return WalkForwardResult(
        oos_returns=oos_returns,
        chosen_weights=chosen_weights,
        comparison=comparison,
        child_labels=labels,
    )
