"""Tests for strategies/blend.py's `BlendStrategy` weight-combination glue.

Uses a tiny registered test-only child strategy (`EchoWeightStrategy`) that
just echoes a fixed weights dict from its params, rather than the real
momentum/value plugins - keeps this file's fixtures independent of theirs
and isolates the arithmetic under test (the linear combination itself,
ported from the old repo's `combine_strategies`/`blend_returns` - see
strategies/blend.py's module docstring) from any of their data-fetching
concerns.
"""

from __future__ import annotations

import pandas as pd
import pytest
from pydantic import BaseModel, ConfigDict

from quantlab.core.types import TargetWeights
from quantlab.data.pit import PITDataContext
from quantlab.data.requirements import DataRequirements
from quantlab.strategies.base import Strategy
from quantlab.strategies.blend import BlendStrategy
from quantlab.strategies.registry import register_strategy

ASOF = pd.Timestamp("2021-04-30")


class _EchoWeightParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    weights: dict[str, float]
    # A default (selection-affecting-if-changed) param, purely so
    # test_strategy_id_is_order_insensitive_and_default_insensitive below
    # has a child param that can be omitted vs. written out explicitly -
    # default 1.0 leaves every OTHER test in this file's weight arithmetic
    # unaffected.
    multiplier: float = 1.0


@register_strategy("blend-test-echo")
class EchoWeightStrategy(Strategy):
    """Test-only strategy: ignores `ctx` and just returns `params.weights`
    scaled by `params.multiplier`."""

    @classmethod
    def params_model(cls) -> type[BaseModel]:
        return _EchoWeightParams

    def requires(self) -> DataRequirements:
        return DataRequirements()

    def generate_targets(self, ctx: PITDataContext, date) -> TargetWeights:
        weights = {k: v * self._params.multiplier for k, v in self._params.weights.items()}
        return TargetWeights(asof=date, weights=weights, strategy_id=self.strategy_id)


def _no_op_ctx() -> PITDataContext:
    """No child in these tests ever calls `ctx`, so an object satisfying
    the interface with unreachable methods is enough."""

    class _Unreachable:
        def __getattr__(self, name):
            raise AssertionError(f"unexpected ctx.{name}() call in a blend test")

    return _Unreachable()  # type: ignore[return-value]


def _blend_config(*children: tuple[str, dict, float]) -> dict:
    return {
        "strategy": "blend",
        "params": {
            "children": [
                {"strategy": name, "params": params, "weight": weight}
                for name, params, weight in children
            ]
        },
    }


# -- weight combination --------------------------------------------------


def test_fifty_fifty_blend_combines_disjoint_weights():
    from quantlab.strategies.registry import load_strategy

    blend = load_strategy(
        _blend_config(
            ("blend-test-echo", {"weights": {"AAA": 1.0}}, 0.5),
            ("blend-test-echo", {"weights": {"BBB": 1.0}}, 0.5),
        )
    )
    result = blend.generate_targets(_no_op_ctx(), ASOF)
    assert result.weights == pytest.approx({"AAA": 0.5, "BBB": 0.5}, abs=1e-9)


def test_blend_sums_overlapping_ticker_weights():
    from quantlab.strategies.registry import load_strategy

    blend = load_strategy(
        _blend_config(
            ("blend-test-echo", {"weights": {"AAA": 1.0}}, 0.6),
            ("blend-test-echo", {"weights": {"AAA": 0.5, "BBB": 0.5}}, 0.4),
        )
    )
    result = blend.generate_targets(_no_op_ctx(), ASOF)
    # AAA: 0.6*1.0 + 0.4*0.5 = 0.8 ; BBB: 0.4*0.5 = 0.2
    assert result.weights == pytest.approx({"AAA": 0.8, "BBB": 0.2}, abs=1e-9)


def test_weights_not_summing_to_one_is_rejected():
    with pytest.raises(ValueError, match="sum to 1.0"):
        BlendStrategy(
            {
                "children": [
                    {
                        "strategy": "blend-test-echo",
                        "params": {"weights": {"AAA": 1.0}},
                        "weight": 0.5,
                    },
                    {
                        "strategy": "blend-test-echo",
                        "params": {"weights": {"BBB": 1.0}},
                        "weight": 0.4,
                    },
                ]
            }
        )


def test_requires_less_than_two_children_is_rejected():
    with pytest.raises(ValueError):
        BlendStrategy(
            {
                "children": [
                    {
                        "strategy": "blend-test-echo",
                        "params": {"weights": {"AAA": 1.0}},
                        "weight": 1.0,
                    },
                ]
            }
        )


