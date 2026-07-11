from __future__ import annotations

import pandas as pd
import pytest

from quantlab.data.survivorship import CoverageReport, PriceAvailability, coverage_gap


def _universe_history(tickers: list[str], asof: str = "2020-01-01") -> pd.DataFrame:
    return pd.DataFrame({"tickers": [tickers]}, index=pd.DatetimeIndex([asof]))


def test_coverage_gap_reports_30_percent_for_3_of_10_missing_prices():
    tickers = [f"T{i}" for i in range(10)]
    universe_history = _universe_history(tickers, "2020-01-01")
    availability = {
        t: PriceAvailability(has_data=True, last_bar_date=pd.Timestamp("2020-12-31"))
        for t in tickers
    }
    for missing in tickers[:3]:
        availability[missing] = PriceAvailability(has_data=False)

    report = coverage_gap(universe_history, availability, "2020-01-01", "2020-12-31")

    assert isinstance(report, CoverageReport)
    assert report.by_year.loc[2020] == pytest.approx(30.0)
    assert report.overall_bound == pytest.approx(30.0)


def test_coverage_gap_reports_zero_when_all_covered():
    tickers = [f"T{i}" for i in range(5)]
    universe_history = _universe_history(tickers, "2020-01-01")
    availability = {
        t: PriceAvailability(has_data=True, last_bar_date=pd.Timestamp("2020-12-31"))
        for t in tickers
    }

    report = coverage_gap(universe_history, availability, "2020-01-01", "2020-12-31")

    assert report.by_year.loc[2020] == 0.0
    assert report.overall_bound == 0.0


def test_coverage_gap_reports_zero_when_no_point_in_time_members():
    universe_history = pd.DataFrame({"tickers": []}, index=pd.DatetimeIndex([]))

    report = coverage_gap(universe_history, {}, "2020-01-01", "2020-12-31")

    assert report.by_year.loc[2020] == 0.0
    assert report.overall_bound == 0.0


def test_coverage_gap_surfaces_cache_metadata_masked_truncation():
    """A ticker whose cache metadata claims coverage through a wide
    REQUESTED range, but whose actual last bar stops years earlier, while
    the point-in-time constituents say it was STILL a member after that cut
    -off: this must count as coverage loss (and be reported in
    `masked_tickers`), not be silently treated as "has data" just because
    `has_data=True`."""
    universe_history = pd.DataFrame(
        {"tickers": [["MASKED", "OK"]]}, index=pd.DatetimeIndex(["2019-01-01"])
    )
    availability = {
        # Real data stopped in 2019, but the cache metadata (recorded when
        # the fetch was REQUESTED) claims coverage through 2021 - the exact
        # "frozen truncation" scenario from plans/QUANT-NOTES.md's M01 note.
        "MASKED": PriceAvailability(
            has_data=True,
            last_bar_date=pd.Timestamp("2019-06-01"),
            masked_end=pd.Timestamp("2021-12-31"),
        ),
        "OK": PriceAvailability(has_data=True, last_bar_date=pd.Timestamp("2020-12-31")),
    }

    report = coverage_gap(universe_history, availability, "2019-01-01", "2020-12-31")

    # In 2020, MASKED's real data (stopped 2019-06-01) no longer covers the
    # year-end reference date, even though its cache metadata claims it
    # does through 2021 - so it must be counted as lacking coverage.
    assert report.by_year.loc[2020] == pytest.approx(50.0)
    assert report.masked_tickers[2020] == ["MASKED"]
    # In 2019, the reference date (2019-12-31) is still within the real
    # data range recorded on last_bar_date? No - last_bar_date is 2019-06-01,
    # so 2019 is also masked.
    assert "MASKED" in report.masked_tickers[2019]


def test_coverage_gap_multi_year_overall_bound_is_the_worst_year():
    universe_history = pd.DataFrame(
        {"tickers": [["A", "B", "C", "D"]]}, index=pd.DatetimeIndex(["2019-01-01"])
    )
    availability = {
        "A": PriceAvailability(has_data=True, last_bar_date=pd.Timestamp("2021-12-31")),
        "B": PriceAvailability(has_data=True, last_bar_date=pd.Timestamp("2021-12-31")),
        "C": PriceAvailability(has_data=True, last_bar_date=pd.Timestamp("2021-12-31")),
        "D": PriceAvailability(has_data=False),
    }

    report = coverage_gap(universe_history, availability, "2019-01-01", "2021-12-31")

    # D is missing every year -> 25% every year -> overall bound (max) 25%,
    # not an average across years diluted by better-covered ones.
    assert report.by_year.loc[2019] == pytest.approx(25.0)
    assert report.by_year.loc[2020] == pytest.approx(25.0)
    assert report.by_year.loc[2021] == pytest.approx(25.0)
    assert report.overall_bound == pytest.approx(25.0)
