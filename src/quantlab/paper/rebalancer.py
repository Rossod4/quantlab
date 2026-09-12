"""`plan_orders`: a PURE function from (targets, account, prices,
capabilities, config) to a list of `Order`s - no I/O, no broker calls, no
mutation of any argument. Exhaustively hand-tested (tests/test_rebalancer.py)
because everything downstream (idempotent submission, reconciliation,
the journal) trusts that this function's output is exactly reproducible from
its inputs alone.

## Algorithm

1. Reject up front (`ValueError`) if any target weight is negative and the
   broker cannot short (`capabilities.shorting is False`) - "a long-only
   strategy must never produce a sell below zero" (work packet). This check
   happens BEFORE any order is planned, so a violating strategy/broker
   pairing never silently produces a partial, wrong plan.
2. `investable_equity = account.equity * (1 - config.cash_buffer)` - the
   cash buffer is a HAIRCUT on the equity base every target dollar amount is
   computed from, not a separate reserved dollar figure, so it scales with
   the account automatically.
3. For every ticker in `targets.weights` UNION every ticker currently held
   (a name dropped from the target book must still be sold to zero):
   `target_dollars = targets.weights.get(ticker, 0.0) * investable_equity`;
   `current_dollars = current_qty * price`; `drift = (current_dollars -
   target_dollars) / account.equity` (a FRACTION OF TOTAL EQUITY, so the
   drift band threshold means what its docstring says regardless of the
   cash buffer). A ticker with `abs(drift) < config.drift_band` is skipped
   entirely (no order).
4. Lot rounding: `qty = abs(target_dollars - current_dollars) / price`,
   floored to a whole share when `not capabilities.fractional_shares` - an
   order that floors to exactly 0 shares is dropped (no point in it, and
   `core.types.Order` requires `qty > 0` anyway).
5. `config.max_order_notional` (if set) CLIPS (does not reject) an
   individual order's quantity down to that notional, so a single call
   never sends an order bigger than the cap - a target this far from a
   single-order fill needs more than one `run_once` cycle to reach, which is
   the intended, documented behavior for a strategy or account whose
   rebalance is unusually large relative to the cap.
6. Orders are returned SELLS FIRST, then BUYS (each group sorted by ticker
   for determinism) - a broker that processes the list in order frees sale
   proceeds before spending them, though nothing in this function itself
   depends on order execution order (it never touches account state).
7. `client_order_id` is generated via `paper.broker.client_order_id_for`
   from `(targets.strategy_id, targets.asof, ticker, attempt)` - see that
   function's docstring for why this makes a rerun of the same day's plan
   naturally idempotent at the broker, and how `attempt` lets a later
   `run_once` cycle top up a partial fill under a genuinely new id.
8. A ticker with a ZERO target (dropped from the book, or forced to zero by
   the caller - see `paper/runner.py`'s forced-exit handling for a held
   name with no available price) but a NONZERO held quantity needs NO price
   at all to exit: `qty = abs(current_qty)` directly, bypassing the
   price-based sizing/drift-band logic entirely (there is no meaningful
   "drift" to measure without a price, and a full exit-to-zero's quantity
   never depended on price in the first place - see step 3's algebra, which
   reduces to exactly this when `target_dollars == 0`). This is what lets a
   delisted/unpriceable HELD name still be sold to zero (CLAUDE.md
   invariant #3's paper-side counterpart) rather than raising - `plan_orders`
   only ever raises `ValueError` for a ticker with NO price that the caller
   still wants a NONZERO position in, which cannot be sized at all.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from quantlab.core.types import Order, OrderType, Side, TargetWeights
from quantlab.paper.broker import AccountSnapshot, BrokerCapabilities, client_order_id_for


@dataclass(frozen=True)
class RebalancerConfig:
    """`drift_band`/`cash_buffer` are fractions of total account equity
    (0.005 = 0.5%, matching the work packet's stated default for the drift
    band). `max_order_notional` (`None` = no cap) is in the account's base
    currency."""

    drift_band: float = 0.005
    cash_buffer: float = 0.01
    max_order_notional: float | None = None


def plan_orders(
    targets: TargetWeights,
    account: AccountSnapshot,
    prices: dict[str, float],
    capabilities: BrokerCapabilities,
    config: RebalancerConfig | None = None,
    attempt: int = 1,
) -> list[Order]:
    """See module docstring. Raises `ValueError` if a target weight is
    negative and `capabilities.shorting` is False, or if a ticker needing a
    NONZERO position has no entry in `prices` (a zero-target, currently-held
    ticker with no price is a full exit and needs none - step 8)."""
    cfg = config or RebalancerConfig()

    if not capabilities.shorting:
        shorts = {t: w for t, w in targets.weights.items() if w < 0}
        if shorts:
            raise ValueError(
                "plan_orders: no-short guard - target weight(s) "
                f"{shorts} are negative but this broker's capabilities() reports "
                "shorting=False; a long-only strategy/broker pairing must never be asked "
                "to sell below zero."
            )

    equity = account.equity
    investable_equity = equity * (1.0 - cfg.cash_buffer)

    current_qty = {t: p.qty for t, p in account.positions.items()}
    all_tickers = sorted(set(targets.weights) | set(current_qty))

    sells: list[Order] = []
    buys: list[Order] = []
    for ticker in all_tickers:
        target_dollars = targets.weights.get(ticker, 0.0) * investable_equity
        cur_qty = current_qty.get(ticker, 0.0)
        if ticker not in prices:
            if cur_qty == 0.0 and target_dollars == 0.0:
                continue
            if target_dollars == 0.0:
                # Full exit to zero needs no price at all (module docstring
                # step 8) - a delisted/unpriceable HELD name must still be
                # sellable to zero.
                side = Side.SELL if cur_qty > 0 else Side.BUY
                order = Order(
                    client_order_id=client_order_id_for(
                        targets.strategy_id, targets.asof, ticker, attempt
                    ),
                    ticker=ticker,
                    side=side,
                    qty=abs(cur_qty),
                    order_type=OrderType.MARKET,
                )
                (sells if side == Side.SELL else buys).append(order)
                continue
            raise ValueError(f"plan_orders: no price supplied for {ticker!r}")
        price = prices[ticker]
        current_dollars = cur_qty * price

        drift = (current_dollars - target_dollars) / equity if equity else 0.0
        if abs(drift) < cfg.drift_band:
            continue

        delta_dollars = target_dollars - current_dollars
        if cfg.max_order_notional is not None:
            capped = min(abs(delta_dollars), cfg.max_order_notional)
            delta_dollars = math.copysign(capped, delta_dollars)

        qty = abs(delta_dollars) / price
        if not capabilities.fractional_shares:
            qty = math.floor(qty)
        if qty <= 0:
            continue

        side = Side.BUY if delta_dollars > 0 else Side.SELL
        order = Order(
            client_order_id=client_order_id_for(targets.strategy_id, targets.asof, ticker, attempt),
            ticker=ticker,
            side=side,
            qty=float(qty),
            order_type=OrderType.MARKET,
        )
        (sells if side == Side.SELL else buys).append(order)

    return sells + buys
