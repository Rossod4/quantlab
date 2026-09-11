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

from quantlab.core.errors import UndeclaredDataError
from quantlab.core.types import TargetWeights
from quantlab.data.interfaces import (
    ConstituentsProvider,
    CorporateActionsProvider,
    FundamentalsProvider,
    PriceProvider,
)
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


# -- per-child context factory (M03 verdict carried item 6 / REVIEW.md
# finding 3) --------------------------------------------------------------
#
# Real `PITDataContext`s (not `_no_op_ctx()`) are needed here: the whole
# point is exercising REAL `UndeclaredDataError` enforcement, which only a
# genuine `PITDataContext` performs.


class _FakePriceProvider(PriceProvider):
    def __init__(self, panel: pd.DataFrame):
        self._panel = panel

    def get_prices(self, tickers: list[str], start: object, end: object) -> pd.DataFrame:
        return self._panel[self._panel["ticker"].isin(tickers)].copy()


class _FakeConstituentsProvider(ConstituentsProvider):
    def membership(self, asof: object) -> list[str]:
        return ["AAA"]

    def membership_history(self, start: object, end: object) -> pd.DataFrame:
        raise NotImplementedError


class _NoOpFundamentalsProvider(FundamentalsProvider):
    def get_pit_fundamentals(self, ticker: str, asof: object) -> dict:
        return {}


class _EmptyActionsProvider(CorporateActionsProvider):
    def get_actions(self, ticker: str, start: object, end: object) -> pd.DataFrame:
        df = pd.DataFrame(columns=["ticker", "action_type", "value"])
        df.index = pd.DatetimeIndex([], name="date")
        return df


def _price_panel_for(dates: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ticker": ["AAA"] * len(dates),
            "open": [10.0] * len(dates),
            "high": [10.0] * len(dates),
            "low": [10.0] * len(dates),
            "close": [10.0] * len(dates),
            "adj_close": [10.0] * len(dates),
            "volume": [1000] * len(dates),
        },
        index=dates,
    )


_PANEL = _price_panel_for(pd.bdate_range("2021-01-01", "2021-04-30"))


def _real_context_factory(requirements: DataRequirements) -> PITDataContext:
    """A real `context_factory` (the same callable shape backtest/engine.py
    hands to `BlendStrategy.set_context_factory`), so `UndeclaredDataError`
    is genuinely enforced per the `DataRequirements` it's called with."""
    return PITDataContext(
        asof=ASOF,
        requirements=requirements,
        price_provider=_FakePriceProvider(_PANEL),
        constituents_provider=_FakeConstituentsProvider(),
        fundamentals_provider=_NoOpFundamentalsProvider(),
        corporate_actions_provider=_EmptyActionsProvider(),
    )


class _DeclareOnlyParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    price_lookback_days: int = 0


@register_strategy("blend-test-declare-only")
class _DeclareOnlyStrategy(Strategy):
    """Declares a configurable `price_lookback_days` but never touches
    `ctx` - purely for asserting what `DataRequirements` a context was
    built from, with no risk of `UndeclaredDataError` noise."""

    @classmethod
    def params_model(cls) -> type[BaseModel]:
        return _DeclareOnlyParams

    def requires(self) -> DataRequirements:
        return DataRequirements(price_lookback_days=self._params.price_lookback_days)

    def generate_targets(self, ctx: PITDataContext, date) -> TargetWeights:
        return TargetWeights(asof=date, weights={}, strategy_id=self.strategy_id)


class _OverreachParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


@register_strategy("blend-test-overreach")
class _OverreachingStrategy(Strategy):
    """Declares `price_lookback_days=1` but actually calls `ctx.prices()`
    for 5 - the fixture for proving the per-child context factory's
    UndeclaredDataError-survives-composition property. Standalone, this
    strategy always raises; the point is whether it ALSO raises once
    wrapped in a blend."""

    @classmethod
    def params_model(cls) -> type[BaseModel]:
        return _OverreachParams

    def requires(self) -> DataRequirements:
        return DataRequirements(price_lookback_days=1)

    def generate_targets(self, ctx: PITDataContext, date) -> TargetWeights:
        ctx.prices(["AAA"], 5)  # deliberately over-reaches its own declared 1
        return TargetWeights(asof=date, weights={}, strategy_id=self.strategy_id)


