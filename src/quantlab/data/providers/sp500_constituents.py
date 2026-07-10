"""Point-in-time S&P 500 constituents, ported from the old repo's
`data_layer/constituents.py`.

Using TODAY'S S&P 500 list for the whole backtest would introduce
survivorship bias: any company that was in the index and later got removed
(bankruptcy, acquisition, demotion) would be invisible to the strategy,
silently inflating returns. Instead this module tracks index MEMBERSHIP AS
IT ACTUALLY WAS on each historical date, using a free, community-maintained
dataset: https://github.com/fja05680/sp500

This is NOT an official index vendor feed - it's compiled from Wikipedia
and updated by the maintainer roughly every couple of months. That means
some historical add/remove dates may be slightly imprecise, and membership
for the very latest weeks/months may lag true real-time changes. This is a
real, documented limitation - "point-in-time" here means "best-effort
point-in-time from a free community source", not "guaranteed
survivorship-bias-free". It's still a meaningful improvement over using
today's constituent list retroactively.

The CSV itself has one row per date-of-change, with a single quoted,
comma-separated `tickers` column (not JSON), e.g.:

    date,tickers
    1996-01-02,"AAL,AAMRQ,AAPL,ABI,..."
"""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import requests

from quantlab.data.cache import read_cache, write_cache
from quantlab.data.interfaces import ConstituentsProvider

DEFAULT_CONSTITUENTS_URL = (
    "https://raw.githubusercontent.com/fja05680/sp500/master/"
    "S%26P%20500%20Historical%20Components%20%26%20Changes%20(Updated).csv"
)
CACHE_FILENAME = "sp500_constituents.parquet"


def normalize_ticker(ticker: str) -> str:
    """Convert a dataset ticker to the symbol yfinance/Yahoo Finance expects.

    Share classes are written with a dot in this dataset (e.g. "BF.B",
    "BRK.B") but yfinance/Yahoo Finance use a hyphen ("BF-B", "BRK-B").
    """
    return ticker.replace(".", "-")


def _download_constituents_csv(url: str) -> pd.DataFrame:
    """Download and parse the raw point-in-time constituents CSV.

    Returns a DataFrame with a DatetimeIndex named `date` (sorted ascending)
    and a single column `tickers`, where each value is a list[str].

    Uses `requests` rather than `pandas.read_csv(url)` directly - the latter
    goes through urllib, which was found to truncate this ~multi-MB file
    when fetched through a proxy (IncompleteRead), while `requests` handles
    it correctly.
    """
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    raw = pd.read_csv(io.StringIO(response.text))
    raw["date"] = pd.to_datetime(raw["date"])
    # The `tickers` column is a single quoted comma-separated string, e.g.
    # "AAL,AAMRQ,AAPL" - split it into an actual list of ticker strings.
    raw["tickers"] = raw["tickers"].str.split(",")
    raw = raw.set_index("date").sort_index()
    return raw[["tickers"]]


class SP500CommunityConstituentsProvider(ConstituentsProvider):
    """`ConstituentsProvider` backed by the fja05680/sp500 community CSV."""

    def __init__(self, cache_dir: Path, url: str = DEFAULT_CONSTITUENTS_URL):
        self._cache_dir = Path(cache_dir)
        self._url = url

    def _load_table(self, force_refresh: bool = False) -> pd.DataFrame:
        """Load the point-in-time constituents table, using the local cache
        if present. The parquet cache stores `tickers` as a native list
        column, so no re-parsing of the comma-separated string is needed on
        cache hits."""
        cache_path = self._cache_dir / CACHE_FILENAME
        if not force_refresh:
            cached = read_cache(cache_path)
            if cached is not None:
                return cached

        table = _download_constituents_csv(self._url)
        write_cache(table, cache_path)
        return table

    def membership(self, asof: object) -> list[str]:
        """Return the S&P 500 tickers that were constituents as of `asof`.

        This is an "as-of" lookup: it finds the most recent row in the
        constituents table with a date <= `asof`, and returns that row's
        ticker list. This enforces the no-look-ahead invariant for the
        universe: a rebalance on date `t` can never see index changes that
        happened after `t`.

        Raises ValueError if `asof` precedes the earliest date in the
        table, since there's no valid point-in-time membership to return -
        this matches the old repo's behavior exactly (see
        tests/test_constituents.py::test_date_before_earliest_raises).
        """
        table = self._load_table()
        return _membership_from_table(table, asof)

    def membership_history(self, start: object, end: object) -> pd.DataFrame:
        """Membership change rows recorded within [start, end], with
        `tickers` normalized (dot -> hyphen)."""
        table = self._load_table()
        start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
        sliced = table.loc[(table.index >= start_ts) & (table.index <= end_ts)].copy()
        sliced["tickers"] = sliced["tickers"].apply(
            lambda tickers: [normalize_ticker(t) for t in tickers]
        )
        return sliced


def _membership_from_table(table: pd.DataFrame, asof: object) -> list[str]:
    """Shared as-of lookup logic, factored out so tests can exercise it
    directly against small synthetic tables (see test_constituents.py),
    matching the old repo's `get_membership(date, table)` signature."""
    date = pd.Timestamp(asof)
    if date < table.index.min():
        raise ValueError(
            f"No point-in-time S&P 500 membership data available before "
            f"{table.index.min().date()}; requested date {date.date()} is "
            f"earlier than that."
        )

    # `asof` finds the last index label <= date, which is exactly the
    # "most recent known membership as of this date" lookup we need.
    as_of_date = table.index.asof(date)
    tickers = table.loc[as_of_date, "tickers"]
    return [normalize_ticker(t) for t in tickers]
