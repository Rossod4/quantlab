"""`Ledger`: pure, deterministic cash + positions bookkeeping.

This is a SEPARATE track from engine.py's own gross/net return computation
(see engine.py's module docstring, "Two parallel tracks" section): the
Ledger produces genuine mark-to-market `PortfolioSnapshot`s (real compounding
of actual position values) for `BacktestResult.snapshots`, while the
reported `gross_returns`/`net_returns` series follow the old repo's ADDITIVE
cost convention (`gross - cost`, not `(1-cost)*(1+gross)-1`) for exact
1e-10 parity. The two agree to first order but are not bit-identical -
documented, not a bug.

No I/O, no provider access, no clock reads - every price the Ledger touches
is handed to it explicitly by the caller (engine.py).
"""

from __future__ import annotations

from quantlab.core.types import PortfolioSnapshot, Position, TargetWeights, normalize_timestamp


class Ledger:
    """Cash + positions for one backtest run.

    Weights are applied AS GIVEN (per work-packet instruction): a long-only
    `TargetWeights` summing to 1.0 invests all equity; a long-short book per
    M03's conventions (net 0, net 1.0 for 130/30, etc.) invests accordingly,
    with the un-invested fraction `1 - sum(weights)` sitting in cash. Cash
    earns 0 (CLAUDE.md-adjacent convention carried from the old repo's
    0%-risk-free-rate assumption) - this is a deliberate simplification: no
    margin/financing cost is charged on gross exposure above 100%, matching
    long_short_engine.py's documented Limitations.
    """

    def __init__(self, initial_capital: float):
        if not (initial_capital > 0):
            raise ValueError(f"initial_capital must be positive, got {initial_capital}")
        self._cash = float(initial_capital)
        self._qty: dict[str, float] = {}
        self._entry_price: dict[str, float] = {}

    @property
    def cash(self) -> float:
        return self._cash

    def holdings(self) -> dict[str, float]:
        """Current {ticker: qty}. A defensive copy - mutating it has no
        effect on the Ledger's own state."""
        return dict(self._qty)

    def entry_price(self, ticker: str) -> float:
        """The fill price this ticker's current position was entered at
        (its most recent `rebalance_to`'s fill price - avg_cost, since a
        position is always fully replaced rather than dollar-cost-averaged
        into). Raises `KeyError` if `ticker` is not currently held."""
        return self._entry_price[ticker]

    def equity(self, prices: dict[str, float]) -> float:
        """Cash plus the mark-to-market value of every currently-held
        position, using `prices`. Raises `KeyError` naming the ticker if a
        currently-held position has no price in `prices` - the caller
        (engine.py) is responsible for supplying one for every held ticker,
        settling (via `force_exit`) any that can no longer be priced first.
        """
        value = self._cash
        for ticker, qty in self._qty.items():
            if ticker not in prices:
                raise KeyError(
                    f"Ledger.equity: no price supplied for currently-held ticker {ticker!r}"
                )
            value += qty * prices[ticker]
        return value

    def snapshot(self, date: object, prices: dict[str, float]) -> PortfolioSnapshot:
        """A `PortfolioSnapshot` of the current state, marked at `prices`."""
        positions = {
            ticker: Position(ticker=ticker, qty=qty, avg_cost=self._entry_price[ticker])
            for ticker, qty in self._qty.items()
        }
        return PortfolioSnapshot(
            date=normalize_timestamp(date),
            cash=self._cash,
            positions=positions,
            equity=self.equity(prices),
        )

    def mark(self, date: object, prices: dict[str, float]) -> PortfolioSnapshot:
        """Read-only mark-to-market snapshot - identical to `snapshot`,
        named separately per the work packet's specified surface. Never
        mutates Ledger state."""
        return self.snapshot(date, prices)

    def rebalance_to(
        self,
        target: TargetWeights,
        fill_prices: dict[str, float],
        cost_fraction: float,
        mark_prices: dict[str, float] | None = None,
    ) -> None:
        """Replace the current book with `target`'s weights, priced at
        `fill_prices`, after deducting `cost_fraction` (a fraction of
        pre-trade equity) as a cash drag.

        `mark_prices` values the CURRENTLY HELD book (to compute equity
        BEFORE this rebalance's costs/trades) separately from `fill_prices`
        (which prices the NEW target book) - needed because a currently-held
        name that this period's extreme-return guard capped (engine.py) must
        be valued at its capped price for `equity_before`, even though, if
        re-selected, its FRESH entry uses the real market price. Defaults to
        `fill_prices` when omitted (no capping in effect: mark == fill for
        every currently-held name).

        Every ticker in `target.weights` must have a price in `fill_prices`;
        every currently-held ticker must have a price in `mark_prices` (or
        `fill_prices` if `mark_prices` is None) - `KeyError` otherwise (via
        `equity()`). Raises `ValueError` if `cost_fraction` is negative or
        any target fill price is non-positive.
        """
        if cost_fraction < 0:
            raise ValueError(f"cost_fraction must be >= 0, got {cost_fraction}")
        equity_before = self.equity(mark_prices if mark_prices is not None else fill_prices)
        equity_after_costs = equity_before * (1.0 - cost_fraction)

        new_qty: dict[str, float] = {}
        new_entry: dict[str, float] = {}
        invested = 0.0
        for ticker, weight in target.weights.items():
            if ticker not in fill_prices:
                raise KeyError(f"Ledger.rebalance_to: no fill price supplied for {ticker!r}")
            price = fill_prices[ticker]
            if not price > 0:
                raise ValueError(
                    f"Ledger.rebalance_to: non-positive fill price for {ticker!r}: {price}"
                )
            dollar = weight * equity_after_costs
            new_qty[ticker] = dollar / price
            new_entry[ticker] = price
            invested += dollar

        self._qty = new_qty
        self._entry_price = new_entry
        self._cash = equity_after_costs - invested

    def force_exit(self, ticker: str, last_price: float, haircut: float, reason: str) -> float:
        """Close `ticker`'s position immediately at `last_price * (1 -
        haircut)`, crediting the proceeds to cash - CLAUDE.md invariant #3:
        a delisting/forced exit is booked, never silently dropped.

        `reason` is caller-facing documentation only (e.g. "price_series_ended")
        and is not retained by the Ledger; the caller (engine.py) is
        responsible for counting/recording exits by reason in
        `BacktestResult.quality_flags`. Returns the cash proceeds credited.
        Raises `KeyError` if `ticker` is not currently held, `ValueError` if
        `haircut` is outside [0, 1] or `reason` is empty.
        """
        if ticker not in self._qty:
            raise KeyError(f"Ledger.force_exit: {ticker!r} is not currently held")
        if not (0.0 <= haircut <= 1.0):
            raise ValueError(f"haircut must be in [0, 1], got {haircut}")
        if not reason:
            raise ValueError("reason must be a non-empty string")
        qty = self._qty.pop(ticker)
        self._entry_price.pop(ticker, None)
        proceeds = qty * last_price * (1.0 - haircut)
        self._cash += proceeds
        return proceeds
