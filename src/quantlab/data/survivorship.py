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

import pandas as pd


@dataclass(frozen=True)
class PriceAvailability:
    """Per-ticker price cache availability, as needed by `coverage_gap()`.

    `has_data`: whether any cached price bars exist for this ticker at all.
    `last_bar_date`: the ticker's most recent cached bar (None if no data).
    `masked_end`: if the cache's sidecar metadata recorded that data was
        REQUESTED through this date, but `last_bar_date` is earlier, the gap
        between them is a "masked truncation" (see module docstring). None
        if no such metadata is known, or it doesn't exceed `last_bar_date`.
    """

    has_data: bool
    last_bar_date: pd.Timestamp | None = None
    masked_end: pd.Timestamp | None = None


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
    """

    by_year: pd.Series
    overall_bound: float
    masked_tickers: dict[int, list[str]] = field(default_factory=dict)


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
) -> CoverageReport:
    """Per-year % of point-in-time constituents lacking price data, plus an
    overall conservative bound.

    For each calendar year in [start, end], membership is taken as-of that
    year's end (clamped to `end`), and the % lacking coverage is
    `|lacking| / |members|` where a member is "lacking" if it has no cached
    price data at all, OR its cache is masked-truncated (see
    `PriceAvailability.masked_end`) before that year's reference date while
    still being a constituent then. A year with zero point-in-time members
    (e.g. `asof` precedes all membership data) reports 0%, not an error.
    """
    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)

    by_year: dict[int, float] = {}
    masked_tickers: dict[int, list[str]] = {}

    for year in range(start_ts.year, end_ts.year + 1):
        year_end = min(pd.Timestamp(year=year, month=12, day=31), end_ts)
        if year_end < start_ts:
            continue

        members = _as_of_membership(universe_history, year_end)
        if not members:
            by_year[year] = 0.0
            masked_tickers[year] = []
            continue

        lacking: set[str] = set()
        masked_this_year: list[str] = []
        for ticker in members:
            avail = price_availability.get(ticker)
            if avail is None or not avail.has_data:
                lacking.add(ticker)
                continue
            if (
                avail.masked_end is not None
                and avail.last_bar_date is not None
                and avail.last_bar_date < year_end <= avail.masked_end
            ):
                lacking.add(ticker)
                masked_this_year.append(ticker)

        by_year[year] = 100.0 * len(lacking) / len(members)
        masked_tickers[year] = sorted(masked_this_year)

    by_year_series = pd.Series(by_year, name="pct_lacking_coverage", dtype=float).sort_index()
    overall_bound = float(by_year_series.max()) if not by_year_series.empty else 0.0
    return CoverageReport(
        by_year=by_year_series, overall_bound=overall_bound, masked_tickers=masked_tickers
    )
