"""Corporate actions (dividends/splits) and delisting inference.

`YFinanceCorporateActionsProvider` implements `CorporateActionsProvider`
(data/interfaces.py), backed by yfinance's per-ticker `actions` endpoint
(dividends + stock splits, each with a genuine, independently-announced ex
date - NOT derived from the vendor's globally-adjusted close series). This
is new code in this milestone (no old-repo port source exists for it), with
its own per-ticker parquet cache following the same pattern as
data/cache.py's price cache.

Why this module exists, and why it does NOT yet drive price adjustment:
see the "central design decision" writeup in the M02 handoff
(plans/state/M02/HANDOFF.md) for the full reasoning. In short:
`PITDataContext.prices()` deliberately does NOT use this module's actions
to compute an as-of-adjusted price in this milestone - that would be new,
unparitized numerical logic in the platform's most safety-critical spot.
This module still ships now because (a) `CorporateActionsProvider` was
already a signature-only ABC from M01 that needs a real implementation, (b)
`actions(ticker)` is independently useful point-in-time metadata, and (c)
it's the building block a future milestone would need to implement as-of
adjustment properly, once it can be parity-tested.

Delisting inference: a lightweight heuristic, not a real corporate-events
feed. `infer_delisting()` only ever produces `DelistingReason.UNKNOWN` -
distinguishing ACQUISITION from BANKRUPTCY needs a richer source (e.g. SEC
8-K filings) not built here; see its docstring for the exact rule.

## Actions-cache staleness (M02b, VERDICT.md carried item 1 - IN SCOPE, not
## carried to a later milestone: "needs refresh-or-metadata before a long
## backtest" is part of this packet's required contents)

This cache is fetch-once-forever: once a ticker's actions history is
downloaded it is trusted forever, never re-fetched opportunistically (see
`get_actions` below). That is safe for a purely historical backtest (no
split announced after the fetch can matter to an `asof` that already
precedes the fetch), but it silently reintroduces the raw-discontinuity bug
the M02b adjustment replay exists to close for any `asof` LATER than the
fetch time - a split announced after the cache was populated is invisible
to it. `get_actions` therefore records a `fetched_at` date in the cache
sidecar metadata (data/cache.py's generic JSON-sidecar mechanism, the same
one `write_price_cache_meta` uses - not a parallel one) on every fresh
download, and raises `StaleActionsCacheError` - naming the ticker, the
requested asof, and the fetched_at (or its absence) - when asked for
actions through an `end` later than that date. `end` is exactly `asof` at
every current call site (`PITDataContext._gated_actions_by_ticker` calls
`get_actions(ticker, _EPOCH, self._asof)`), so enforcing here IS enforcing
on the PIT actions path; the alternative of also adding an abstractmethod
to `CorporateActionsProvider` so `pit.py` could check it directly was
rejected as disproportionate - it would force every test fake across
tests/test_pit.py, tests/canaries/test_lookahead.py and
tests/test_adjustment.py to implement a method they have no need for.
No auto-refresh happens here or anywhere in the PIT path (offline,
deterministic per CLAUDE.md invariant #5); `refresh_actions_cache()` below
is the only way to clear a `StaleActionsCacheError`, and is expected to be
invoked from a network-tier operational path, never from `pit.py`.

Granularity: `fetched_at` is a calendar DATE, matching this platform's
day-granular `asof` convention (like the day-granular EDGAR `filed` gate
carried to M03/M04 in QUANT-NOTES.md) - a same-day fetch-then-decide is
never flagged stale, even though a split could in principle be announced
between the two intraday. Documented limitation, not a bug.

Backward compatibility: a cache file written before this sidecar existed
has no `fetched_at` metadata. Missing metadata is treated as STALE (raises)
rather than trusted - "we don't know when this was fetched" must never
silently pass through to an as-of decision. This is a deliberate reversal
of the more lenient stance `cache.py.has_sufficient_price_cache` takes for
its own pre-metadata files (there, staleness only costs a redundant
re-fetch; here, missing information about freshness is exactly the failure
mode this check exists to catch), and it means every actions cache entry
written before this milestone requires one `refresh_actions_cache()` call
before its ticker's actions are usable again.

A transient fetch failure on a cache MISS raises `ActionsFetchError`
(a `DataQualityError`) rather than returning an empty frame - the same
"never silently degrade an as-of decision" principle as the staleness
check above, closing VERDICT.md (M02b re-review) finding 2. Nothing is
cached on this path, so the next call retries.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

from quantlab.core.errors import ActionsFetchError, StaleActionsCacheError
from quantlab.core.types import DelistingEvent, DelistingReason, normalize_timestamp
from quantlab.data.cache import (
    price_cache_path,
    read_cache,
    read_json_meta,
    write_cache,
    write_json_meta,
)
from quantlab.data.interfaces import ConstituentsProvider, CorporateActionsProvider

ACTIONS_CACHE_SUBDIR = "actions"
_ACTION_COLUMNS = ["ticker", "action_type", "value"]


def _actions_cache_path(ticker: str, cache_dir: Path) -> Path:
    return Path(cache_dir) / ACTIONS_CACHE_SUBDIR / f"{ticker}.parquet"


def _actions_meta_path(ticker: str, cache_dir: Path) -> Path:
    """Sidecar metadata recording the date `ticker`'s actions cache was last
    (re)fetched - see module docstring's staleness section."""
    return Path(cache_dir) / ACTIONS_CACHE_SUBDIR / f"{ticker}.meta.json"


