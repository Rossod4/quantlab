"""Contract tests for the `Broker` ABC, parametrized over `MockBroker` and
`Trading212Broker` (and `AlpacaPaperBroker` when `ALPACA_API_KEY`/
`ALPACA_SECRET_KEY` are set - see tests/test_alpaca_broker.py's network-tier
tests for that one specifically, which exercise submit/account/etc; this
file's Alpaca parametrization only pins the offline-safe parts of the
contract - `capabilities()` and construction)."""

from __future__ import annotations

import os

import pytest

from quantlab.core.types import Fill, Order, OrderType, Side
from quantlab.paper.broker import BrokerCapabilities, OrderAck, OrderAckStatus
from quantlab.paper.mock import MockBroker
from quantlab.paper.trading212 import Trading212Broker

_HAS_ALPACA_KEYS = bool(os.environ.get("ALPACA_API_KEY")) and bool(
    os.environ.get("ALPACA_SECRET_KEY")
)


def _mock_broker() -> MockBroker:
    return MockBroker(
        capabilities_=BrokerCapabilities(
            fractional_shares=True, shorting=False, extended_hours=False
        ),
        prices={"AAA": 100.0},
        cash=10_000.0,
        asof="2024-01-15",
    )


@pytest.fixture(params=["mock", "trading212"])
def broker(request):
    if request.param == "mock":
        return _mock_broker()
    return Trading212Broker()


def test_capabilities_returns_a_broker_capabilities_instance(broker):
    caps = broker.capabilities()

    assert isinstance(caps, BrokerCapabilities)
    assert isinstance(caps.fractional_shares, bool)
    assert isinstance(caps.shorting, bool)


def test_trading212_capabilities_are_a_no_margin_isa():
    caps = Trading212Broker().capabilities()

    assert caps.fractional_shares is True
    assert caps.shorting is False


def test_trading212_every_other_method_raises_not_implemented():
    broker = Trading212Broker()
    order = Order(
        client_order_id="x", ticker="AAA", side=Side.BUY, qty=1.0, order_type=OrderType.MARKET
    )

    with pytest.raises(NotImplementedError):
        broker.account()
    with pytest.raises(NotImplementedError):
        broker.submit([order])
    with pytest.raises(NotImplementedError):
        broker.open_orders()
    with pytest.raises(NotImplementedError):
        broker.cancel("x")
    with pytest.raises(NotImplementedError):
        broker.is_market_open("2024-01-15")


def test_mock_broker_account_reflects_cash_and_positions():
    broker = _mock_broker()

    account = broker.account()

    assert account.cash == 10_000.0
    assert account.equity == 10_000.0
    assert account.positions == {}


def test_mock_broker_submit_fills_and_updates_account():
    broker = _mock_broker()
    order = Order(
        client_order_id="cid-1", ticker="AAA", side=Side.BUY, qty=10.0, order_type=OrderType.MARKET
    )

    results = broker.submit([order])

    assert len(results) == 1
    fill = results[0]
    assert fill.qty == 10.0
    assert fill.price == 100.0
    account = broker.account()
    assert account.cash == pytest.approx(9_000.0)
    assert account.positions["AAA"].qty == 10.0


def test_mock_broker_resubmitting_the_same_client_order_id_is_idempotent():
    """Account state is unchanged by a resubmit (idempotency), and the
    resubmit's own result is a `DUPLICATE` ack, never a replayed `Fill`
    (quant-gate VERDICT.md M08 cycle-1 finding 4: a caller must be able to
    tell a genuine execution from a replay of an already-settled order)."""
    broker = _mock_broker()
    order = Order(
        client_order_id="cid-1", ticker="AAA", side=Side.BUY, qty=10.0, order_type=OrderType.MARKET
    )

    (first,) = broker.submit([order])
    account_after_first = broker.account()
    (second,) = broker.submit([order])
    account_after_second = broker.account()

    assert isinstance(first, Fill)
    assert isinstance(second, OrderAck)
    assert second.status == OrderAckStatus.DUPLICATE
    assert account_after_first == account_after_second


def test_mock_broker_partial_fill_leaves_the_remainder_open():
    broker = MockBroker(
        capabilities_=BrokerCapabilities(True, False, False),
        prices={"AAA": 100.0},
        cash=10_000.0,
        asof="2024-01-15",
        partial_fill_fraction={"AAA": 0.5},
    )
    order = Order(
        client_order_id="cid-1", ticker="AAA", side=Side.BUY, qty=10.0, order_type=OrderType.MARKET
    )

    (fill,) = broker.submit([order])

    assert fill.qty == 5.0
    open_orders = broker.open_orders()
    assert len(open_orders) == 1
    assert open_orders[0].qty == 5.0


def test_mock_broker_reject_ticker_produces_an_ack_with_no_account_change():
    broker = MockBroker(
        capabilities_=BrokerCapabilities(True, False, False),
        prices={"AAA": 100.0},
        cash=10_000.0,
        asof="2024-01-15",
        reject_tickers={"AAA"},
    )
    order = Order(
        client_order_id="cid-1", ticker="AAA", side=Side.BUY, qty=10.0, order_type=OrderType.MARKET
    )

    (result,) = broker.submit([order])

    assert isinstance(result, OrderAck)
    assert result.status == OrderAckStatus.REJECTED
    assert broker.account().cash == 10_000.0


def test_mock_broker_cancel_removes_an_open_order():
    broker = MockBroker(
        capabilities_=BrokerCapabilities(True, False, False),
        prices={"AAA": 100.0},
        cash=10_000.0,
        asof="2024-01-15",
        partial_fill_fraction={"AAA": 0.5},
    )
    order = Order(
        client_order_id="cid-1", ticker="AAA", side=Side.BUY, qty=10.0, order_type=OrderType.MARKET
    )
    broker.submit([order])
    assert len(broker.open_orders()) == 1

    broker.cancel("cid-1")

    assert broker.open_orders() == []


def test_mock_broker_is_market_open_matches_the_nyse_calendar():
    broker = _mock_broker()

    assert broker.is_market_open("2024-01-16") is True  # a Tuesday
    assert broker.is_market_open("2024-01-13") is False  # a Saturday


@pytest.mark.network
@pytest.mark.skipif(not _HAS_ALPACA_KEYS, reason="ALPACA_API_KEY/ALPACA_SECRET_KEY not set")
def test_alpaca_broker_capabilities_when_keys_present():
    from quantlab.paper.alpaca import AlpacaPaperBroker

    broker = AlpacaPaperBroker()

    caps = broker.capabilities()
    assert isinstance(caps, BrokerCapabilities)
