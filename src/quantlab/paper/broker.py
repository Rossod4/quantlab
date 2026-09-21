"""`Broker`: the ABC every paper (and, in principle, live - though nothing in
this platform ever constructs one) trading adapter implements.

Every method below is deliberately narrow: a `Broker` is a dumb execution
surface, exactly like `data/interfaces.py`'s providers are dumb data
surfaces - `paper/rebalancer.py` decides WHAT to trade (a pure function),
`paper/runner.py` orchestrates WHEN, and this ABC only ever answers "what
does the account look like" / "do this order" / "is the market open".

## New types

`Order`, `Fill`, `Position` are the existing frozen pydantic models from
`core/types.py` (work packet's "Interfaces to honor" - reused unchanged, not
extended). `AccountSnapshot`, `BrokerCapabilities`, and `OrderAck` below are
NEW types this milestone introduces: they are paper-trading-specific (no
`backtest`/`validation` code needs them), so they live here rather than in
`core/types.py`, mirroring how `backtest/result.py`'s `QualityFlags` lives
next to the engine that produces it rather than in `core`.

## Idempotency

`Order.client_order_id` is the idempotency key for `submit()`: resubmitting
an order with a `client_order_id` a broker has already processed (accepted,
filled, partially filled, or rejected) must return the SAME outcome without
taking a second real-world action (no double fill, no double reject side
effect). This is what lets `paper/runner.py` safely retry a whole day's plan
(a crashed run, a scheduled-task double-fire) without risking a
double-traded book. `client_order_id_for()` below is the SAME scheme
`paper/rebalancer.py` uses to generate each `Order.client_order_id` in the
first place (mirroring the work packet's `paper/alpaca.py` section, but
shared across every broker so idempotency is consistent everywhere), so a
rerun of the same day's plan naturally reproduces the same ids - no broker
needs its own separate "have I already submitted this" ledger, only its own
`client_order_id`-keyed dedup.

## Errors

Typed in `core/errors.py`: `BrokerError` (adapter-level failure),
`ReconcileError` (raised by `paper/reconcile.py`, not this module),
`NotPaperAccountError` (raised by an adapter's constructor - see
`paper/alpaca.py`)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import pandas as pd

from quantlab.core.types import Fill, Order, Position


def client_order_id_for(strategy_id: str, asof: pd.Timestamp, ticker: str, attempt: int = 1) -> str:
    """The platform-wide client-order-id scheme: `f"{strategy_id[:12]}-
    {asof:%Y%m%d}-{ticker}"` for the first attempt at a given `(strategy_id,
    asof, ticker)`, with a `-a{attempt}` suffix for `attempt > 1`.
    Deterministic in its inputs alone - re-running the SAME day's plan for
    the SAME strategy at `attempt=1` always reproduces the SAME id, which is
    exactly what makes `paper/runner.py`'s "two consecutive runs, second is
    idempotent" acceptance criterion possible without any persisted "have I
    already submitted this order" state of its own: the BROKER's own
    idempotency (keyed on this id) does that job. `strategy_id[:12]` keeps
    the id short (most brokers, Alpaca included, cap `client_order_id`
    length) while still disambiguating strategies in practice (`strategy_id`
    is `{name}-{10 hex chars}` - see strategies/base.py - so 12 chars covers
    the name's first couple characters plus part of the hash, not the hash
    alone).

    `attempt` (quant-gate VERDICT.md M08 cycle-1 finding 4): a partially
    filled order can never be topped up under a client-order-id scheme with
    no way to express "this is a NEW order for the same day's remaining
    gap" - `paper/runner.py` cancels a prior attempt's resting remainder and
    resubmits any still-needed quantity under `attempt=N+1`, a genuinely
    DISTINCT id the broker has never seen, rather than replaying attempt 1's
    id (which a broker's own dedup would then treat as a duplicate of the
    ALREADY-SETTLED first attempt, per this function's own idempotency
    contract - see `paper/mock.py`'s `MockBroker.submit`)."""
    base = f"{strategy_id[:12]}-{asof:%Y%m%d}-{ticker}"
    return base if attempt <= 1 else f"{base}-a{attempt}"


class OrderAckStatus(StrEnum):
    """Every non-fill outcome `Broker.submit()` can report for one order.
    `ACCEPTED`: the broker took the order but has not (yet) reported a fill
    (e.g. `Trading212Broker`'s stub, or a real broker's queued-order state).
    `REJECTED`: the broker refused the order outright (bad symbol,
    insufficient buying power, market closed for a day-only order, etc).
    `DUPLICATE`: a resubmit of a `client_order_id` already processed -
    idempotent replay, not a new action.
    `CANCELED`: the order was open and has since been canceled (returned
    from `open_orders()`/`cancel()` bookkeeping, never from `submit()`
    itself)."""

    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    DUPLICATE = "DUPLICATE"
    CANCELED = "CANCELED"


@dataclass(frozen=True)
class OrderAck:
    """A `submit()` outcome that is NOT a `Fill` - see `OrderAckStatus`."""

    client_order_id: str
    ticker: str
    status: OrderAckStatus
    message: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": "OrderAck",
            "client_order_id": self.client_order_id,
            "ticker": self.ticker,
            "status": str(self.status),
            "message": self.message,
        }


