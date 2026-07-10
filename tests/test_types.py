from __future__ import annotations

import math

import pandas as pd
import pytest
from pydantic import ValidationError

from quantlab.core.types import (
    Bar,
    DelistingEvent,
    DelistingReason,
    Fill,
    Order,
    OrderType,
    PortfolioSnapshot,
    Position,
    Side,
    TargetWeights,
)


def _bar(**overrides: object) -> Bar:
    fields: dict[str, object] = {
        "date": "2024-01-02",
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.5,
        "adj_close": 100.5,
        "volume": 1_000,
    }
    fields.update(overrides)
    return Bar(**fields)


def test_bar_normalizes_date_to_midnight() -> None:
    bar = _bar(date="2024-01-02 15:30:00")
    assert bar.date == pd.Timestamp("2024-01-02")


def test_bar_is_immutable() -> None:
    bar = _bar()
    with pytest.raises(ValidationError):
        bar.close = 999.0  # type: ignore[misc]


def test_target_weights_nan_raises() -> None:
    with pytest.raises(ValidationError):
        TargetWeights(asof="2024-01-02", weights={"AAPL": math.nan}, strategy_id="s1")


def test_target_weights_inf_raises() -> None:
    with pytest.raises(ValidationError):
        TargetWeights(asof="2024-01-02", weights={"AAPL": math.inf}, strategy_id="s1")


def test_target_weights_valid() -> None:
    tw = TargetWeights(asof="2024-01-02", weights={"AAPL": 0.5, "MSFT": 0.5}, strategy_id="s1")
    assert tw.weights == {"AAPL": 0.5, "MSFT": 0.5}
    assert tw.asof == pd.Timestamp("2024-01-02")


def test_target_weights_is_immutable() -> None:
    tw = TargetWeights(asof="2024-01-02", weights={"AAPL": 1.0}, strategy_id="s1")
    with pytest.raises(ValidationError):
        tw.strategy_id = "other"  # type: ignore[misc]


def test_order_roundtrip_and_immutable() -> None:
    order = Order(
        client_order_id="o1",
        ticker="AAPL",
        side=Side.BUY,
        qty=10,
        order_type=OrderType.MARKET,
    )
    assert order.side is Side.BUY
    with pytest.raises(ValidationError):
        order.qty = 20  # type: ignore[misc]


def test_order_nonpositive_qty_raises() -> None:
    with pytest.raises(ValidationError):
        Order(
            client_order_id="o1",
            ticker="AAPL",
            side=Side.BUY,
            qty=0,
            order_type=OrderType.MARKET,
        )


def test_fill_roundtrip_and_immutable() -> None:
    fill = Fill(
        client_order_id="o1",
        ticker="AAPL",
        qty=10,
        price=100.0,
        date="2024-01-02",
        commission=1.0,
    )
    assert fill.date == pd.Timestamp("2024-01-02")
    with pytest.raises(ValidationError):
        fill.price = 200.0  # type: ignore[misc]


def test_fill_negative_commission_raises() -> None:
    with pytest.raises(ValidationError):
        Fill(
            client_order_id="o1",
            ticker="AAPL",
            qty=10,
            price=100.0,
            date="2024-01-02",
            commission=-1.0,
        )


def test_position_is_immutable() -> None:
    pos = Position(ticker="AAPL", qty=10, avg_cost=100.0)
    with pytest.raises(ValidationError):
        pos.qty = 20  # type: ignore[misc]


def test_portfolio_snapshot_is_immutable() -> None:
    pos = Position(ticker="AAPL", qty=10, avg_cost=100.0)
    snap = PortfolioSnapshot(date="2024-01-02", cash=1000.0, positions={"AAPL": pos}, equity=2000.0)
    assert snap.positions["AAPL"].ticker == "AAPL"
    with pytest.raises(ValidationError):
        snap.cash = 0.0  # type: ignore[misc]


def test_delisting_event_is_immutable() -> None:
    event = DelistingEvent(
        ticker="XYZ", last_trade_date="2024-01-02", reason=DelistingReason.BANKRUPTCY
    )
    assert event.reason is DelistingReason.BANKRUPTCY
    with pytest.raises(ValidationError):
        event.ticker = "ABC"  # type: ignore[misc]
