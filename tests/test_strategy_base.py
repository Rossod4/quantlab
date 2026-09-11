"""Tests for the `Strategy` ABC contract itself (strategies/base.py):
strategy_id stability, purity, and the declare-vs-use gate. Uses a tiny
test-only `Strategy` subclass rather than any real plugin, so these tests
stay generic to the ABC contract - see test_momentum_strategy.py /
test_value_strategy.py / test_blend.py for the real plugins' own tests.
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


class _FakePriceProvider(PriceProvider):
    def __init__(self, panel: pd.DataFrame):
        self._panel = panel

    def get_prices(self, tickers: list[str], start: object, end: object) -> pd.DataFrame:
        return self._panel[self._panel["ticker"].isin(tickers)].copy()


class _FakeConstituentsProvider(ConstituentsProvider):
    def __init__(self, tickers: list[str]):
        self._tickers = tickers

    def membership(self, asof: object) -> list[str]:
        return list(self._tickers)

    def membership_history(self, start: object, end: object) -> pd.DataFrame:
        raise NotImplementedError


class _FakeFundamentalsProvider(FundamentalsProvider):
    def get_pit_fundamentals(self, ticker: str, asof: object) -> dict:
        return {}


class _FakeCorporateActionsProvider(CorporateActionsProvider):
    def get_actions(self, ticker: str, start: object, end: object) -> pd.DataFrame:
        df = pd.DataFrame(columns=["ticker", "action_type", "value"])
        df.index = pd.DatetimeIndex([], name="date")
        return df


def _price_panel(dates: pd.DatetimeIndex, ticker: str = "AAA") -> pd.DataFrame:
    n = len(dates)
    return pd.DataFrame(
        {
            "ticker": [ticker] * n,
            "open": [100.0] * n,
            "high": [101.0] * n,
            "low": [99.0] * n,
            "close": [100.0] * n,
            "adj_close": [100.0] * n,
            "volume": [1000] * n,
        },
        index=dates,
    )


def _context(
    asof, requirements: DataRequirements, panel: pd.DataFrame | None = None
) -> PITDataContext:
    if panel is None:
        panel = _price_panel(pd.bdate_range("2020-01-01", "2020-03-31"))
    return PITDataContext(
        asof=asof,
        requirements=requirements,
        price_provider=_FakePriceProvider(panel),
        constituents_provider=_FakeConstituentsProvider(["AAA"]),
        fundamentals_provider=_FakeFundamentalsProvider(),
        corporate_actions_provider=_FakeCorporateActionsProvider(),
    )


class _EchoParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    lookback_days: int = 1


class _EchoStrategy(Strategy):
    """Deterministic, stateless test strategy: always returns 100% AAA."""

    name = "test-echo"

    @classmethod
    def params_model(cls) -> type[BaseModel]:
        return _EchoParams

    def requires(self) -> DataRequirements:
        return DataRequirements(price_lookback_days=self._params.lookback_days)

    def generate_targets(self, ctx: PITDataContext, date) -> TargetWeights:
        ctx.prices(["AAA"], self._params.lookback_days)  # honors its own declaration
        return TargetWeights(asof=date, weights={"AAA": 1.0}, strategy_id=self.strategy_id)


class _OverreachingStrategy(Strategy):
    """Deliberately under-declares: requires() promises 1 day of lookback
    but generate_targets asks ctx for far more - acceptance criterion 3."""

    name = "test-overreach"

    @classmethod
    def params_model(cls) -> type[BaseModel]:
        return _EchoParams

    def requires(self) -> DataRequirements:
        return DataRequirements(price_lookback_days=1)

    def generate_targets(self, ctx: PITDataContext, date) -> TargetWeights:
        ctx.prices(["AAA"], 999)  # exceeds the 1-day declaration above
        return TargetWeights(asof=date, weights={"AAA": 1.0}, strategy_id=self.strategy_id)


# -- strategy_id --------------------------------------------------------------


def test_strategy_id_stable_for_same_params():
    a = _EchoStrategy({"lookback_days": 5})
    b = _EchoStrategy({"lookback_days": 5})
    assert a.strategy_id == b.strategy_id


def test_strategy_id_changes_with_params():
    a = _EchoStrategy({"lookback_days": 5})
    b = _EchoStrategy({"lookback_days": 6})
    assert a.strategy_id != b.strategy_id


def test_strategy_id_includes_registered_name():
    strat = _EchoStrategy({"lookback_days": 5})
    assert strat.strategy_id.startswith("test-echo-")


# -- declare-vs-use gate (acceptance criterion 3) ----------------------------


def test_overreaching_strategy_raises_undeclared_data_error():
    strat = _OverreachingStrategy({})
    ctx = _context("2020-03-15", strat.requires())
    with pytest.raises(UndeclaredDataError):
        strat.generate_targets(ctx, "2020-03-15")


def test_well_declared_strategy_does_not_raise():
    strat = _EchoStrategy({"lookback_days": 5})
    ctx = _context("2020-03-15", strat.requires())
    strat.generate_targets(ctx, "2020-03-15")  # no raise


# -- purity (acceptance criterion 4) -----------------------------------------


def test_generate_targets_is_pure_same_ctx_and_params_same_result():
    strat = _EchoStrategy({"lookback_days": 5})
    ctx = _context("2020-03-15", strat.requires())

    first = strat.generate_targets(ctx, "2020-03-15")
    second = strat.generate_targets(ctx, "2020-03-15")

    assert first == second


def test_generate_targets_does_not_mutate_params():
    strat = _EchoStrategy({"lookback_days": 5})
    ctx = _context("2020-03-15", strat.requires())
    before = dict(strat.params)

    strat.generate_targets(ctx, "2020-03-15")

    assert strat.params == before
