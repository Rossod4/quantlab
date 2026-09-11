from __future__ import annotations

import pandas as pd
import pytest

from quantlab.data.cache import price_cache_path, write_cache, write_price_cache_meta
from quantlab.data.survivorship import (
    CoverageReport,
    PriceAvailability,
    coverage_gap,
    price_availability_from_cache,
)


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


# -- sample_dates (M04 additive param) ---------------------------------------


def test_coverage_gap_sample_dates_uses_the_latest_sample_in_year_not_the_first():
    """`sample_dates` (backtest/engine.py passes its rebalance dates) must
    use the LATEST sample falling in a year as that year's reference date,
    not merely "a" sample. A's cache is masked-truncated (real data ends
    2020-11-15, metadata claims coverage through 2020-12-31 - see
    `PriceAvailability.masked_end`'s docstring): using the correct LATEST
    sample (2020-12-15) still falls inside the masked window (11-15 < 12-15
    <= 12-31) -> lacking; an implementation that incorrectly picked the
    FIRST sample (2020-10-01, before A's real last bar) would wrongly say
    covered instead."""
    universe_history = pd.DataFrame({"tickers": [["A"]]}, index=pd.DatetimeIndex(["2019-01-01"]))
    availability = {
        "A": PriceAvailability(
            has_data=True,
            last_bar_date=pd.Timestamp("2020-11-15"),
            masked_end=pd.Timestamp("2020-12-31"),
        )
    }
    sample_dates = pd.DatetimeIndex(["2020-10-01", "2020-12-15"])

    report = coverage_gap(
        universe_history, availability, "2020-01-01", "2020-12-31", sample_dates=sample_dates
    )

    assert report.by_year.loc[2020] == pytest.approx(100.0)
    assert "A" in report.masked_tickers[2020]


def test_coverage_gap_sample_dates_can_flip_the_verdict_for_a_year():
    """A ticker's masked-truncation status can flip once membership/coverage
    is sampled at the actual rebalance dates instead of Dec 31: if every
    sample in the year falls BEFORE the ticker's real last bar, the masked
    metadata's LATER claimed range never actually gets tested against a
    date the data doesn't cover, so it counts as covered."""
    universe_history = pd.DataFrame({"tickers": [["A"]]}, index=pd.DatetimeIndex(["2019-01-01"]))
    availability = {
        "A": PriceAvailability(
            has_data=True,
            last_bar_date=pd.Timestamp("2020-11-15"),
            masked_end=pd.Timestamp("2020-12-31"),
        )
    }
    sample_dates = pd.DatetimeIndex(["2020-10-30"])  # before A's real last bar

    without_sample_dates = coverage_gap(universe_history, availability, "2020-01-01", "2020-12-31")
    with_sample_dates = coverage_gap(
        universe_history, availability, "2020-01-01", "2020-12-31", sample_dates=sample_dates
    )

    # Dec-31 reference (default): 11-15 < 12-31 <= 12-31 -> lacking (masked).
    assert without_sample_dates.by_year.loc[2020] == pytest.approx(100.0)
    # 2020-10-30 reference: 11-15 < 10-30 is FALSE -> covered.
    assert with_sample_dates.by_year.loc[2020] == pytest.approx(0.0)


def test_coverage_gap_sample_dates_falls_back_to_dec_31_for_a_year_with_no_samples():
    """A year with no `sample_dates` entry at all keeps the pre-existing
    Dec-31-or-`end` behavior, byte-identical to `sample_dates=None`."""
    universe_history = pd.DataFrame({"tickers": [["A"]]}, index=pd.DatetimeIndex(["2019-01-01"]))
    availability = {"A": PriceAvailability(has_data=True, last_bar_date=pd.Timestamp("2019-12-31"))}
    # Only samples in 2020, none in 2019.
    sample_dates = pd.DatetimeIndex(["2020-06-30"])

    report = coverage_gap(
        universe_history, availability, "2019-01-01", "2020-12-31", sample_dates=sample_dates
    )

    assert report.by_year.loc[2019] == pytest.approx(0.0)  # falls back to Dec-31 -> covered