def _overreach_blend_config() -> dict:
    # The companion child declares a BIGGER lookback (10), so the blend's
    # UNION requirements (price_lookback_days=10) would silently mask the
    # overreaching child's own under-declaration if it were ever handed
    # that shared union context instead of one built from its own requires().
    return _blend_config(
        ("blend-test-declare-only", {"price_lookback_days": 10}, 0.5),
        ("blend-test-overreach", {}, 0.5),
    )


def test_overreaching_child_does_not_raise_without_the_factory_reproducing_the_bug():
    """Demonstrates the bug the mechanism fixes (QUANT-NOTES.md "From M03
    verdict": "a child that over-reaches its own footprint raises
    UndeclaredDataError standalone but NOT inside a blend"): with NO
    `set_context_factory` call, the blend falls back to handing every
    child the SAME union-built ctx (pre-M04 behavior), and the union's
    bigger `price_lookback_days=10` masks the overreaching child's own
    declared limit of 1."""
    from quantlab.strategies.registry import load_strategy

    blend = load_strategy(_overreach_blend_config())
    union_ctx = _real_context_factory(blend.requires())

    blend.generate_targets(union_ctx, ASOF)  # must NOT raise - the bug


def test_overreaching_child_raises_undeclared_data_error_when_factory_is_wired():
    """With the factory wired (as backtest/engine.py always does), the
    overreaching child gets a context built from its OWN `requires()`
    (price_lookback_days=1), so its `ctx.prices(["AAA"], 5)` call genuinely
    raises - the guard survives composition."""
    from quantlab.strategies.registry import load_strategy

    blend = load_strategy(_overreach_blend_config())
    blend.set_context_factory(_real_context_factory)
    union_ctx = _real_context_factory(blend.requires())

    with pytest.raises(UndeclaredDataError):
        blend.generate_targets(union_ctx, ASOF)


def test_each_child_receives_a_context_built_from_its_own_requires_not_the_union():
    """Spy on the factory's arguments: each child must be called with ITS
    OWN `requires()`, never the blend's union - proven directly rather than
    only inferred from the overreach test's pass/fail."""
    from quantlab.strategies.registry import load_strategy

    recorded: list[DataRequirements] = []

    def spy_factory(requirements: DataRequirements) -> PITDataContext:
        recorded.append(requirements)
        return _real_context_factory(requirements)

    blend = load_strategy(
        _blend_config(
            ("blend-test-declare-only", {"price_lookback_days": 3}, 0.5),
            ("blend-test-declare-only", {"price_lookback_days": 7}, 0.5),
        )
    )
    blend.set_context_factory(spy_factory)

    blend.generate_targets(_real_context_factory(blend.requires()), ASOF)

    assert recorded == [
        DataRequirements(price_lookback_days=3),
        DataRequirements(price_lookback_days=7),
    ]
    assert blend.requires().price_lookback_days == 7  # the union - neither child got THIS


def test_nested_blend_propagates_the_context_factory_to_grandchildren():
    """A blend-of-blends: the outer blend must propagate its factory to an
    inner `BlendStrategy` child (via `set_context_factory` before that
    child's own `generate_targets` runs), so the guard survives arbitrarily
    deep composition, not just one level."""
    from quantlab.strategies.registry import load_strategy

    inner_config = _overreach_blend_config()
    outer = load_strategy(
        {
            "strategy": "blend",
            "params": {
                "children": [
                    {"strategy": "blend", "params": inner_config["params"], "weight": 0.5},
                    {
                        "strategy": "blend-test-echo",
                        "params": {"weights": {"ZZZ": 1.0}},
                        "weight": 0.5,
                    },
                ]
            },
        }
    )
    outer.set_context_factory(_real_context_factory)
    union_ctx = _real_context_factory(outer.requires())

    with pytest.raises(UndeclaredDataError):
        outer.generate_targets(union_ctx, ASOF)


def test_nested_blend_without_factory_propagation_would_not_raise():
    """Mirror of the outer-level bug-reproduction test, one level down: the
    inner blend, used WITHOUT the factory ever being propagated to it,
    falls back to its own union ctx and masks the same overreach - proving
    the nested test above is exercising real propagation, not something
    that would pass regardless."""
    from quantlab.strategies.registry import load_strategy

    inner = load_strategy(_overreach_blend_config())
    union_ctx = _real_context_factory(inner.requires())

    inner.generate_targets(union_ctx, ASOF)  # must NOT raise - no factory set
