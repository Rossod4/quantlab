"""yfinance-backed `PriceProvider`, ported from the old repo's
`data_layer/prices.py`.

Per the README's design principle carried over from the old repo: strategy
and backtest code should never talk to a vendor directly. Everything
upstream of this module only ever calls `PriceProvider.get_prices()`.
Network calls happen only inside `_download_batch`; every other code path
(cache hit/miss decisions, windowing/trimming) is exercised offline via
`tests/test_prices_provider.py` using fixture cache files, plus a
`monkeypatch` of `_download_batch` to prove no network call was made.
"""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import yfinance as yf

from quantlab.data.cache import (
    DEFAULT_RETRY_AFTER_DAYS,
    has_sufficient_price_cache,
    price_cache_path,
    read_cache,
    write_price_cache_meta,
    write_price_cache_no_data_meta,
)
from quantlab.data.interfaces import PriceProvider

BATCH_SIZE = 75
BATCH_PAUSE_SECONDS = 2

# yfinance's raw (Yahoo-style capitalized) OHLCV columns, mapped to the
# PriceProvider long-panel column names.
_YF_COLUMN_MAP = {
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Adj Close": "adj_close",
    "Volume": "volume",
}

_PANEL_COLUMNS = ["ticker", "open", "high", "low", "close", "adj_close", "volume"]


