"""Blend: a meta-strategy combining child strategies' `TargetWeights`.

Ports the WEIGHT-COMBINATION formula from
...\\MomentumValueStrategy\\src\\evaluation\\comparison.py's
`combine_strategies`/`blend_returns` - not the sweep (blend_sweep,
strategy_comparison_table), which is M05/M06 territory (out of scope). The
old function blended two RETURN series:

    blend_return = w * momentum_return + (1 - w) * value_return

applied fresh every quarter, i.e. "rebalanced back to target weights every
period" (see the old module's docstring on why - letting the split drift
would mean "a 50/50 portfolio" stops being 50/50). This module applies the
IDENTICAL linear-combination idea one level up the stack, to PORTFOLIO
WEIGHTS instead of realized returns - which is exactly what "rebalanced
back to target weights every period" means when you have the weights
directly instead of only their downstream returns:

    blended_weight[ticker] = sum(child.weight * child_targets.weights.get(ticker, 0)
                                  for child in children)

generalized from the old repo's fixed two-way `w` / `(1 - w)` split to N
children whose weights are validated to sum to 1.0 (the N=2,
weights-sum-to-1 case is exactly the old formula).

Every child strategy is called against the SAME `ctx` this strategy
receives - `Blend.requires()` declares the union of every child's
`DataRequirements`, which is a superset of (never narrower than) what each
child individually declared, so no child's own `ctx` calls can raise
`UndeclaredDataError` because of the union.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

from quantlab.core.types import TargetWeights, normalize_timestamp
from quantlab.data.requirements import DataRequirements
from quantlab.strategies.base import Strategy
from quantlab.strategies.registry import register_strategy

if TYPE_CHECKING:
    from quantlab.data.pit import PITDataContext

_WEIGHT_SUM_TOLERANCE = 1e-9


class BlendChildConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy: str
    params: dict[str, Any] = Field(default_factory=dict)
    weight: float


class BlendParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    children: list[BlendChildConfig] = Field(min_length=2)

    @model_validator(mode="after")
    def _check_weights_sum_to_one(self) -> BlendParams:
        total = sum(c.weight for c in self.children)
        if abs(total - 1.0) > _WEIGHT_SUM_TOLERANCE:
            raise ValueError(
                f"blend child weights must sum to 1.0 (the old repo's w / (1 - w) "
                f"convention, generalized to N children), got {total}"
            )
        return self


@register_strategy("blend")
class BlendStrategy(Strategy):
    """Weighted linear combination of child strategies' target weights -
    see module docstring."""

    @classmethod
    def params_model(cls) -> type[BaseModel]:
        return BlendParams

    def _children(self) -> list[tuple[Strategy, float]]:
        # Imported lazily to avoid a module-level import cycle with
        # quantlab.strategies.registry (which this package's __init__
        # populates by importing momentum/value/blend eagerly).
        from quantlab.strategies.registry import load_strategy

        p: BlendParams = self._params
        return [
            (load_strategy({"strategy": c.strategy, "params": c.params}), c.weight)
            for c in p.children
        ]

    def requires(self) -> DataRequirements:
        children = self._children()
        child_requirements = [s.requires() for s, _ in children]
        return DataRequirements(
            price_lookback_days=max((r.price_lookback_days for r in child_requirements), default=0),
            fundamental_fields=frozenset().union(
                *(r.fundamental_fields for r in child_requirements)
            )
            if child_requirements
            else frozenset(),
            needs_universe=any(r.needs_universe for r in child_requirements),
            needs_actions=any(r.needs_actions for r in child_requirements),
        )

    def generate_targets(self, ctx: PITDataContext, date: pd.Timestamp) -> TargetWeights:
        date = normalize_timestamp(date)
        blended: dict[str, float] = {}
        for child, weight in self._children():
            child_targets = child.generate_targets(ctx, date)
            for ticker, w in child_targets.weights.items():
                blended[ticker] = blended.get(ticker, 0.0) + weight * w

        return TargetWeights(asof=date, weights=blended, strategy_id=self.strategy_id)
