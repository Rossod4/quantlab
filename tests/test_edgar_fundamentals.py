"""Unit tests for point-in-time SEC EDGAR fundamentals extraction
(src/quantlab/data/providers/edgar_fundamentals.py).

The first several sections below are adapted verbatim (same assertions, same
scenarios) from the old repo's tests/test_fundamentals.py - this is a parity
suite for FROZEN ported numerical logic, not new test design. Only the
import path changed. New sections at the bottom cover code that's new in
this milestone: `EdgarFundamentalsProvider` wiring, and a real-SEC-data
parity fixture.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from quantlab.data.cache import write_cache
from quantlab.data.providers.edgar_fundamentals import (
    EdgarFundamentalsProvider,
    PointInTimeFundamentals,
    _annual_growth,
    _flatten_company_facts,
    _most_recent_instant,
    _most_recent_instant_with_end,
    _total_debt,
    _ttm_duration,
    get_point_in_time_fundamentals,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def make_facts(rows: list[dict]) -> pd.DataFrame:
    """rows: list of dicts with keys tag, val, end, filed, and optionally
    start (omit/None for instant facts)."""
    df = pd.DataFrame(rows)
    for col in ["start", "end", "filed"]:
        if col not in df:
            df[col] = None
        df[col] = pd.to_datetime(df[col])
    return df


# --- _most_recent_instant / no-look-ahead ----------------------------------


def test_most_recent_instant_respects_filed_date():
    facts = make_facts(
        [
            {"tag": "StockholdersEquity", "val": 100.0, "end": "2020-03-31", "filed": "2020-05-01"},
            {"tag": "StockholdersEquity", "val": 110.0, "end": "2020-06-30", "filed": "2020-08-01"},
        ]
    )
    # As of 2020-06-01, only the Q1 fact has been filed - the Q2 fact
    # (filed 2020-08-01) must not be visible yet.
    value = _most_recent_instant(facts, ["StockholdersEquity"], pd.Timestamp("2020-06-01"))
    assert value == 100.0


def test_most_recent_instant_picks_freshest_end_among_visible_facts():
    facts = make_facts(
        [
            {"tag": "StockholdersEquity", "val": 100.0, "end": "2020-03-31", "filed": "2020-05-01"},
            {"tag": "StockholdersEquity", "val": 110.0, "end": "2020-06-30", "filed": "2020-08-01"},
        ]
    )
    value = _most_recent_instant(facts, ["StockholdersEquity"], pd.Timestamp("2020-09-01"))
    assert value == 110.0


def test_most_recent_instant_pools_alternate_tags_by_freshness():
    """Reconstructs the real Apple debt-tag-switch scenario: a company can
    stop updating one tag and start updating an alternate tag for the same
    concept. The freshest fact across BOTH candidate tags should win, not
    whichever tag happens to be tried first."""
    facts = make_facts(
        [
            {"tag": "LongTermDebt", "val": 40.0, "end": "2015-03-28", "filed": "2015-04-28"},
            {
                "tag": "LongTermDebtNoncurrent",
                "val": 101.0,
                "end": "2018-03-31",
                "filed": "2018-05-02",
            },
        ]
    )
    value, end = _most_recent_instant_with_end(
        facts, ["LongTermDebt", "LongTermDebtNoncurrent"], pd.Timestamp("2018-06-30")
    )
    assert value == 101.0
    assert end == pd.Timestamp("2018-03-31")


def test_most_recent_instant_none_when_no_data_visible():
    facts = make_facts(
        [{"tag": "StockholdersEquity", "val": 100.0, "end": "2020-03-31", "filed": "2020-05-01"}]
    )
    assert _most_recent_instant(facts, ["StockholdersEquity"], pd.Timestamp("2020-01-01")) is None


# --- _total_debt -------------------------------------------------------------


def test_total_debt_sums_split_current_and_noncurrent():
    facts = make_facts(
        [
            {
                "tag": "LongTermDebtNoncurrent",
                "val": 100.0,
                "end": "2020-06-30",
                "filed": "2020-08-01",
            },
            {"tag": "LongTermDebtCurrent", "val": 10.0, "end": "2020-06-30", "filed": "2020-08-01"},
        ]
    )
    assert _total_debt(facts, pd.Timestamp("2020-09-01")) == 110.0


def test_total_debt_prefers_fresher_source_over_combined_tag():
    """The Apple scenario: a stale combined "LongTermDebt" figure exists,
    but a fresher split noncurrent+current figure is available - the
    fresher one should be used, not the combined tag just because it
    technically has data."""
    facts = make_facts(
        [
            {"tag": "LongTermDebt", "val": 40.0, "end": "2015-03-28", "filed": "2015-04-28"},
            {
                "tag": "LongTermDebtNoncurrent",
                "val": 101.0,
                "end": "2018-03-31",
                "filed": "2018-05-02",
            },
            {"tag": "LongTermDebtCurrent", "val": 8.5, "end": "2018-03-31", "filed": "2018-05-02"},
        ]
    )
    assert _total_debt(facts, pd.Timestamp("2018-06-30")) == pytest.approx(109.5)


def test_total_debt_zero_when_no_debt_tags_present():
    facts = make_facts(
        [{"tag": "StockholdersEquity", "val": 100.0, "end": "2020-06-30", "filed": "2020-08-01"}]
    )
    assert _total_debt(facts, pd.Timestamp("2020-09-01")) == 0.0


# --- _ttm_duration -------------------------------------------------------------


def _quarterly_eps_facts(values: list[float], filed_lag_days: int = 30) -> list[dict]:
    """Four non-overlapping ~90-day quarters ending on the given dates."""
    ends = ["2020-03-31", "2020-06-30", "2020-09-30", "2020-12-31"]
    starts = ["2020-01-01", "2020-04-01", "2020-07-01", "2020-10-01"]
    rows = []
    for start, end, val in zip(starts, ends, values, strict=True):
        filed = pd.Timestamp(end) + pd.Timedelta(days=filed_lag_days)
        rows.append(
            {
                "tag": "EarningsPerShareDiluted",
                "val": val,
                "start": start,
                "end": end,
                "filed": filed,
            }
        )
    return rows


def test_ttm_duration_sums_four_quarters():
    facts = make_facts(_quarterly_eps_facts([1.0, 1.1, 1.2, 1.3]))
    ttm = _ttm_duration(facts, ["EarningsPerShareDiluted"], pd.Timestamp("2021-02-01"))
    assert ttm == pytest.approx(4.6)


def test_ttm_duration_excludes_quarters_not_yet_filed():
    facts = make_facts(_quarterly_eps_facts([1.0, 1.1, 1.2, 1.3]))
    # Only the first three quarters have been filed by this date (Q4 filed
    # 2021-01-30, i.e. 2020-12-31 + 30 days).
    ttm = _ttm_duration(facts, ["EarningsPerShareDiluted"], pd.Timestamp("2021-01-01"))
    assert ttm is None  # fewer than 4 quarters, and no annual fallback present


def test_ttm_duration_falls_back_to_annual_when_no_quarterly_data():
    facts = make_facts(
        [
            {
                "tag": "EarningsPerShareDiluted",
                "val": 4.5,
                "start": "2020-01-01",
                "end": "2020-12-31",
                "filed": "2021-02-15",
            }
        ]
    )
    ttm = _ttm_duration(facts, ["EarningsPerShareDiluted"], pd.Timestamp("2021-03-01"))
    assert ttm == 4.5


def test_ttm_duration_restatement_uses_latest_filed_value_per_quarter():
    rows = _quarterly_eps_facts([1.0, 1.1, 1.2, 1.3])
    # A restated Q1 figure, filed later, for the same `end` date.
    rows.append(
        {
            "tag": "EarningsPerShareDiluted",
            "val": 0.9,
            "start": "2020-01-01",
            "end": "2020-03-31",
            "filed": "2020-08-01",
        }
    )
    facts = make_facts(rows)
    ttm = _ttm_duration(facts, ["EarningsPerShareDiluted"], pd.Timestamp("2021-02-01"))
    assert ttm == pytest.approx(0.9 + 1.1 + 1.2 + 1.3)


# --- _annual_growth -------------------------------------------------------------


def test_annual_growth_computed_from_two_most_recent_annual_facts():
    facts = make_facts(
        [
            {
                "tag": "EarningsPerShareDiluted",
                "val": 4.0,
                "start": "2018-01-01",
                "end": "2018-12-31",
                "filed": "2019-02-01",
            },
            {
                "tag": "EarningsPerShareDiluted",
                "val": 5.0,
                "start": "2019-01-01",
                "end": "2019-12-31",
                "filed": "2020-02-01",
            },
        ]
    )
    growth = _annual_growth(facts, ["EarningsPerShareDiluted"], pd.Timestamp("2020-06-01"))
    assert growth == pytest.approx(0.25)


def test_annual_growth_none_with_fewer_than_two_years():
    facts = make_facts(
        [
            {
                "tag": "EarningsPerShareDiluted",
                "val": 4.0,
                "start": "2018-01-01",
                "end": "2018-12-31",
                "filed": "2019-02-01",
            }
        ]
    )
    assert _annual_growth(facts, ["EarningsPerShareDiluted"], pd.Timestamp("2020-06-01")) is None


def test_annual_growth_none_when_prior_year_zero():
    facts = make_facts(
        [
            {
                "tag": "EarningsPerShareDiluted",
                "val": 0.0,
                "start": "2018-01-01",
                "end": "2018-12-31",
                "filed": "2019-02-01",
            },
            {
                "tag": "EarningsPerShareDiluted",
                "val": 5.0,
                "start": "2019-01-01",
                "end": "2019-12-31",
                "filed": "2020-02-01",
            },
        ]
    )
    assert _annual_growth(facts, ["EarningsPerShareDiluted"], pd.Timestamp("2020-06-01")) is None


# --- get_point_in_time_fundamentals (integration) ---------------------------


def test_diluted_eps_preferred_over_basic_when_both_present():
    """Diluted and basic EPS are reported simultaneously every period -
    pooling them would let a growth/TTM calculation mix a diluted-EPS year
    against a basic-EPS year. Diluted must be used exclusively when
    available."""
    facts = make_facts(
        [
            {
                "tag": "EarningsPerShareDiluted",
                "val": 4.0,
                "start": "2018-01-01",
                "end": "2018-12-31",
                "filed": "2019-02-01",
            },
            {
                "tag": "EarningsPerShareBasic",
                "val": 4.2,
                "start": "2018-01-01",
                "end": "2018-12-31",
                "filed": "2019-02-01",
            },
            {
                "tag": "EarningsPerShareDiluted",
                "val": 5.0,
                "start": "2019-01-01",
                "end": "2019-12-31",
                "filed": "2020-02-01",
            },
            {
                "tag": "EarningsPerShareBasic",
                "val": 5.3,
                "start": "2019-01-01",
                "end": "2019-12-31",
                "filed": "2020-02-01",
            },
        ]
    )
    result = get_point_in_time_fundamentals(facts, "2020-06-01")
    assert result.annual_eps_growth == pytest.approx(5.0 / 4.0 - 1)


def test_basic_eps_used_as_fallback_when_diluted_entirely_absent():
    facts = make_facts(
        [
            {
                "tag": "EarningsPerShareBasic",
                "val": 4.0,
                "start": "2018-01-01",
                "end": "2018-12-31",
                "filed": "2019-02-01",
            },
            {
                "tag": "EarningsPerShareBasic",
                "val": 5.0,
                "start": "2019-01-01",
                "end": "2019-12-31",
                "filed": "2020-02-01",
            },
        ]
    )
    result = get_point_in_time_fundamentals(facts, "2020-06-01")
    assert result.annual_eps_growth == pytest.approx(0.25)


def test_get_point_in_time_fundamentals_no_lookahead_on_any_field():
    """A fact filed after as_of_date must not leak into any field of the
    result - the core invariant this whole module exists to enforce."""
    facts = make_facts(
        [{"tag": "StockholdersEquity", "val": 999.0, "end": "2025-01-01", "filed": "2025-02-01"}]
    )
    result = get_point_in_time_fundamentals(facts, "2024-01-01")
    assert result.stockholders_equity is None


def test_get_point_in_time_fundamentals_missing_ebitda_inputs_returns_none():
    facts = make_facts(
        [{"tag": "StockholdersEquity", "val": 100.0, "end": "2020-06-30", "filed": "2020-08-01"}]
    )
    result = get_point_in_time_fundamentals(facts, "2020-09-01")
    assert isinstance(result, PointInTimeFundamentals)
    assert result.ttm_ebitda is None
    assert result.total_debt == 0.0


# --- new in this milestone: EdgarFundamentalsProvider wiring ----------------


def test_provider_returns_all_none_fields_when_ticker_has_no_cik():
    provider = EdgarFundamentalsProvider(cache_dir=Path("unused"))
    provider._cik_map = {}  # pretend the CIK map was already loaded, empty

    result = provider.get_pit_fundamentals("NOPE", "2020-01-01")

    assert result["total_debt"] == 0.0
    assert result["stockholders_equity"] is None


def test_provider_reads_cached_facts_and_extracts_point_in_time(tmp_path):
    facts = make_facts(
        [{"tag": "StockholdersEquity", "val": 42.0, "end": "2020-06-30", "filed": "2020-08-01"}]
    )
    write_cache(facts, tmp_path / "fundamentals" / "AAA.parquet")
    provider = EdgarFundamentalsProvider(cache_dir=tmp_path)
    provider._cik_map = {"AAA": 12345}  # skip the network ticker-CIK fetch

    result = provider.get_pit_fundamentals("AAA", "2020-09-01")

    assert result["stockholders_equity"] == 42.0


def test_provider_no_lookahead_end_to_end(tmp_path):
    facts = make_facts(
        [{"tag": "StockholdersEquity", "val": 42.0, "end": "2020-06-30", "filed": "2020-08-01"}]
    )
    write_cache(facts, tmp_path / "fundamentals" / "AAA.parquet")
    provider = EdgarFundamentalsProvider(cache_dir=tmp_path)
    provider._cik_map = {"AAA": 12345}

    result = provider.get_pit_fundamentals("AAA", "2020-07-01")  # before filed date

    assert result["stockholders_equity"] is None


# --- parity fixture: real SEC EDGAR companyfacts snapshot -------------------


def test_edgar_parity_nathans_famous_real_fixture():
    """Parity fixture: a real SEC EDGAR companyfacts snapshot for Nathan's
    Famous, Inc. (ticker NATH, CIK 0000069733), trimmed to this module's
    TAGS_OF_INTEREST and to facts with `end` >= 2018-01-01 to keep the
    committed fixture small (tests/fixtures/edgar/nath_companyfacts.json).
    Retrieved 2026-07-10 from
    https://data.sec.gov/api/xbrl/companyfacts/CIK0000069733.json (SEC's
    public XBRL API, no API key required).

    Expected values below were computed OFFLINE by running the OLD repo's
    module (MomentumValueStrategy/src/data_layer/fundamentals.py,
    `get_point_in_time_fundamentals`) directly against this exact fixture
    at asof=2022-06-01, then hard-coded here to lock in ported-logic parity
    between the old and new modules.
    """
    raw = json.loads((FIXTURES_DIR / "edgar" / "nath_companyfacts.json").read_text())
    facts = _flatten_company_facts(raw)

    result = get_point_in_time_fundamentals(facts, "2022-06-01")

    assert result.shares_outstanding == pytest.approx(4115154.0)
    assert result.stockholders_equity == pytest.approx(-55301000.0)
    assert result.ttm_eps == pytest.approx(3.11)
    assert result.ttm_ebitda == pytest.approx(29252000.0)
    assert result.total_debt == pytest.approx(147349000.0)
    assert result.cash == pytest.approx(86168000.0)
    assert result.annual_eps_growth == pytest.approx(-0.15673981191222575)