def _download_batch(tickers: list[str], start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Download OHLCV for a batch of tickers via yfinance.

    Returns a DataFrame with a MultiIndex (ticker, field) column structure,
    matching yfinance's `group_by="ticker"` output. Module-level (rather
    than a method) so tests can monkeypatch it directly to prove a code
    path never touches the network - mirrors the old repo's structure.
    """
    return yf.download(
        tickers,
        start=start,
        end=end,
        auto_adjust=False,  # keep raw + Adj Close separately, for transparency
        group_by="ticker",
        threads=True,
        progress=False,
    )


def _empty_panel() -> pd.DataFrame:
    empty = pd.DataFrame(columns=_PANEL_COLUMNS)
    empty.index = pd.DatetimeIndex([], name="date")
    return empty


class YFinancePriceProvider(PriceProvider):
    """`PriceProvider` backed by yfinance, with per-ticker parquet caching.

    Caching: each ticker's full OHLCV history is cached separately. If the
    existing cache for a ticker already covers [start, end] (see
    `quantlab.data.cache.has_sufficient_price_cache`), it's reused;
    otherwise the ticker is re-fetched for the full requested range and the
    cache is overwritten. This is simpler than incrementally patching cache
    gaps, at the cost of occasionally re-fetching data already had - the
    same deliberate simplicity/efficiency trade-off as the old repo, at the
    same scale (hundreds of tickers, not thousands).
    """

    def __init__(self, cache_dir: Path, retry_after_days: int = DEFAULT_RETRY_AFTER_DAYS):
        self._cache_dir = Path(cache_dir)
        # M04b work packet item 3 - `PlatformConfig.retry_after_days`
        # (core/config.py), wired through `data/interfaces.py.build_provider`.
        self._retry_after_days = retry_after_days

    def get_prices(self, tickers: list[str], start: object, end: object) -> pd.DataFrame:
        start_ts = pd.Timestamp(start).normalize()
        end_ts = pd.Timestamp(end).normalize()

        to_fetch: list[str] = []
        cached_frames: dict[str, pd.DataFrame] = {}
        for ticker in tickers:
            cached = has_sufficient_price_cache(
                ticker, start_ts, end_ts, self._cache_dir, retry_after_days=self._retry_after_days
            )
            if cached is not None:
                cached_frames[ticker] = cached
            else:
                to_fetch.append(ticker)

        downloaded_frames: dict[str, pd.DataFrame] = {}
        for i in range(0, len(to_fetch), BATCH_SIZE):
            batch = to_fetch[i : i + BATCH_SIZE]
            try:
                raw = _download_batch(batch, start_ts, end_ts)
            except Exception:
                # A whole-batch failure (e.g. transient network error)
                # shouldn't abort the entire fetch - these tickers simply
                # won't appear in the result.
                continue

            for ticker in batch:
                try:
                    # yfinance>=1.0 always returns MultiIndex (ticker, field)
                    # columns under group_by="ticker", even for a single-
                    # ticker batch (the old repo's yfinance 0.2.x returned
                    # flat columns for a batch of one - a mechanical API
                    # change, see handoff). Handle both shapes.
                    if isinstance(raw.columns, pd.MultiIndex):
                        ticker_df = raw[ticker]
                    else:
                        ticker_df = raw
                    ticker_df = ticker_df.dropna(how="all")
                    if ticker_df.empty or "Adj Close" not in ticker_df:
                        # M04b work packet item 3: the BATCH download itself
                        # succeeded (we're inside the `try` for `_download_
                        # batch`, past its own exception handler above) but
                        # THIS ticker came back with no usable rows - a
                        # vendor no longer serving it (a real, permanent
                        # delisting) is indistinguishable here from a one-off
                        # gap, so record a NEGATIVE-cache sidecar (TTL-bound,
                        # never a parquet file) rather than silently doing
                        # nothing - see cache.py's `write_price_cache_no_data_
                        # meta` and `has_sufficient_price_cache`'s "no_data"
                        # branch. Before this fix, nothing was recorded here
                        # at all, so a ticker Yahoo no longer serves was
                        # re-downloaded (and re-throttled) on EVERY single
                        # call - the M04b work packet's profiled bug.
                        #
                        # M04b quant-gate VERDICT.md cycle 1 finding 1
                        # (BLOCKING): this fetch attempt can be reached for a
                        # ticker that ALREADY has real, healthy cached data
                        # (e.g. a wider re-fetch triggered by a request that
                        # exceeds the existing cache's covered range - see
                        # `has_sufficient_price_cache`) - a transient empty
                        # result inside that call must NEVER overwrite the
                        # ticker's sidecar with `no_data`, which would mask
                        # the real parquet on every future read. Only write
                        # the negative-cache sidecar when there is no usable
                        # parquet for this ticker at all.
                        if read_cache(price_cache_path(ticker, self._cache_dir)) is None:
                            write_price_cache_no_data_meta(
                                ticker, start_ts, end_ts, self._cache_dir
                            )
                        continue
                    write_path = price_cache_path(ticker, self._cache_dir)
                    write_path.parent.mkdir(parents=True, exist_ok=True)
                    ticker_df.to_parquet(write_path)
                    # Record what range this fetch was FOR, so future calls
                    # can trust the cache even when the data legitimately
                    # stops early (delisted ticker) - see cache.py. This also
                    # OVERWRITES any stale negative-cache sidecar (a ticker
                    # that previously came back empty but now succeeded) -
                    # `write_json_meta` replaces the file wholesale, so the
                    # "no_data" flag never lingers once a real download
                    # succeeds (M04b acceptance test (c)).
                    write_price_cache_meta(ticker, start_ts, end_ts, self._cache_dir)
                    downloaded_frames[ticker] = ticker_df
                except KeyError:
                    # The ticker key is entirely absent from a MultiIndex
                    # batch result - yfinance's equivalent of "no rows for
                    # this ticker" for a batch shape rather than an empty
                    # frame; same negative-cache treatment as above (and the
                    # same "never mask an existing healthy parquet" guard).
                    if read_cache(price_cache_path(ticker, self._cache_dir)) is None:
                        write_price_cache_no_data_meta(ticker, start_ts, end_ts, self._cache_dir)
                    continue
                except ValueError:
                    continue

            if i + BATCH_SIZE < len(to_fetch):
                time.sleep(BATCH_PAUSE_SECONDS)

        all_frames = {**cached_frames, **downloaded_frames}
        if not all_frames:
            return _empty_panel()

        panels = []
        for ticker, df in all_frames.items():
            panel = df.rename(columns=_YF_COLUMN_MAP)[list(_YF_COLUMN_MAP.values())].copy()
            panel["ticker"] = ticker
            panels.append(panel)
        combined = pd.concat(panels).sort_index()

        # Trim to the requested [start, end] window. A cached file can cover
        # a WIDER range than this call asked for - see the regression test
        # in test_prices_provider.py for why this trim is load-bearing.
        combined = combined.loc[(combined.index >= start_ts) & (combined.index <= end_ts)]
        combined.index.name = "date"
        return combined[_PANEL_COLUMNS]
