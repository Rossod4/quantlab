"""Unit tests for point-in-time S&P 500 constituents logic.

Most tests use small synthetic in-memory tables (offline, deterministic).
Acceptance-criteria parity tests use the committed fixture CSV
(tests/fixtures/constituents_slice.csv) with hand-derived expectations.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import requests

from quantlab.data.providers.sp500_constituents import (
    DEFAULT_CONSTITUENTS_URL,
    SP500CommunityConstituentsProvider,
    _download_constituents_csv,
    _membership_from_table,
    normalize_ticker,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def make_table(rows: dict) -> pd.DataFrame:
    """rows: {date_str: [tickers]}"""
    dates = pd.to_datetime(list(rows.keys()))
    table = pd.DataFrame({"tickers": list(rows.values())}, index=dates).sort_index()
    return table


# --- synthetic-table tests (ported from the old repo) ----------------------


def test_membership_differs_across_dates():
    table = make_table({"2012-01-01": ["A", "B", "C"], "2022-01-01": ["A", "D", "E"]})
    members_2012 = _membership_from_table(table, "2012-06-15")
    members_2022 = _membership_from_table(table, "2022-06-15")
    assert set(members_2012) == {"A", "B", "C"}
    assert set(members_2022) == {"A", "D", "E"}
    assert members_2012 != members_2022


def test_as_of_lookup_uses_most_recent_prior_row():
    table = make_table(
        {"2020-01-01": ["A", "B"], "2020-06-01": ["A", "C"], "2021-01-01": ["A", "D"]}
    )
    assert set(_membership_from_table(table, "2020-08-15")) == {"A", "C"}


def test_no_lookahead_future_row_not_used_for_earlier_date():
    """Core no-look-ahead invariant: a rebalance on date t must never see a
    membership change recorded after t."""
    table = make_table({"2020-01-01": ["A", "B"], "2025-01-01": ["A", "ZZZZ_FUTURE_ONLY"]})
    members = _membership_from_table(table, "2020-06-01")
    assert "ZZZZ_FUTURE_ONLY" not in members
    assert set(members) == {"A", "B"}


def test_date_before_earliest_raises():
    table = make_table({"2000-01-01": ["A", "B"]})
    with pytest.raises(ValueError):
        _membership_from_table(table, "1999-01-01")


def test_normalize_ticker_converts_dot_to_hyphen():
    assert normalize_ticker("BF.B") == "BF-B"
    assert normalize_ticker("BRK.B") == "BRK-B"
    assert normalize_ticker("AAPL") == "AAPL"


def test_membership_applies_normalization():
    table = make_table({"2020-01-01": ["BF.B", "AAPL"]})
    members = _membership_from_table(table, "2020-06-01")
    assert "BF-B" in members
    assert "BF.B" not in members


# --- provider tests over the committed fixture CSV --------------------------


@pytest.fixture
def provider(tmp_path) -> SP500CommunityConstituentsProvider:
    p = SP500CommunityConstituentsProvider(cache_dir=tmp_path)
    # Bypass the network entirely: seed the provider's own cache file with
    # the fixture CSV, parsed exactly as `_download_constituents_csv` would.
    raw = pd.read_csv(FIXTURES_DIR / "constituents_slice.csv")
    raw["date"] = pd.to_datetime(raw["date"])
    raw["tickers"] = raw["tickers"].str.split(",")
    table = raw.set_index("date").sort_index()[["tickers"]]
    from quantlab.data.cache import write_cache

    write_cache(table, tmp_path / "sp500_constituents.parquet")
    return p


def test_fixture_membership_between_change_rows_uses_earlier_row(provider):
    """asof 2019-01-01 falls strictly between the 2018-06-07 and 2020-09-21
    fixture rows - must return the 2018-06-07 row's (normalized) membership,
    with no look-ahead to the 2020-09-21 row's TSLA addition."""
    members = provider.membership("2019-01-01")
    assert set(members) == {"AAPL", "MSFT", "XOM", "BRK-B", "JPM"}
    assert "TSLA" not in members


def test_fixture_membership_after_last_row(provider):
    """asof after the last fixture row (2023-01-10) returns that row's
    membership."""
    members = provider.membership("2024-01-01")
    assert set(members) == {"AAPL", "MSFT", "BRK-B", "TSLA", "NVDA"}


def test_fixture_membership_before_first_row_raises(provider):
    """asof before the fixture's earliest row (2015-03-15): matches the old
    repo's behavior of raising ValueError - there is no valid point-in-time
    membership to return before any data exists."""
    with pytest.raises(ValueError):
        provider.membership("2014-01-01")


def test_fixture_membership_history_window(provider):
    history = provider.membership_history("2018-01-01", "2021-01-01")
    assert list(history.index) == [pd.Timestamp("2018-06-07"), pd.Timestamp("2020-09-21")]
    expected = ["AAPL", "MSFT", "XOM", "BRK-B", "JPM"]
    assert history.loc[pd.Timestamp("2018-06-07"), "tickers"] == expected


# --- network tier ------------------------------------------------------------


@pytest.mark.network
def test_real_constituents_csv_download():
    response_table = _download_constituents_csv(DEFAULT_CONSTITUENTS_URL)
    assert not response_table.empty
    assert "tickers" in response_table.columns
    assert isinstance(response_table.index, pd.DatetimeIndex)


@pytest.mark.network
def test_real_constituents_url_reachable():
    response = requests.get(DEFAULT_CONSTITUENTS_URL, timeout=60)
    response.raise_for_status()
