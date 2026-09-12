"""`MockBroker`: an in-memory, deterministic `Broker` for tests and
`--dry-run`-adjacent development - never touches a network.

Fills happen at a caller-supplied price map (deterministic - no randomness,
per CLAUDE.md invariant #5), honours `Order.client_order_id` idempotency
(see `paper/broker.py`'s module docstring), and can be configured to
simulate a partial fill or an outright reject for specific tickers, so
`paper/rebalancer.py`/`paper/runner.py` tests can exercise both without a
real broker."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from quantlab.core.calendar import is_trading_day
from quantlab.core.types import Fill, Order, Position, Side, normalize_timestamp
from quantlab.paper.broker import (
    AccountSnapshot,
    Broker,
    BrokerCapabilities,
    OrderAck,
    OrderAckStatus,
)


@dataclass
class MockBroker(Broker):
    """See module docstring.

    `prices`: ticker -> fill price for THIS instance's lifetime (a fresh
    `MockBroker` per test/run - not meant to be reused across days with a
    stale price map).
    `partial_fill_fraction`: ticker -> fraction of the requested qty to
    actually fill (default 1.0 - full fill) - e.g. 0.5 fills half an order,
    leaving the rest as a still-open order (`open_orders()`).
    `reject_tickers`: orders for these tickers are rejected outright (no
    cash/position change).
    `commission_rate`: fraction of notional charged as commission on every
    fill (default 0.0)."""

    capabilities_: BrokerCapabilities
    prices: dict[str, float]
    cash: float = 100_000.0
    positions: dict[str, Position] = field(default_factory=dict)
    asof: pd.Timestamp = field(default_factory=lambda: normalize_timestamp(pd.Timestamp.now()))
    partial_fill_fraction: dict[str, float] = field(default_factory=dict)
    reject_tickers: set[str] = field(default_factory=set)
    commission_rate: float = 0.0

    def __post_init__(self) -> None:
        self.asof = normalize_timestamp(self.asof)
        # client_order_id -> the outcome it produced the FIRST time it was
        # seen - every later resubmit of the same id replays this unchanged
        # (idempotency - see paper/broker.py's module docstring).
        self._processed: dict[str, Fill | OrderAck] = {}
        # client_order_id -> the Order still open (a partial fill's
        # unfilled remainder never auto-completes; a reject/full-fill never
        # appears here at all).
        self._open: dict[str, Order] = {}

    # -- Broker ------------------------------------------------------------

    def capabilities(self) -> BrokerCapabilities:
        return self.capabilities_

    def account(self) -> AccountSnapshot:
        equity = self.cash + sum(
            pos.qty * self.prices.get(t, pos.avg_cost) for t, pos in self.positions.items()
        )
        return AccountSnapshot(cash=self.cash, equity=equity, positions=dict(self.positions))

    def submit(self, orders: list[Order]) -> list[Fill | OrderAck]:
        # quant-gate VERDICT.md M08 cycle-1 finding 4: a resubmitted
        # client_order_id ALWAYS surfaces as OrderAckStatus.DUPLICATE, never
        # a replayed `Fill` - a caller (paper/runner.py's journal) must be
        # able to tell "this run genuinely executed a trade" from "this run
        # asked again about an order already settled on a prior run", and a
        # verbatim replayed Fill is indistinguishable from a fresh one.
        results: list[Fill | OrderAck] = []
        for order in orders:
            if order.client_order_id in self._processed:
                cached = self._processed[order.client_order_id]
                results.append(
                    OrderAck(
                        order.client_order_id,
                        order.ticker,
                        OrderAckStatus.DUPLICATE,
                        f"duplicate of a prior {type(cached).__name__}",
                    )
                )
                continue
            results.append(self._process_new_order(order))
        return results

    def _process_new_order(self, order: Order) -> Fill | OrderAck:
        if order.ticker in self.reject_tickers:
            ack = OrderAck(
                order.client_order_id, order.ticker, OrderAckStatus.REJECTED, "rejected by fixture"
            )
            self._processed[order.client_order_id] = ack
            return ack

        if order.ticker not in self.prices:
            ack = OrderAck(
                order.client_order_id,
                order.ticker,
                OrderAckStatus.REJECTED,
                f"no price available for {order.ticker!r}",
            )
            self._processed[order.client_order_id] = ack
            return ack

        price = self.prices[order.ticker]
        fraction = self.partial_fill_fraction.get(order.ticker, 1.0)
        fill_qty = order.qty * fraction
        if fill_qty <= 0:
            ack = OrderAck(
                order.client_order_id, order.ticker, OrderAckStatus.REJECTED, "zero fill quantity"
            )
            self._processed[order.client_order_id] = ack
            return ack

        commission = fill_qty * price * self.commission_rate
        signed_qty = fill_qty if order.side == Side.BUY else -fill_qty
        self.cash += -signed_qty * price - commission
        existing = self.positions.get(order.ticker)
        new_qty = (existing.qty if existing else 0.0) + signed_qty
        if existing is None:
            avg_cost = price
        elif (existing.qty >= 0) == (signed_qty >= 0):
            # Adding to (or opening from flat into) the same side: a
            # notional-weighted average cost.
            total_cost = existing.qty * existing.avg_cost + signed_qty * price
            avg_cost = total_cost / new_qty if new_qty != 0 else price
        else:
            # Reducing/flipping a position: the cost basis of the SURVIVING
            # shares is unchanged; only a flip through zero resets it to the
            # new fill's price.
            avg_cost = existing.avg_cost if (existing.qty >= 0) == (new_qty >= 0) else price
        if new_qty == 0:
            self.positions.pop(order.ticker, None)
        else:
            self.positions[order.ticker] = Position(
                ticker=order.ticker, qty=new_qty, avg_cost=avg_cost
            )

        fill = Fill(
            client_order_id=order.client_order_id,
            ticker=order.ticker,
            qty=fill_qty,
            price=price,
            date=self.asof,
            commission=commission,
        )
        self._processed[order.client_order_id] = fill

        remainder = order.qty - fill_qty
        if remainder > 1e-9:
            self._open[order.client_order_id] = order.model_copy(update={"qty": remainder})
        return fill

    def open_orders(self) -> list[Order]:
        return list(self._open.values())

    def cancel(self, client_order_id: str) -> None:
        self._open.pop(client_order_id, None)

    def is_market_open(self, asof: object) -> bool:
        return is_trading_day(asof)
