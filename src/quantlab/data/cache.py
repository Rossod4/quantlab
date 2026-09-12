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

## Negative-cache force-clear (M04b work packet item 3 - documented here,
## NOT implemented; M09's job)

`write_price_cache_no_data_meta` below adds a SECOND kind of sidecar: "the
last download attempt for this ticker came back with zero rows" (see
`has_sufficient_price_cache`'s "no_data" branch), trusted for
`retry_after_days` before being retried automatically. That TTL is the right
default for an unattended run, but a human operator who KNOWS a specific
"no_data" verdict was wrong (e.g. a vendor outage briefly affected one
ticker, or a delisted ticker was later relisted under the same symbol) has
no way to force an immediate re-check today - only `refresh_actions_cache()`
(data/corporate_actions.py) exists for the actions-cache equivalent, and it
has the same "no operational caller" gap noted there. M09's `quantlab data`
refresh/invalidation CLI should offer a force-clear for this sidecar (delete
`price_meta_path(ticker, cache_dir)`, or overwrite it with `no_data: False`)
alongside that module's `refresh_actions_cache()` wiring.
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

# Fallback TTL for a negative-cache sidecar (see `has_sufficient_price_cache`'s
# "no_data" branch) when no caller-supplied `retry_after_days` is given -
# `PlatformConfig.retry_after_days` (core/config.py) is the real, wired-in
# default (30) that every production call site actually uses; this constant
# only matters for a direct call to this function without threading that
# config value through (e.g. an ad hoc script or a test).
DEFAULT_RETRY_AFTER_DAYS = 30

# `has_sufficient_price_cache`'s "no_data" branch returns an empty frame in
# THIS shape - yfinance's raw (Yahoo-style capitalized) column names, exactly
# matching `providers/yfinance_prices.py`'s `_YF_COLUMN_MAP` keys - so that
# module's `df.rename(columns=_YF_COLUMN_MAP)[...]` reindex succeeds on an
# empty frame exactly as it would on a real (non-empty) cached one. Duplicated
# here rather than imported (this module must not depend on `data/providers/*`
# - see this module's own docstring) - keep the two in sync if either changes.
_EMPTY_RAW_PRICE_COLUMNS = ["Open", "High", "Low", "Close", "Adj Close", "Volume"]


def _today() -> pd.Timestamp:
    """Today's date (normalized). Module-level, like
    `data/corporate_actions.py`'s own `_today()`, so tests can monkeypatch it
    directly for determinism (CLAUDE.md invariant #5)."""
    return pd.Timestamp(pd.Timestamp.now().date())


def _empty_raw_price_frame() -> pd.DataFrame:
    empty = pd.DataFrame(columns=_EMPTY_RAW_PRICE_COLUMNS)
    empty.index = pd.DatetimeIndex([], name="Date")
    return empty


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


def write_price_cache_no_data_meta(
    ticker: str, start: object, end: object, cache_dir: Path
) -> None:
    """Negative-cache sidecar (M04b work packet item 3): record that a
    download for `ticker` over [start, end] came back with ZERO rows, so
    `has_sufficient_price_cache` can skip re-attempting it for
    `retry_after_days` instead of re-hitting the vendor on every single
    call - see that function's "no_data" branch and this module's docstring
    for the full M01 frozen-transient-failure hazard this closes without
    reintroducing it (a TTL, not a forever-cache).

    Deliberately writes NO parquet price file - `read_cache` on this
    ticker's price path stays `None` forever (until a real download
    succeeds), so `data/survivorship.py`'s `price_availability_from_cache`
    correctly reports `has_data=False` for it with no changes to that
    module at all."""
    write_json_meta(
        price_meta_path(ticker, cache_dir),
        {
            "no_data": True,
            "fetched_at": str(_today().date()),
            "requested_start": str(pd.Timestamp(start).date()),
            "requested_end": str(pd.Timestamp(end).date()),
        },
    )


def write_quarantine_meta(ticker: str, reasons: list[str], cache_dir: Path) -> None:
    """Quarantine sidecar (M04b quant-gate VERDICT.md cycle 1 finding 2):
    mark `ticker` as failing the quality scan (`data/quality.py`'s
    `scan_price_cache`). `has_sufficient_price_cache` then refuses to serve
    it (an empty frame, no TTL) regardless of what parquet data sits on
    disk, and `data/survivorship.py`'s `price_availability_from_cache`
    reports it as lacking data with reason "quarantined".

    MERGES into whatever sidecar already exists - a real, positively-cached
    ticker's `requested_start`/`requested_end` are preserved - rather than
    overwriting wholesale like `write_price_cache_no_data_meta` does.
    Quarantine is an independent quality verdict layered on top of an
    otherwise-normal (even a genuinely well-covered) cache entry, exactly
    the real-world case this milestone's scan found (PTV/BMC/TIE all have
    real, positively-cached parquet files; the DATA in them is corrupt)."""
    path = price_meta_path(ticker, cache_dir)
    existing = read_json_meta(path) or {}
    existing.update(
        {"quarantined": True, "reasons": list(reasons), "checked_at": str(_today().date())}
    )
    write_json_meta(path, existing)


