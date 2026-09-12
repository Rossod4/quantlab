"""Survivorship coverage-gap measurement, ported as a library from the old
repo's `scripts/coverage_gap_analysis.py` (a one-off analysis script there;
here it's `coverage_gap()`, a pure function so backtests can embed the
result directly - see CLAUDE.md invariant #2: "Every `BacktestResult`
embeds the universe coverage-gap bound").

The strategies this platform builds can only rank names it has data for.
The uncovered remainder of the point-in-time universe (no price data, or
masked by a truncated cache - see below) is invisible to every strategy,
which is a real form of survivorship/selection bias. Rather than footnoting
that as an unknown, this module measures it, per year, from whatever
universe-membership and price-availability information the caller has -
pure function of inputs, no disk I/O, fully offline-testable.

Per plans/QUANT-NOTES.md's M01 note: a ticker's price cache can look
"fully served" purely because of cache SIDECAR METADATA recording a wide
REQUESTED range (see data/cache.py's `write_price_cache_meta` /
`has_sufficient_price_cache`), even when the underlying data actually
stopped years earlier - e.g. a one-time truncated vendor response gets
frozen as "complete" and all later data is silently masked. If the
point-in-time constituents say the ticker was STILL a member after that
masked cutoff, that's real coverage loss, not silence - `PriceAvailability`
carries both the real last-bar date and the metadata-claimed end so
`coverage_gap()` can surface exactly this case (see `masked_tickers` below).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from quantlab.data.cache import price_cache_path, price_meta_path, read_cache, read_json_meta


@dataclass(frozen=True)
class PriceAvailability:
    """Per-ticker price cache availability, as needed by `coverage_gap()`.

    `has_data`: whether any cached price bars exist for this ticker at all.
    `last_bar_date`: the ticker's most recent cached bar (None if no data).
    `masked_end`: if the cache's sidecar metadata recorded that data was
        REQUESTED through this date, but `last_bar_date` is earlier, the gap
        between them is a "masked truncation" (see module docstring). None
        if no such metadata is known, or it doesn't exceed `last_bar_date`.
    `quarantined`: whether `data/quality.py`'s `scan_price_cache` judged this
        ticker's cached history corrupt (a merged/reused-symbol series - see
        that module's docstring) and quarantined it. A quarantined ticker
        reports `has_data=False` here REGARDLESS of what its real parquet
        contains (M04b quant-gate VERDICT.md cycle 1 finding 2) - its data
        is judged untrustworthy, not merely absent, but the coverage-gap
        effect on a strategy is identical: the name is invisible to it.
    `masked_start`: the mirror of `masked_end` on the START side (M04b
        quant-gate cycle-2 review): if the ticker was ALREADY a point-in-time
        index member before its cached history's first bar, the ticker's
        early membership span is invisible to any strategy even though
        `has_data=True` and the cache is not otherwise flagged - e.g. a
        symbol reused for a new listing (`data/quality.py`'s
        `symbol_reuse_new_listing_reason`) reports real, clean-looking data
        that nonetheless cannot cover the ORIGINAL constituent's own
        history. `None` if the ticker's membership start is unknown, or
        membership began on/after the first cached bar (nothing masked).
    """

    has_data: bool
    last_bar_date: pd.Timestamp | None = None
    masked_end: pd.Timestamp | None = None
    quarantined: bool = False
    masked_start: pd.Timestamp | None = None


@dataclass(frozen=True)
class CoverageReport:
    """Per-year coverage-gap percentages plus a single conservative bound.

    `by_year`: pandas Series indexed by calendar year (int), values are the
        % (0-100) of that year's point-in-time constituents lacking usable
        price data.
    `overall_bound`: the WORST single year's percentage across the whole
        window - a conservative ceiling ("coverage loss never exceeded
        X% in any year"), not an average, since an average could hide one
        badly-covered year behind several well-covered ones.
    `masked_tickers`: year -> sorted list of tickers whose coverage loss in
        that year comes specifically from a cache-metadata-masked
        truncation (see module docstring) rather than genuinely absent data.
    `quarantined_tickers`: year -> sorted list of tickers whose coverage
        loss in that year comes specifically from a quality-scan quarantine
        (M04b quant-gate VERDICT.md cycle 1 finding 2 - `PriceAvailability.
        quarantined`) rather than genuinely absent data or a masked
        truncation. A ticker can appear here without appearing in
        `masked_tickers` (or vice versa) - they are independent reasons a
        member is "lacking".
    `masked_start_tickers`: year -> sorted list of tickers whose coverage
        loss in that year comes from a START-side masked truncation
        (`PriceAvailability.masked_start` - cycle-2 review) - the ticker was
        already a point-in-time member before its cached history begins
        (commonly a reused-symbol new listing whose OWN clean data cannot
        stand in for the original constituent's history).
    """

    by_year: pd.Series
    overall_bound: float
    masked_tickers: dict[int, list[str]] = field(default_factory=dict)
    quarantined_tickers: dict[int, list[str]] = field(default_factory=dict)
    masked_start_tickers: dict[int, list[str]] = field(default_factory=dict)


def _as_of_membership(universe_history: pd.DataFrame, asof: pd.Timestamp) -> list[str]:
    """Point-in-time membership as of `asof`: the most recent row in
    `universe_history` (indexed by change date, `tickers` column of
    list[str]) with a date <= `asof`. Returns [] if none exists (asof
    precedes all known membership data, or the table is empty)."""
    if universe_history.empty:
        return []
    as_of_date = universe_history.index.asof(asof)
    if pd.isna(as_of_date):
        return []
    return list(universe_history.loc[as_of_date, "tickers"])


def coverage_gap(
    universe_history: pd.DataFrame,
    price_availability: dict[str, PriceAvailability],
    start: object,
    end: object,
    sample_dates: pd.DatetimeIndex | None = None,
) -> CoverageReport:
    """Per-year % of point-in-time constituents lacking price data, plus an
    overall conservative bound.

    For each calendar year in [start, end], membership is taken as-of a
    reference date (clamped to `end`), and the % lacking coverage is
    `|lacking| / |members|` where a member is "lacking" if it has no cached
    price data at all, OR its cache is masked-truncated (see
    `PriceAvailability.masked_end`) before that year's reference date while
    still being a constituent then. A year with zero point-in-time members
    (e.g. `asof` precedes all membership data) reports 0%, not an error.

    `sample_dates` (additive, M04 work packet - plans/QUANT-NOTES.md's M02
    carried item): when given, each year's reference date is the LATEST
    `sample_dates` entry falling in that calendar year (e.g. the backtest
    engine's own rebalance dates), rather than that year's Dec 31 - sampling
    membership/coverage at the dates a strategy actually acts on, rather
    than an arbitrary calendar boundary the backtest may never touch. A year
    with no `sample_dates` entry falls back to the Dec-31-or-`end` behavior
    (unchanged from before this parameter existed). `sample_dates=None`
    (default) is byte-identical to the pre-existing Dec-31-every-year
    behavior - every caller and test written before this parameter existed
    is unaffected.
    """
    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
    sample_index = pd.DatetimeIndex(sample_dates) if sample_dates is not None else None

    by_year: dict[int, float] = {}
    masked_tickers: dict[int, list[str]] = {}
    quarantined_tickers: dict[int, list[str]] = {}
    masked_start_tickers: dict[int, list[str]] = {}

    for year in range(start_ts.year, end_ts.year + 1):
        year_end = min(pd.Timestamp(year=year, month=12, day=31), end_ts)
        if sample_index is not None:
            in_year = sample_index[sample_index.year == year]
            if len(in_year) > 0:
                year_end = min(in_year.max(), end_ts)
        if year_end < start_ts:
            continue

        members = _as_of_membership(universe_history, year_end)
        if not members:
            by_year[year] = 0.0
            masked_tickers[year] = []
            quarantined_tickers[year] = []
            masked_start_tickers[year] = []
            continue

        lacking: set[str] = set()
        masked_this_year: list[str] = []
        quarantined_this_year: list[str] = []
        masked_start_this_year: list[str] = []
        for ticker in members:
            avail = price_availability.get(ticker)
            if avail is None or not avail.has_data:
                lacking.add(ticker)
                if avail is not None and avail.quarantined:
                    quarantined_this_year.append(ticker)
                continue
            if (
                avail.masked_end is not None
                and avail.last_bar_date is not None
                and avail.last_bar_date < year_end <= avail.masked_end
            ):
                lacking.add(ticker)
                masked_this_year.append(ticker)
            if avail.masked_start is not None and year_end < avail.masked_start:
                lacking.add(ticker)
                masked_start_this_year.append(ticker)

        by_year[year] = 100.0 * len(lacking) / len(members)
        masked_tickers[year] = sorted(masked_this_year)
        quarantined_tickers[year] = sorted(quarantined_this_year)
        masked_start_tickers[year] = sorted(masked_start_this_year)

    by_year_series = pd.Series(by_year, name="pct_lacking_coverage", dtype=float).sort_index()
    overall_bound = float(by_year_series.max()) if not by_year_series.empty else 0.0
    return CoverageReport(
        by_year=by_year_series,
        overall_bound=overall_bound,
        masked_tickers=masked_tickers,
        quarantined_tickers=quarantined_tickers,
        masked_start_tickers=masked_start_tickers,
    )


def price_availability_from_cache(
    tickers: list[str],
    cache_dir: Path,
    membership_start_by_ticker_map: dict[str, pd.Timestamp] | None = None,
) -> dict[str, PriceAvailability]:
    """Build `coverage_gap`'s `price_availability` argument directly from the
    on-disk price cache (M04 work packet / plans/QUANT-NOTES.md's M02
    carried item 3(ii)) - without this, `PriceAvailability.masked_end` is
    never populated and `coverage_gap` can never surface a masked-truncation
    (see this module's docstring's "masked truncation" hazard).

    For each ticker: `has_data=False` if there is no cached price file at
    all; else `last_bar_date` = the cache's most recent bar, and
    `masked_end` = the cache's sidecar-recorded `requested_end` (data/cache.py's
    `write_price_cache_meta`) IF that is later than `last_bar_date` (a
    request that reached further than the data actually goes - the signature
    of a frozen truncation), else `None` (no metadata, or the metadata
    doesn't exceed the real last bar - nothing masked).

    `membership_start_by_ticker_map` (optional, from `data/quality.py`'s
    `membership_start_by_ticker`): when supplied, ALSO populates
    `masked_start` - the START-side mirror of `masked_end` - whenever the
    ticker's point-in-time membership began before its cached history's
    first bar (a reused-symbol new listing's own clean data cannot stand in
    for the original constituent's earlier history it displaced).

    A ticker whose sidecar carries `quarantined: true` (M04b quant-gate
    VERDICT.md cycle 1 finding 2 - `data/quality.py`'s `scan_price_cache`)
    ALWAYS reports `has_data=False, quarantined=True` here, REGARDLESS of
    what its parquet actually contains - quarantine means the cached data is
    judged untrustworthy (a merged/reused-symbol series), and a strategy
    genuinely cannot see it (`has_sufficient_price_cache` refuses to serve
    it), so survivorship must count it exactly like "no data at all", not
    "fully covered".
    """
    result: dict[str, PriceAvailability] = {}
    for ticker in tickers:
        meta = read_json_meta(price_meta_path(ticker, cache_dir))
        if meta is not None and meta.get("quarantined"):
            result[ticker] = PriceAvailability(has_data=False, quarantined=True)
            continue

        cached = read_cache(price_cache_path(ticker, cache_dir))
        if cached is None or cached.empty:
            result[ticker] = PriceAvailability(has_data=False)
            continue

        last_bar_date = pd.Timestamp(cached.index.max())
        first_bar_date = pd.Timestamp(cached.index.min())
        masked_end: pd.Timestamp | None = None
        if meta is not None and "requested_end" in meta:
            requested_end = pd.Timestamp(meta["requested_end"])
            if requested_end > last_bar_date:
                masked_end = requested_end

        masked_start: pd.Timestamp | None = None
        if membership_start_by_ticker_map is not None:
            membership_start = membership_start_by_ticker_map.get(ticker)
            if membership_start is not None and membership_start < first_bar_date:
                masked_start = first_bar_date

        result[ticker] = PriceAvailability(
            has_data=True,
            last_bar_date=last_bar_date,
            masked_end=masked_end,
            masked_start=masked_start,
        )
    return result