@dataclass(frozen=True)
class BrokerCapabilities:
    """What a broker adapter can do - `paper/rebalancer.py`'s `plan_orders`
    reads this to decide lot rounding (`fractional_shares`) and whether a
    negative target weight is even expressible (`shorting`)."""

    fractional_shares: bool
    shorting: bool
    extended_hours: bool
    min_order_notional: float = 0.0

    def to_json(self) -> dict[str, Any]:
        return {
            "fractional_shares": self.fractional_shares,
            "shorting": self.shorting,
            "extended_hours": self.extended_hours,
            "min_order_notional": self.min_order_notional,
        }


@dataclass(frozen=True)
class AccountSnapshot:
    """A broker account's current state - `cash`/`equity` in the account's
    base currency, `positions` keyed by ticker using the existing
    `core.types.Position` model (work packet: "positions as
    core.types.Position")."""

    cash: float
    equity: float
    positions: dict[str, Position] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "cash": self.cash,
            "equity": self.equity,
            "positions": {t: p.model_dump(mode="json") for t, p in self.positions.items()},
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> AccountSnapshot:
        return cls(
            cash=float(data["cash"]),
            equity=float(data["equity"]),
            positions={t: Position.model_validate(p) for t, p in data.get("positions", {}).items()},
        )


class Broker(ABC):
    """One trading venue adapter. See module docstring for the contract
    every method below must uphold."""

    @abstractmethod
    def capabilities(self) -> BrokerCapabilities:
        """This broker/account's trading capabilities. Must be a pure
        function of the broker's own fixed configuration (never a function
        of the current account state) - `plan_orders` calls it once per
        rebalance and assumes it is stable within a run."""

    @abstractmethod
    def account(self) -> AccountSnapshot:
        """The account's current cash/equity/positions."""

    @abstractmethod
    def submit(self, orders: list[Order]) -> list[Fill | OrderAck]:
        """Submit `orders` and return one outcome per order, in the SAME
        order as `orders` - a `Fill` (full or partial - see `Fill.qty`
        against the originating `Order.qty`) or an `OrderAck` (accepted,
        rejected, or a `DUPLICATE` idempotent replay - see module
        docstring). Never raises for an ordinary per-order rejection (that
        is exactly what `OrderAckStatus.REJECTED` is for); `BrokerError` is
        reserved for an adapter-level failure (the whole call could not be
        made at all - network/auth/malformed request)."""

    @abstractmethod
    def open_orders(self) -> list[Order]:
        """Orders still open (unfilled or partially filled and not yet
        canceled)."""

    @abstractmethod
    def cancel(self, client_order_id: str) -> None:
        """Cancel the open order with this `client_order_id`, if any -
        canceling an order that is not open (already filled, already
        canceled, or never submitted) is a documented no-op, not an error,
        so a caller never needs to track order state itself before
        canceling."""

    @abstractmethod
    def is_market_open(self, asof: object) -> bool:
        """Whether the market this broker trades on is open on `asof`'s
        calendar date. This platform is EOD-only (CLAUDE.md) - `asof` is a
        date, never a timestamp-with-time-of-day, so this answers "is
        `asof` a trading session", not "is the market open RIGHT NOW"."""