def clear_quarantine_meta(ticker: str, cache_dir: Path) -> None:
    """Force-clear a quarantine verdict, leaving any other sidecar metadata
    (a real ticker's requested range) untouched. The mechanism M09's
    `quantlab data refresh --unquarantine <ticker>` is expected to call
    (documented, not wired to a CLI here - out of this milestone's scope)."""
    path = price_meta_path(ticker, cache_dir)
    existing = read_json_meta(path)
    if existing is None:
        return
    existing.pop("quarantined", None)
    existing.pop("reasons", None)
    existing.pop("checked_at", None)
    write_json_meta(path, existing)


def has_sufficient_price_cache(
    ticker: str,
    start: object,
    end: object,
    cache_dir: Path,
    retry_after_days: int = DEFAULT_RETRY_AFTER_DAYS,
) -> pd.DataFrame | None:
    """Return the cached OHLCV DataFrame for `ticker` if it already covers
    [start, end], else None (meaning: re-fetch).

    Checks, in order:

    0. Quarantine sidecar (M04b quant-gate VERDICT.md cycle 1 finding 2): a
       ticker the quality scan (`data/quality.py`'s `scan_price_cache`)
       judged corrupt is NEVER served, regardless of what parquet happens to
       sit on disk - always returns an empty frame. Unlike the negative
       cache below, this has NO TTL: a mislabeled/merged-instrument series
       does not become trustworthy again on its own, so only an explicit
       re-scan (M09's future `quantlab data refresh --unquarantine`) clears
       it.

    1. A REAL, non-empty parquet ALWAYS takes priority over a `no_data`
       sidecar (M04b quant-gate VERDICT.md cycle 1 finding 1, BLOCKING - this
       reorders the pre-fix check sequence, which consulted `no_data` before
       ever looking at the parquet file): if we recorded what range was
       REQUESTED when this cache file was written (sidecar metadata,
       preferred) and that request covers [start, end], the cache is
       complete by construction - even if the data itself stops years early
       (a delisted ticker). Falls back to a data-based check (cache files
       written before the metadata existed, or whose metadata request
       doesn't cover this one): the cache counts as covering a boundary if
       its data comes within CACHE_DATE_TOLERANCE_DAYS of it. A `no_data`
       verdict recorded ALONGSIDE a real parquet (e.g. a transient empty
       download hitting a ticker that already had good data - the exact
       hazard the finding reproduced) is never even consulted here: a
       non-empty parquet is proof the ticker is NOT "no data", full stop.

    2. Negative-cache sidecar (M04b work packet item 3), reached ONLY when
       there is no usable parquet at all: if the last download attempt for
       this ticker came back with ZERO rows (`write_price_cache_no_data_meta`),
       and that attempt is still within `retry_after_days` AND its own
       requested range already covers [start, end], treat the cache as
       sufficient - return an EMPTY frame (never None) so the caller does
       not re-fetch. Before this existed, a failed download was deliberately
       never cached at all (see this module's docstring's M01 note on the
       frozen-transient-failure hazard), which was safe but meant every
       ticker Yahoo no longer serves (a genuine, permanent delisting) was
       re-fetched - and re-throttled - on EVERY single call, the bug
       plans/M04b-engine-perf.md profiles. A TTL is the middle ground: once
       it lapses, this branch falls through to "insufficient" (None) below,
       so a GENUINELY transient failure still gets retried - just not on
       every call.
    """
    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
    meta = read_json_meta(price_meta_path(ticker, cache_dir))

    if meta is not None and meta.get("quarantined"):
        return _empty_raw_price_frame()

    path = price_cache_path(ticker, cache_dir)
    cached = read_cache(path)

    if cached is not None and not cached.empty:
        if meta is not None and not meta.get("no_data"):
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
        return None  # a real parquet exists but doesn't cover this request - re-fetch.

    # No usable parquet at all - only NOW does a negative-cache verdict apply.
    if meta is not None and meta.get("no_data"):
        fetched_at = pd.Timestamp(meta["fetched_at"])
        within_ttl = _today() - fetched_at < pd.Timedelta(days=retry_after_days)
        requested_covers = (
            pd.Timestamp(meta["requested_start"]) <= start_ts
            and pd.Timestamp(meta["requested_end"]) >= end_ts
        )
        if within_ttl and requested_covers:
            return _empty_raw_price_frame()
        return None  # TTL lapsed, or a wider range is now requested - retry.

    return None