def _today() -> pd.Timestamp:
    """Today's date (normalized). Module-level (like `_download_actions`)
    so tests can monkeypatch it directly for determinism (CLAUDE.md
    invariant #5: tests are offline and deterministic)."""
    return normalize_timestamp(pd.Timestamp.now())


def _write_actions_cache_meta(ticker: str, cache_dir: Path) -> None:
    write_json_meta(_actions_meta_path(ticker, cache_dir), {"fetched_at": str(_today().date())})


def _read_actions_cache_fetched_at(ticker: str, cache_dir: Path) -> pd.Timestamp | None:
    meta = read_json_meta(_actions_meta_path(ticker, cache_dir))
    if meta is None:
        return None
    return normalize_timestamp(meta["fetched_at"])


def _empty_actions() -> pd.DataFrame:
    empty = pd.DataFrame(columns=_ACTION_COLUMNS)
    empty.index = pd.DatetimeIndex([], name="date")
    return empty


def _normalize_actions(ticker: str, raw: pd.DataFrame) -> pd.DataFrame:
    """Normalize yfinance's `Ticker(ticker).actions` (DatetimeIndex, columns
    "Dividends"/"Stock Splits", zero where no event occurred) into this
    module's long format: DatetimeIndex named "date", columns
    [ticker, action_type, value] - one row per actual event (zero rows
    dropped)."""
    if raw is None or raw.empty:
        return _empty_actions()

    dates = pd.DatetimeIndex([normalize_timestamp(d) for d in raw.index], name="date")
    df = raw.copy()
    df.index = dates

    rows = []
    if "Dividends" in df:
        for date, val in df.loc[df["Dividends"] != 0, "Dividends"].items():
            rows.append(
                {"date": date, "ticker": ticker, "action_type": "dividend", "value": float(val)}
            )
    if "Stock Splits" in df:
        for date, val in df.loc[df["Stock Splits"] != 0, "Stock Splits"].items():
            rows.append(
                {"date": date, "ticker": ticker, "action_type": "split", "value": float(val)}
            )

    if not rows:
        return _empty_actions()

    result = pd.DataFrame(rows).set_index("date").sort_index()
    return result[_ACTION_COLUMNS]


def _download_actions(ticker: str) -> pd.DataFrame:
    """Fetch dividends/splits for `ticker` via yfinance. Module-level
    (rather than a method) so tests can monkeypatch it directly to prove a
    code path never touches the network - mirrors yfinance_prices.py's
    `_download_batch` pattern."""
    raw = yf.Ticker(ticker).actions
    return _normalize_actions(ticker, raw)


