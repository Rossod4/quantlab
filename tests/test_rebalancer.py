"""Hand-computed cases for `paper/rebalancer.py`'s `plan_orders` - a pure
function, so every case here is checked against an exact expected quantity,
not merely "an order exists"."""

from __future__ import annotations

import pytest

from quantlab.core.types import Position, Side, TargetWeights
from quantlab.paper.broker import AccountSnapshot, BrokerCapabilities
from quantlab.paper.rebalancer import RebalancerConfig, plan_orders

_FRACTIONAL = BrokerCapabilities(fractional_shares=True, shorting=False, extended_hours=False)
_WHOLE_SHARE = BrokerCapabilities(fractional_shares=False, shorting=False, extended_hours=False)
_SHORT_OK = BrokerCapabilities(fractional_shares=True, shorting=True, extended_hours=False)


def _targets(weights: dict[str, float], strategy_id: str = "test-abc123") -> TargetWeights:
    return TargetWeights(asof="2024-01-15", weights=weights, strategy_id=strategy_id)


def test_buy_from_flat_uses_investable_equity_after_cash_buffer():
    account = AccountSnapshot(cash=100_000.0, equity=100_000.0, positions={})
    targets = _targets({"AAA": 0.5})
    config = RebalancerConfig(drift_band=0.0, cash_buffer=0.01)

    orders = plan_orders(targets, account, {"AAA": 100.0}, _FRACTIONAL, config)

    assert len(orders) == 1
    order = orders[0]
    assert order.side == Side.BUY
    assert order.ticker == "AAA"
    # target_dollars = 0.5 * (100_000 * 0.99) = 49_500 -> 495 shares
    assert order.qty == pytest.approx(495.0)


def test_drift_within_band_produces_no_order():
    positions = {"AAA": Position(ticker="AAA", qty=495.0, avg_cost=100.0)}
    account = AccountSnapshot(cash=50_500.0, equity=100_000.0, positions=positions)
    targets = _targets({"AAA": 0.5})
    config = RebalancerConfig(drift_band=0.005, cash_buffer=0.01)

    orders = plan_orders(targets, account, {"AAA": 100.0}, _FRACTIONAL, config)

    assert orders == []


def test_drift_just_outside_band_produces_an_order():
    # current_dollars = 495*100 = 49_500; target_dollars = 49_500 too, so
    # nudge the position away by more than the 0.5%-of-equity band.
    positions = {"AAA": Position(ticker="AAA", qty=400.0, avg_cost=100.0)}
    account = AccountSnapshot(cash=60_500.0, equity=100_000.0, positions=positions)
    targets = _targets({"AAA": 0.5})
    config = RebalancerConfig(drift_band=0.005, cash_buffer=0.01)

    orders = plan_orders(targets, account, {"AAA": 100.0}, _FRACTIONAL, config)

    assert len(orders) == 1
    assert orders[0].side == Side.BUY
    assert orders[0].qty == pytest.approx(95.0)


def test_whole_share_rounding_floors_fractional_quantity():
    account = AccountSnapshot(cash=1_000.0, equity=1_000.0, positions={})
    targets = _targets({"AAA": 1.0})
    config = RebalancerConfig(drift_band=0.0, cash_buffer=0.0)

    orders = plan_orders(targets, account, {"AAA": 33.0}, _WHOLE_SHARE, config)

    # 1000 / 33 = 30.30... -> floors to 30 whole shares.
    assert len(orders) == 1
    assert orders[0].qty == 30.0


def test_whole_share_rounding_to_zero_drops_the_order():
    account = AccountSnapshot(cash=1_000.0, equity=1_000.0, positions={})
    targets = _targets({"AAA": 0.001})
    config = RebalancerConfig(drift_band=0.0, cash_buffer=0.0)

    orders = plan_orders(targets, account, {"AAA": 500.0}, _WHOLE_SHARE, config)

    # target_dollars = 1.0 -> 1.0/500 = 0.002 shares -> floors to 0 -> dropped.
    assert orders == []