def test_coverage_gap_sample_dates_none_is_byte_identical_to_omitting_it():
    universe_history = _universe_history(["A", "B"], "2020-01-01")
    availability = {
        "A": PriceAvailability(has_data=True, last_bar_date=pd.Timestamp("2020-12-31")),
        "B": PriceAvailability(has_data=False),
    }

    default = coverage_gap(universe_history, availability, "2020-01-01", "2020-12-31")
    explicit_none = coverage_gap(
        universe_history, availability, "2020-01-01", "2020-12-31", sample_dates=None
    )

    pd.testing.assert_series_equal(default.by_year, explicit_none.by_year)
    assert default.overall_bound == explicit_none.overall_bound


# -- price_availability_from_cache (M04 new bridge function, REVIEW.md
# finding 4) ------------------------------------------------------------


def test_price_availability_from_cache_reports_no_data_for_a_ticker_with_no_cache_file(tmp_path):
    availability = price_availability_from_cache(["NEVER_CACHED"], tmp_path)
    assert availability["NEVER_CACHED"] == PriceAvailability(has_data=False)


def test_price_availability_from_cache_reports_last_bar_with_no_masking_when_metadata_matches(
    tmp_path,
):
    cached = pd.DataFrame(
        {
            "ticker": ["OK"],
            "open": [10.0],
            "high": [10.0],
            "low": [10.0],
            "close": [10.0],
            "adj_close": [10.0],
            "volume": [1000],
        },
        index=pd.DatetimeIndex(["2020-12-31"], name="date"),
    )
    write_cache(cached, price_cache_path("OK", tmp_path))
    write_price_cache_meta("OK", "2015-01-01", "2020-12-31", tmp_path)  # requested == last bar

    availability = price_availability_from_cache(["OK"], tmp_path)

    assert availability["OK"].has_data is True
    assert availability["OK"].last_bar_date == pd.Timestamp("2020-12-31")
    assert availability["OK"].masked_end is None


def test_price_availability_from_cache_surfaces_a_real_masked_truncation_end_to_end(tmp_path):
    """REVIEW.md finding 4 (blocker): a REAL on-disk cache (price parquet +
    sidecar `requested_end` beyond the last cached bar) must feed all the
    way through `price_availability_from_cache` into `coverage_gap`'s
    `masked_tickers` and move `overall_bound` - not just a hand-built
    `PriceAvailability` object (that only tests `coverage_gap` itself,
    pre-existing since M02 - see
    `test_coverage_gap_surfaces_cache_metadata_masked_truncation` above)."""
    cached = pd.DataFrame(
        {
            "ticker": ["MASKED"],
            "open": [10.0],
            "high": [10.0],
            "low": [10.0],
            "close": [10.0],
            "adj_close": [10.0],
            "volume": [1000],
        },
        index=pd.DatetimeIndex(["2019-06-01"], name="date"),
    )
    write_cache(cached, price_cache_path("MASKED", tmp_path))
    # Requested through 2021 - far beyond the real last bar (2019-06-01) -
    # the frozen-truncation hazard plans/QUANT-NOTES.md's M01 note describes.
    write_price_cache_meta("MASKED", "2015-01-01", "2021-12-31", tmp_path)

    availability = price_availability_from_cache(["MASKED", "NEVER_CACHED"], tmp_path)

    assert availability["MASKED"].has_data is True
    assert availability["MASKED"].last_bar_date == pd.Timestamp("2019-06-01")
    assert availability["MASKED"].masked_end == pd.Timestamp("2021-12-31")
    assert availability["NEVER_CACHED"].has_data is False

    universe_history = pd.DataFrame(
        {"tickers": [["MASKED", "NEVER_CACHED"]]}, index=pd.DatetimeIndex(["2019-01-01"])
    )
    report = coverage_gap(universe_history, availability, "2019-01-01", "2020-12-31")

    assert "MASKED" in report.masked_tickers[2020]
    # Both names lack usable coverage by 2020 (one masked, one never cached).
    assert report.overall_bound == pytest.approx(100.0)