# -- requires() union ----------------------------------------------------


def test_requires_is_union_of_children_requirements():
    from quantlab.strategies.registry import load_strategy

    blend = load_strategy(
        _blend_config(
            ("blend-test-echo", {"weights": {"AAA": 1.0}}, 0.5),
            ("blend-test-echo", {"weights": {"BBB": 1.0}}, 0.5),
        )
    )
    # Both children declare an empty DataRequirements(); the union must
    # still be a valid, empty DataRequirements() rather than raising.
    requirements = blend.requires()
    assert requirements.price_lookback_days == 0
    assert requirements.needs_universe is False


# -- purity & strategy_id --------------------------------------------------


def test_generate_targets_is_pure():
    from quantlab.strategies.registry import load_strategy

    blend = load_strategy(
        _blend_config(
            ("blend-test-echo", {"weights": {"AAA": 1.0}}, 0.5),
            ("blend-test-echo", {"weights": {"BBB": 1.0}}, 0.5),
        )
    )
    assert blend.generate_targets(_no_op_ctx(), ASOF) == blend.generate_targets(_no_op_ctx(), ASOF)


def test_strategy_id_changes_when_a_child_weight_changes():
    from quantlab.strategies.registry import load_strategy

    a = load_strategy(
        _blend_config(
            ("blend-test-echo", {"weights": {"AAA": 1.0}}, 0.5),
            ("blend-test-echo", {"weights": {"BBB": 1.0}}, 0.5),
        )
    )
    b = load_strategy(
        _blend_config(
            ("blend-test-echo", {"weights": {"AAA": 1.0}}, 0.6),
            ("blend-test-echo", {"weights": {"BBB": 1.0}}, 0.4),
        )
    )
    assert a.strategy_id != b.strategy_id


# -- strategy_id canonicalization (M03b, closing plans/state/M03/VERDICT.md
# item 4.8, carried to M06) --------------------------------------------------


def test_strategy_id_is_order_insensitive():
    """Swapping the order of two children with an otherwise identical
    portfolio must give the SAME blend strategy_id - VERDICT.md 4.8's first
    over-counting hazard for the M06 trials registry."""
    from quantlab.strategies.registry import load_strategy

    order_a = load_strategy(
        _blend_config(
            ("blend-test-echo", {"weights": {"AAA": 1.0}}, 0.5),
            ("blend-test-echo", {"weights": {"BBB": 1.0}}, 0.5),
        )
    )
    order_b = load_strategy(
        _blend_config(
            ("blend-test-echo", {"weights": {"BBB": 1.0}}, 0.5),
            ("blend-test-echo", {"weights": {"AAA": 1.0}}, 0.5),
        )
    )
    assert order_a.strategy_id == order_b.strategy_id


def test_strategy_id_is_insensitive_to_a_child_omitting_its_default_param():
    """Omitting a child's default param vs. writing it out explicitly must
    give the SAME blend strategy_id, since the child's own strategy_id is
    already identical either way (base.py hashes the validated pydantic
    dump, not the raw YAML) - VERDICT.md 4.8's second over-counting hazard."""
    from quantlab.strategies.registry import load_strategy

    omitted_default = load_strategy(
        _blend_config(
            ("blend-test-echo", {"weights": {"AAA": 1.0}}, 0.5),
            ("blend-test-echo", {"weights": {"BBB": 1.0}}, 0.5),
        )
    )
    explicit_default = load_strategy(
        _blend_config(
            ("blend-test-echo", {"weights": {"AAA": 1.0}, "multiplier": 1.0}, 0.5),
            ("blend-test-echo", {"weights": {"BBB": 1.0}}, 0.5),
        )
    )
    assert omitted_default.strategy_id == explicit_default.strategy_id


def test_strategy_id_changes_when_a_child_param_changes():
    """A child param change that changes the CHILD's own strategy_id must
    still change the blend's id, even though the canonicalization no longer
    hashes the child's raw config dict directly."""
    from quantlab.strategies.registry import load_strategy

    a = load_strategy(
        _blend_config(
            ("blend-test-echo", {"weights": {"AAA": 1.0}, "multiplier": 1.0}, 0.5),
            ("blend-test-echo", {"weights": {"BBB": 1.0}}, 0.5),
        )
    )
    b = load_strategy(
        _blend_config(
            ("blend-test-echo", {"weights": {"AAA": 1.0}, "multiplier": 2.0}, 0.5),
            ("blend-test-echo", {"weights": {"BBB": 1.0}}, 0.5),
        )
    )
    assert a.strategy_id != b.strategy_id
