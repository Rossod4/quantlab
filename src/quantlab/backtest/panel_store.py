"""`PricePanelStore`: a run-level, in-memory price panel (M04b work packet
item 4).

## Why this exists

Before this module, every `PITDataContext` (data/pit.py) - a FRESH one is
built for every rebalance's decision, and again internally for every
accounting/settlement/benchmark fetch (backtest/engine.py's
`_accounting_context`) - called `PriceProvider.get_prices()` independently.
For an already-cached ticker this is "only" a parquet re-read plus a sidecar
JSON read (data/cache.py), not a network call, but across a real ~170-month
2012-2026 run - several hundred tickers, several accounting call sites per
rebalance, ~170 rebalances - that is tens of thousands of redundant disk
reads for data that never changes within one run (measured contribution to
the 463s profile in plans/M04b-engine-perf.md, alongside the ~150 uncached
delisted names this milestone's negative price cache separately fixes).

`PricePanelStore.build()` fetches the FULL universe (every point-in-time
constituent over the whole backtest window, plus the benchmark) ONCE via the
provider (itself still cache-backed, so this is parquet reads plus at most
one network fetch per never-before-seen ticker) into one in-memory
long-format panel. `PITDataContext` gains an optional `panel_store`
constructor kwarg (default `None`, meaning "call the provider" - see that
module) that, when present, slices FROM THIS IN-MEMORY PANEL instead.

## Untrusted, exactly like a provider

Nothing in this module checks any row's date against any `asof`.
`PITDataContext._sliced_price_panel` hard-slices whatever `get_prices()`
returns (`<= last_session`, then `_assert_no_future_dates`) and this is
UNCHANGED regardless of whether that frame came from a real provider or this
store - a hostile/corrupted store entry (a row dated after `asof`) is caught
by the exact same defense-in-depth this module never weakens or bypasses
(M04b acceptance criterion 6). This class does not need to, and must not,
duplicate that guard.

## Missing tickers fall back to the provider

A ticker never loaded into the store (outside the declared universe, or a
strategy that never declares `needs_universe` at all) is fetched directly
from the provider, per the M04b work packet's own wording - uncached inside
this store (a rare path in the real run this milestone targets; see
backtest/engine.py's module docstring for how `run_backtest` sizes the
store's own preload window so this path is not the common one)."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from quantlab.data.interfaces import PriceProvider

_PANEL_COLUMNS = ["ticker", "open", "high", "low", "close", "adj_close", "volume"]


def _empty_panel() -> pd.DataFrame:
    empty = pd.DataFrame(columns=_PANEL_COLUMNS)
    empty.index = pd.DatetimeIndex([], name="date")
    return empty


@dataclass
class PricePanelStore:
    """See module docstring. `get_prices` mirrors `PriceProvider`'s own
    signature exactly (same argument names, same long-format return shape)
    so a caller cannot tell the difference - and must not need to, since the
    caller's own hard-slice-then-assert is what actually enforces the
    no-look-ahead guarantee, not this class."""

    _panel: pd.DataFrame
    _known_tickers: frozenset[str]
    _provider: PriceProvider

    @classmethod
    def build(
        cls, provider: PriceProvider, tickers: list[str], start: object, end: object
    ) -> PricePanelStore:
        """Fetch `tickers` over [start, end] ONCE via `provider` (cache-backed,
        so this is parquet reads plus at most one network fetch per
        never-before-seen ticker) and hold the result in memory for the rest
        of this store's lifetime."""
        unique = sorted(set(tickers))
        panel = provider.get_prices(unique, start, end) if unique else _empty_panel()
        if not panel.empty:
            # M04b work packet perf fix (plans/M04b-engine-perf.md):
            # guarantee (rather than merely assume) a sorted DatetimeIndex,
            # so `get_prices` below can slice by date with `.loc[start:end]`
            # (binary search, O(log n + k)) instead of an elementwise
            # boolean mask over the WHOLE in-memory panel on every single
            # call - `PriceProvider`'s own docstring makes no sortedness
            # promise, so this is enforced here rather than trusted.
            panel = panel.sort_index()
        known = frozenset(panel["ticker"].unique()) if not panel.empty else frozenset()
        return cls(_panel=panel, _known_tickers=known, _provider=provider)

    def get_prices(self, tickers: list[str], start: object, end: object) -> pd.DataFrame:
        """Same contract as `PriceProvider.get_prices`: a long-format panel
        for `tickers` over [start, end]. Tickers already loaded are sliced
        from the in-memory panel; any others fall back to a direct,
        uncached provider call (see module docstring).

        Slices by DATE FIRST (`.loc[start:end]`, a binary search against the
        sorted index `build()` guarantees - O(log n + k) for a window of k
        rows) and only THEN filters the much smaller windowed result by
        ticker - not the other way around. A real multi-year run's full
        in-memory panel can hold millions of rows across the whole universe
        and window, while any single rebalance's own request window is a
        tiny fraction of it; filtering the full panel by ticker FIRST (an
        elementwise scan with no way to use the sorted index) before
        narrowing by date was measured, on the real 2012-2026 momentum run,
        re-scanning the ENTIRE in-memory panel on every one of this
        method's ~50-plus calls per rebalance."""
        start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
        wanted = list(dict.fromkeys(tickers))  # de-dup, preserve order
        in_store = [t for t in wanted if t in self._known_tickers]
        missing = [t for t in wanted if t not in self._known_tickers]

        frames = []
        if in_store:
            windowed = self._panel.loc[start_ts:end_ts]
            frames.append(windowed[windowed["ticker"].isin(in_store)])
        if missing:
            frames.append(self._provider.get_prices(missing, start_ts, end_ts))

        if not frames:
            return _empty_panel()
        return pd.concat(frames).sort_index()