class YFinanceCorporateActionsProvider(CorporateActionsProvider):
    """`CorporateActionsProvider` backed by yfinance dividends/splits, with
    per-ticker parquet caching (cached forever once fetched, like the price
    cache's delisted-ticker case - dividend/split history for a given
    ticker only grows over time, so a cache hit is always safe to reuse for
    OLDER data; this provider does not attempt incremental refresh)."""

    def __init__(self, cache_dir: Path):
        self._cache_dir = Path(cache_dir)

    def get_actions(self, ticker: str, start: object, end: object) -> pd.DataFrame:
        cache_path = _actions_cache_path(ticker, self._cache_dir)
        cached = read_cache(cache_path)
        if cached is None:
            try:
                cached = _download_actions(ticker)
            except (requests.RequestException, OSError) as exc:
                # A failed download must NOT be written to the cache: doing
                # so would freeze a transient network error as "this ticker
                # has no actions, ever" - exactly the frozen-truncation
                # hazard plans/QUANT-NOTES.md's M01 note flags (and which
                # data/survivorship.py exists to measure on the price side).
                # Not caching means the next call re-attempts the fetch.
                # Only network-level failures are swallowed here (
                # requests.RequestException covers everything yfinance's
                # requests-based transport raises; OSError covers raw
                # socket/curl-level errors from alternate transports) - a
                # genuine yfinance API/parsing bug still surfaces loudly.
                #
                # VERDICT.md (M02b re-review) finding 2: returning an empty
                # frame here used to silently disable adjustment - before
                # M02b, "no actions" was benign metadata; after M02b it
                # means "no as-of adjustment", so a transient blip would
                # make prices() return the raw, split-distorted series with
                # no error. Raise instead of degrading silently.
                raise ActionsFetchError(
                    f"{ticker}: failed to fetch corporate actions ({exc!r}) - refusing to "
                    'treat this as "no actions", which would silently disable the as-of '
                    "adjustment replay for this ticker. Not cached; retry once the "
                    "underlying failure clears."
                ) from exc
            write_cache(cached, cache_path)
            _write_actions_cache_meta(ticker, self._cache_dir)

        end_ts = normalize_timestamp(end)
        fetched_at = _read_actions_cache_fetched_at(ticker, self._cache_dir)
        # See module docstring's staleness section: a missing fetch date is
        # treated the SAME as a known-stale one - never silently trusted.
        if fetched_at is None or end_ts > fetched_at:
            if fetched_at is None:
                fetched_at_desc = "unknown (no fetch-time metadata recorded)"
            else:
                fetched_at_desc = str(fetched_at.date())
            raise StaleActionsCacheError(
                f"{ticker}: actions cache staleness check failed for asof={end_ts.date()} "
                f"(fetched_at={fetched_at_desc}) - a corporate action announced since the "
                "cache was fetched (or ever, if the fetch time is unknown) would be "
                "invisible to this as-of decision. Call refresh_actions_cache() to refresh."
            )

        start_ts = normalize_timestamp(start)
        return cached.loc[(cached.index >= start_ts) & (cached.index <= end_ts)].copy()


def refresh_actions_cache(ticker: str, cache_dir: Path) -> pd.DataFrame:
    """Force a fresh download of `ticker`'s corporate actions, overwriting
    whatever is cached and resetting the `fetched_at` staleness sidecar
    (see module docstring). The only way to clear a `StaleActionsCacheError`
    for a ticker - this provider is otherwise fetch-once-forever and never
    refreshes opportunistically. A download failure here propagates (unlike
    `get_actions`'s opportunistic first fetch): a caller explicitly asking
    for a refresh needs to know it did not happen, not get a silent no-op."""
    fresh = _download_actions(ticker)
    write_cache(fresh, _actions_cache_path(ticker, cache_dir))
    _write_actions_cache_meta(ticker, cache_dir)
    return fresh


def infer_delisting(
    ticker: str,
    price_cache_dir: Path,
    constituents_provider: ConstituentsProvider,
    end: object,
) -> DelistingEvent | None:
    """Infer a delisting event for `ticker` from its cached price data plus
    point-in-time constituents membership.

    Heuristic, per the M02 work packet: if `ticker`'s last cached price bar
    precedes the requested `end` date AND `ticker` LEFT the constituents
    set - it WAS a member as of its last trade date but is NOT a member as
    of `end` - infer it was delisted at its last observed trade date.
    Requiring prior membership (not just absence at `end`) prevents a
    spurious DelistingEvent for a ticker that was never a member of the
    tracked index but happens to have a stale price cache. Reason is always
    UNKNOWN - distinguishing ACQUISITION from BANKRUPTCY needs a richer
    source (e.g. SEC 8-K filings or a dedicated delisting-reason feed) not
    built in this milestone.

    Returns None when there's no evidence of delisting: price data extends
    through `end`, the ticker has no cached price data at all (nothing to
    infer from), the ticker wasn't a member at its last trade date (never
    "left" the set), or the membership data doesn't reach back far enough
    to establish either membership lookup (ValueError from the provider).
    """
    cached = read_cache(price_cache_path(ticker, price_cache_dir))
    if cached is None or cached.empty:
        return None

    end_ts = pd.Timestamp(end)
    last_trade_date = pd.Timestamp(cached.index.max())
    if last_trade_date >= end_ts:
        return None

    try:
        members_at_last_trade = set(constituents_provider.membership(last_trade_date))
        members_at_end = set(constituents_provider.membership(end_ts))
    except ValueError:
        return None

    if ticker not in members_at_last_trade or ticker in members_at_end:
        return None

    return DelistingEvent(
        ticker=ticker, last_trade_date=last_trade_date, reason=DelistingReason.UNKNOWN
    )