def test_cash_buffer_reduces_every_target_dollar_amount():
    account = AccountSnapshot(cash=100_000.0, equity=100_000.0, positions={})
    targets = _targets({"AAA": 1.0})
    config_no_buffer = RebalancerConfig(drift_band=0.0, cash_buffer=0.0)
    config_with_buffer = RebalancerConfig(drift_band=0.0, cash_buffer=0.10)

    no_buffer = plan_orders(targets, account, {"AAA": 100.0}, _FRACTIONAL, config_no_buffer)
    with_buffer = plan_orders(targets, account, {"AAA": 100.0}, _FRACTIONAL, config_with_buffer)

    assert no_buffer[0].qty == pytest.approx(1_000.0)
    assert with_buffer[0].qty == pytest.approx(900.0)


def test_no_short_guard_raises_on_negative_target_weight_for_a_no_short_broker():
    account = AccountSnapshot(cash=100_000.0, equity=100_000.0, positions={})
    targets = _targets({"AAA": -0.2})

    with pytest.raises(ValueError, match="no-short guard"):
        plan_orders(targets, account, {"AAA": 100.0}, _FRACTIONAL)


def test_negative_target_weight_is_fine_when_the_broker_can_short():
    account = AccountSnapshot(cash=100_000.0, equity=100_000.0, positions={})
    targets = _targets({"AAA": -0.2})
    config = RebalancerConfig(drift_band=0.0, cash_buffer=0.0)

    orders = plan_orders(targets, account, {"AAA": 100.0}, _SHORT_OK, config)

    assert len(orders) == 1
    assert orders[0].side == Side.SELL
    assert orders[0].qty == pytest.approx(200.0)


def test_dropped_ticker_is_fully_sold():
    positions = {"AAA": Position(ticker="AAA", qty=100.0, avg_cost=50.0)}
    account = AccountSnapshot(cash=95_000.0, equity=100_000.0, positions=positions)
    targets = _targets({})  # AAA no longer in the target book at all
    config = RebalancerConfig(drift_band=0.005, cash_buffer=0.0)

    orders = plan_orders(targets, account, {"AAA": 50.0}, _FRACTIONAL, config)

    assert len(orders) == 1
    assert orders[0].side == Side.SELL
    assert orders[0].qty == pytest.approx(100.0)


def test_max_order_notional_clips_a_large_order():
    account = AccountSnapshot(cash=100_000.0, equity=100_000.0, positions={})
    targets = _targets({"AAA": 1.0})
    config = RebalancerConfig(drift_band=0.0, cash_buffer=0.0, max_order_notional=10_000.0)

    orders = plan_orders(targets, account, {"AAA": 100.0}, _FRACTIONAL, config)

    assert len(orders) == 1
    # target dollars = 100_000 -> clipped to 10_000 -> 100 shares
    assert orders[0].qty == pytest.approx(100.0)


def test_sells_are_returned_before_buys():
    positions = {"AAA": Position(ticker="AAA", qty=1000.0, avg_cost=10.0)}
    account = AccountSnapshot(cash=90_000.0, equity=100_000.0, positions=positions)
    targets = _targets({"AAA": 0.0, "BBB": 0.5})
    config = RebalancerConfig(drift_band=0.0, cash_buffer=0.0)

    orders = plan_orders(targets, account, {"AAA": 10.0, "BBB": 20.0}, _FRACTIONAL, config)

    assert [o.side for o in orders] == [Side.SELL, Side.BUY]
    assert orders[0].ticker == "AAA"
    assert orders[1].ticker == "BBB"


def test_client_order_id_is_deterministic_from_strategy_id_asof_and_ticker():
    account = AccountSnapshot(cash=100_000.0, equity=100_000.0, positions={})
    targets = _targets({"AAA": 0.5}, strategy_id="momentum-1234567890")
    config = RebalancerConfig(drift_band=0.0, cash_buffer=0.0)

    first = plan_orders(targets, account, {"AAA": 100.0}, _FRACTIONAL, config)
    second = plan_orders(targets, account, {"AAA": 100.0}, _FRACTIONAL, config)

    assert first[0].client_order_id == second[0].client_order_id == "momentum-123-20240115-AAA"


def test_missing_price_for_a_ticker_needing_an_order_raises():
    account = AccountSnapshot(cash=100_000.0, equity=100_000.0, positions={})
    targets = _targets({"AAA": 0.5})

    with pytest.raises(ValueError, match="no price supplied"):
        plan_orders(targets, account, {}, _FRACTIONAL)
