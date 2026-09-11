"""Parquet cache helpers, ported from the old repo's `data_layer/cache_utils.py`
and `data_layer/prices.py`.

All downloaded data (point-in-time constituents, per-ticker OHLCV) is cached
to disk as parquet so repeated runs don't re-hit the network or a vendor's
rate limits. The cache directory is regenerable — deleting it just means the
next run re-fetches everything.

The one piece of genuinely valuable logic here (per the M01 packet) is the
per-ticker sidecar metadata in `has_sufficient_price_cache`: it records what
date range was REQUESTED when a ticker's cache was written, so a ticker that
was delisted mid-window (and therefore has no data after its delisting date
no matter how often it's re-fetched) is recognized as "fully cached" instead
of being silently re-downloaded on every run.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

# Requested start/end dates are calendar dates, but price data only exists
# for trading days. A requested `end` that falls on a weekend/holiday can
# never be matched exactly by the last cached trading day, so an exact
# equality check would make the cache "insufficient" forever. This
# tolerance treats the cache as covering a boundary if it comes within a
# week of it - comfortably more than any run of holidays/weekends.
CACHE_DATE_TOLERANCE_DAYS = 7


def read_cache(path: Path) -> pd.DataFrame | None:
    """Return the cached DataFrame at `path`, or None if it doesn't exist."""
    if not path.exists():
        return None
    return pd.read_parquet(path)


def write_cache(df: pd.DataFrame, path: Path) -> None:
    """Write `df` to `path` as parquet, creating parent directories if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path)


def price_cache_path(ticker: str, cache_dir: Path) -> Path:
    return Path(cache_dir) / "prices" / f"{ticker}.parquet"


def price_meta_path(ticker: str, cache_dir: Path) -> Path:
    """Sidecar metadata file recording what date range was REQUESTED when the
    ticker's cache was written (see `has_sufficient_price_cache` for why the
    data's own dates aren't enough to judge cache completeness)."""
    return Path(cache_dir) / "prices" / f"{ticker}.meta.json"


def read_json_meta(path: Path) -> dict | None:
    """Generic JSON sidecar reader, or None if `path` doesn't exist. The one
    mechanism behind every per-ticker cache sidecar in this platform - the
    price cache's requested-range metadata below, and the actions cache's
    fetch-time metadata (data/corporate_actions.py) - so there is a single
    place that knows how a sidecar file is read, not one per cache."""
    if not path.exists():
        return None
    return json.loads(path.read_text())


def write_json_meta(path: Path, meta: dict) -> None:
    """Generic JSON sidecar writer - see `read_json_meta`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta))


def write_price_cache_meta(ticker: str, start: object, end: object, cache_dir: Path) -> None:
    write_json_meta(
        price_meta_path(ticker, cache_dir),
        {
            "requested_start": str(pd.Timestamp(start).date()),
            "requested_end": str(pd.Timestamp(end).date()),
        },
    )


def has_sufficient_price_cache(
    ticker: str, start: object, end: object, cache_dir: Path
) -> pd.DataFrame | None:
    """Return the cached OHLCV DataFrame for `ticker` if it already covers
    [start, end], else None (meaning: re-fetch).

    Two checks, in order:

    1. Sidecar metadata (preferred): if we recorded what range was REQUESTED
       when this cache file was written, and that request covers [start, end],
       the cache is complete by construction - even if the data itself stops
       years early. This matters for delisted tickers: a stock delisted in
       2015 has no prices after 2015 no matter how often it's re-fetched.
       Judging completeness by the data's last date alone made every
       delisted-mid-window ticker look permanently stale, so it was silently
       re-fetched on EVERY run - slow, and worse, vendor-adjusted prices can
       drift by tiny amounts between downloads, which would make supposedly
       identical backtest runs differ in the least-significant digits
       (breaking bit-for-bit reproducibility).

    2. Data-based fallback (for cache files written before the metadata
       existed): the cache counts as covering a boundary if its data comes
       within CACHE_DATE_TOLERANCE_DAYS of it - enough slack for weekends
       and holiday runs, but a delisted ticker's early stop still triggers
       one re-fetch, after which the metadata takes over.
    """
    path = price_cache_path(ticker, cache_dir)
    cached = read_cache(path)
    if cached is None or cached.empty:
        return None

    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)

    meta = read_json_meta(price_meta_path(ticker, cache_dir))
    if meta is not None:
        requested_covers = (
            pd.Timestamp(meta["requested_start"]) <= start_ts
            and pd.Timestamp(meta["requested_end"]) >= end_ts
        )
        if requested_covers:
            return cached

    tolerance = pd.Timedelta(days=CACHE_DATE_TOLERANCE_DAYS)
    covers_start = cached.index.min() <= start_ts + tolerance
    covers_end = cached.index.max() >= end_ts - tolerance
    if covers_start and covers_end:
        return cached
    return None
