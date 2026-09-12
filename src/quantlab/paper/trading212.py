"""`Trading212Broker`: a contract-tested STUB, not a real implementation.

Trading212's public API (as of this milestone) has no order-placement
endpoint suitable for automated ISA/GIA trading, so a real implementation is
explicitly post-v1 (work packet's "Out of scope"). This class exists now so
`tests/test_broker_contract.py` can pin the `Broker` ABC against a SECOND
concrete shape (besides `MockBroker`) - every abstract method is
implementable for Trading212 in principle, so declaring the class here (with
loud `NotImplementedError` bodies) documents the account's real
capabilities today without pretending order execution works.

Capabilities are real, not stubbed: Trading212 ISAs support fractional
shares, forbid shorting, and are a no-margin cash/ISA account (no extended
hours, no margin-based capacity) - this is genuine, useful metadata even
before order execution is implemented."""

from __future__ import annotations

from quantlab.core.types import Fill, Order
from quantlab.paper.broker import AccountSnapshot, Broker, BrokerCapabilities, OrderAck

_NOT_IMPLEMENTED = (
    "Trading212Broker is a contract-tested STUB (work packet: 'Trading212 real "
    "implementation (post-v1)') - order execution is not implemented. Use "
    "MockBroker for testing or AlpacaPaperBroker for real paper trading."
)


class Trading212Broker(Broker):
    """See module docstring. `capabilities()` is the only implemented
    method; every other method raises `NotImplementedError`."""

    def capabilities(self) -> BrokerCapabilities:
        return BrokerCapabilities(
            fractional_shares=True,
            shorting=False,
            extended_hours=False,
            min_order_notional=1.0,
        )

    def account(self) -> AccountSnapshot:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    def submit(self, orders: list[Order]) -> list[Fill | OrderAck]:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    def open_orders(self) -> list[Order]:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    def cancel(self, client_order_id: str) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    def is_market_open(self, asof: object) -> bool:
        raise NotImplementedError(_NOT_IMPLEMENTED)
