"""Tests for `paper/alpaca.py`.

Acceptance criterion 7: the paper-endpoint assertion is a PURE, OFFLINE unit
test (no network call is needed to check which URL a constructed client
resolved to - `test_constructor_rejects_a_resolved_non_paper_endpoint` below
fakes the underlying `alpaca-py` client entirely). The network-tier smoke
test (place + cancel one tiny order) is `@pytest.mark.network` and skips
cleanly without `ALPACA_API_KEY`/`ALPACA_SECRET_KEY` - no Alpaca keys exist
on this development machine, so it is expected to always skip here."""

from __future__ import annotations

import os

import pytest

from quantlab.core.errors import BrokerError, NotPaperAccountError

_HAS_ALPACA_KEYS = bool(os.environ.get("ALPACA_API_KEY")) and bool(
    os.environ.get("ALPACA_SECRET_KEY")
)


def test_constructor_raises_broker_error_without_credentials(monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)

    from quantlab.paper.alpaca import AlpacaPaperBroker

    with pytest.raises(BrokerError):
        AlpacaPaperBroker()


def test_constructor_rejects_a_resolved_non_paper_endpoint(monkeypatch):
    """Simulates a hypothetical future bug (this class always passes
    `paper=True` today) by faking `alpaca.trading.client.TradingClient`
    itself to resolve a LIVE endpoint - the constructor must refuse rather
    than proceed, with no network call involved."""
    monkeypatch.setenv("ALPACA_API_KEY", "fake-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "fake-secret")

    import alpaca.trading.client as alpaca_client_module
    from alpaca.common.enums import BaseURL

    class _FakeClientResolvingLive:
        def __init__(self, *args, **kwargs):
            self._base_url = BaseURL.TRADING_LIVE

    monkeypatch.setattr(alpaca_client_module, "TradingClient", _FakeClientResolvingLive)

    from quantlab.paper.alpaca import AlpacaPaperBroker

    with pytest.raises(NotPaperAccountError):
        AlpacaPaperBroker()


def test_constructor_accepts_a_resolved_paper_endpoint(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "fake-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "fake-secret")

    import alpaca.trading.client as alpaca_client_module
    from alpaca.common.enums import BaseURL

    class _FakeClientResolvingPaper:
        def __init__(self, *args, **kwargs):
            self._base_url = BaseURL.TRADING_PAPER

    monkeypatch.setattr(alpaca_client_module, "TradingClient", _FakeClientResolvingPaper)

    from quantlab.paper.alpaca import AlpacaPaperBroker

    broker = AlpacaPaperBroker()

    assert broker.capabilities().shorting is True


@pytest.mark.network
@pytest.mark.skipif(not _HAS_ALPACA_KEYS, reason="ALPACA_API_KEY/ALPACA_SECRET_KEY not set")
def test_place_and_cancel_one_tiny_order_on_the_real_paper_account():
    from quantlab.core.types import Order, OrderType, Side
    from quantlab.paper.alpaca import AlpacaPaperBroker
    from quantlab.paper.broker import OrderAck, client_order_id_for

    broker = AlpacaPaperBroker()
    order = Order(
        client_order_id=client_order_id_for("paper-smoke-test", "2024-01-15", "AAPL") + "-smoke",
        ticker="AAPL",
        side=Side.BUY,
        qty=0.001,
        order_type=OrderType.MARKET,
    )

    (result,) = broker.submit([order])

    if isinstance(result, OrderAck):
        assert result.status.value in {"ACCEPTED", "REJECTED", "DUPLICATE"}
    broker.cancel(order.client_order_id)
