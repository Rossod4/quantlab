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

`Blend.requires()` declares the union of every child's `DataRequirements` -
a superset of (never narrower than) what each child individually declared -
which is what THIS strategy's own `ctx` (as handed to `generate_targets` by
a caller that builds exactly one context per strategy, e.g. a bare
`BlendStrategy` used directly in a test) is built from.

## Per-child context factory (M04 engine, carried from the M03 verdict -
plans/QUANT-NOTES.md "From M03 verdict": "a blend hands every child the SAME
ctx, built from the blend's UNION of DataRequirements ... a child that
over-reaches its own footprint raises UndeclaredDataError standalone but NOT
inside a blend")

Handing every child the SAME union-built `ctx` means a child that asks for
MORE than its OWN `requires()` declared - but no more than the union - never
raises `UndeclaredDataError`, silently defeating that guard under
composition (acceptance criterion 3 in the M03 packet no longer "survives"
being wrapped in a blend). `set_context_factory` below is the intentional,
additive M04 fix: the ENGINE (backtest/engine.py) calls it once per run with
a callable `DataRequirements -> PITDataContext` bound to the current
rebalance date, and `generate_targets`, when a factory has been set, builds
each child a FRESH context from that child's OWN `requires()` instead of
reusing the `ctx` argument at all - so a child's declaration is enforced
exactly as strictly composed as standalone. `ctx` is still accepted (and
used verbatim, matching the pre-M04 behavior) when no factory has been set,
so a bare `BlendStrategy` used directly (as in tests/test_blend.py) needs no
changes. A nested blend (a blend-of-blends) is propagated the SAME factory
via `set_context_factory` before its own `generate_targets` runs, so the
guard survives arbitrarily deep composition, not just one level.

## Canonical `strategy_id` (M03b, closing plans/state/M03/VERDICT.md item
4.8, carried to M06)

`Strategy.strategy_id` (base.py) by default hashes `self.params` verbatim,
which for a blend means the children's RAW config dicts as written in the
YAML - order-sensitive (swapping two children's order changes the hash for
an identical portfolio) and default-sensitive (omitting a child's default
param changes the hash even though the child's own validated `strategy_id`
is identical). Both defeat the M06 multiple-testing trials registry's job
of recognising a repeat blend. `BlendStrategy` overrides `strategy_id`
below to hash an order-insensitive, sorted list of `(child.strategy_id,
weight)` pairs instead - each child's own `strategy_id` is ALREADY stable
and default-insensitive (it hashes that child's validated pydantic dump,
not its raw YAML - see base.py), so building the blend id from those
inherits the same property, plus whatever the blend's own params contribute
(currently nothing beyond `children`).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
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

    def __init__(self, params: dict[str, Any] | None = None):
        super().__init__(params)
        # Set by the engine via `set_context_factory` - see module
        # docstring's "Per-child context factory" section. None means "no
        # factory bound yet": `generate_targets` falls back to handing every
        # child the SAME `ctx` it was itself called with (the pre-M04,
        # standalone-blend behavior every existing test relies on).
        self._context_factory: Callable[[DataRequirements], PITDataContext] | None = None
        # Lazily populated by `_children()` - params are frozen at
        # construction (base.py), so the child list never changes for a
        # given instance; caching it avoids reconstructing every child
        # (including recursively loading nested blends) on every
        # `_children()` call (M03b verdict carried item 9, perf-only, no
        # semantic change).
        self._children_cache: list[tuple[Strategy, float]] | None = None

    @classmethod
    def params_model(cls) -> type[BaseModel]:
        return BlendParams

    def set_context_factory(self, factory: Callable[[DataRequirements], PITDataContext]) -> None:
        """Bind the per-child context factory - see module docstring. The
        engine calls this once per run before the first `generate_targets`
        call; `factory` is expected to build a context bound to whatever
        rebalance date the engine is currently deciding for a given
        `DataRequirements`, via closure (backtest/engine.py's
        `context_factory`, not a change to this class's own signature)."""
        self._context_factory = factory

    @property
    def strategy_id(self) -> str:
        """Override of `Strategy.strategy_id` (base.py) - see this module's
        docstring's "Canonical strategy_id" section. Order-insensitive
        (children are sorted before hashing) and default-insensitive
        (built from each child's OWN `strategy_id`, not its raw config
        dict), while still changing whenever a weight, a child's own
        selection-affecting param, or a future non-`children` blend param
        changes."""
        own_params = {k: v for k, v in self.params.items() if k != "children"}
        child_pairs = sorted((child.strategy_id, weight) for child, weight in self._children())
        canonical = json.dumps({"own_params": own_params, "children": child_pairs}, sort_keys=True)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:10]
        return f"{self.name}-{digest}"

    def _children(self) -> list[tuple[Strategy, float]]:
        if self._children_cache is None:
            # Imported lazily to avoid a module-level import cycle with
            # quantlab.strategies.registry (which this package's __init__
            # populates by importing momentum/value/blend eagerly).
            from quantlab.strategies.registry import load_strategy

            p: BlendParams = self._params
            self._children_cache = [
                (load_strategy({"strategy": c.strategy, "params": c.params}), c.weight)
                for c in p.children
            ]
        return self._children_cache

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
        # M04b quant-gate VERDICT.md cycle 1 finding 3: the union of every
        # child's OWN `unscored` (a name a child could not score - never a
        # set-difference inference here either). A name unscored by more
        # than one child keeps the FIRST child's reason (children are
        # visited in their configured order) rather than concatenating -
        # this is a coarse per-rebalance flag, not a per-sleeve breakdown.
        unscored: dict[str, str] = {}
        for child, weight in self._children():
            if self._context_factory is not None:
                child_ctx = self._context_factory(child.requires())
                if isinstance(child, BlendStrategy):
                    child.set_context_factory(self._context_factory)
            else:
                child_ctx = ctx
            child_targets = child.generate_targets(child_ctx, date)
            for ticker, w in child_targets.weights.items():
                blended[ticker] = blended.get(ticker, 0.0) + weight * w
            for ticker, reason in child_targets.unscored.items():
                unscored.setdefault(ticker, reason)

        return TargetWeights(
            asof=date, weights=blended, strategy_id=self.strategy_id, unscored=unscored
        )
