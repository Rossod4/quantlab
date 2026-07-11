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
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

from quantlab.core.types import DelistingEvent, DelistingReason, normalize_timestamp
from quantlab.data.cache import price_cache_path, read_cache, write_cache
from quantlab.data.interfaces import ConstituentsProvider, CorporateActionsProvider

ACTIONS_CACHE_SUBDIR = "actions"
_ACTION_COLUMNS = ["ticker", "action_type", "value"]


def _actions_cache_path(ticker: str, cache_dir: Path) -> Path:
    return Path(cache_dir) / ACTIONS_CACHE_SUBDIR / f"{ticker}.parquet"


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
            except (requests.RequestException, OSError):
                # A failed download must NOT be written to the cache: doing
                # so would freeze a transient network error as "this ticker
                # has no actions, ever" - exactly the frozen-truncation
                # hazard plans/QUANT-NOTES.md's M01 note flags (and which
                # data/survivorship.py exists to measure on the price side).
                # Returning without caching means the next call re-attempts
                # the fetch. Only network-level failures are swallowed
                # (requests.RequestException covers everything yfinance's
                # requests-based transport raises; OSError covers raw
                # socket/curl-level errors from alternate transports) - a
                # genuine yfinance API/parsing bug should surface loudly,
                # not masquerade as an empty actions history.
                return _empty_actions()
            write_cache(cached, cache_path)

        start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
        return cached.loc[(cached.index >= start_ts) & (cached.index <= end_ts)].copy()


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
