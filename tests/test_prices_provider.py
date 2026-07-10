"""Unit tests for YFinancePriceProvider's cache/windowing logic.

Actual yfinance downloads are deliberately NOT exercised in the offline
tests below - like the rest of the suite, they run entirely from fixture
cache files. `_download_batch` is monkeypatched to fail loudly if a code
path unexpectedly reaches the network. A single real-network test at the
bottom is marked `@pytest.mark.network` and excluded by default.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import quantlab.data.providers.yfinance_prices as yfinance_prices_module
from quantlab.data.cache import price_cache_path, write_price_cache_meta
from quantlab.data.providers.yfinance_prices import YFinancePriceProvider

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _write_fake_cache(cache_dir, ticker: str, start: str, end: str) -> pd.DataFrame:
    """Create a cached file covering [start, end] for `ticker`, in the same
    raw layout YFinancePriceProvider caches (Yahoo-style capitalized
    columns, indexed by date)."""
    dates = pd.date_range(start, end, freq="B")
    df = pd.DataFrame(
        {
            "Open": [float(i) for i in range(1, len(dates) + 1)],
            "High": [float(i) + 0.5 for i in range(1, len(dates) + 1)],
            "Low": [float(i) - 0.5 for i in range(1, len(dates) + 1)],
            "Close": [float(i) for i in range(1, len(dates) + 1)],
            "Adj Close": [float(i) for i in range(1, len(dates) + 1)],
            "Volume": [1000 * i for i in range(1, len(dates) + 1)],
        },
        index=dates,
    )
    path = price_cache_path(ticker, cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path)
    return df


@pytest.fixture
def no_network(monkeypatch):
    """Make any attempted yfinance download fail the test loudly - used to
    prove a code path is served entirely from cache."""

    def _fail(*args, **kwargs):
        raise AssertionError("network download attempted - cache should have been used")

    monkeypatch.setattr(yfinance_prices_module, "_download_batch", _fail)


def test_get_prices_returns_long_format_columns(tmp_path, no_network):
    _write_fake_cache(tmp_path, "TEST", "2020-01-01", "2020-12-31")
    provider = YFinancePriceProvider(cache_dir=tmp_path)

    panel = provider.get_prices(["TEST"], "2020-01-01", "2020-12-31")

    assert list(panel.columns) == ["ticker", "open", "high", "low", "close", "adj_close", "volume"]
    assert isinstance(panel.index, pd.DatetimeIndex)


def test_get_prices_trims_wider_cache_to_requested_window(tmp_path, no_network):
    """Regression test: a cached file can cover a much wider range than a
    call asks for (e.g. a benchmark cached from a strategy's warmup start).
    The returned panel must be trimmed to the requested window."""
    _write_fake_cache(tmp_path, "TEST", "2010-12-01", "2013-06-30")
    provider = YFinancePriceProvider(cache_dir=tmp_path)

    panel = provider.get_prices(["TEST"], "2012-01-01", "2012-12-31")

    assert panel.index.min() >= pd.Timestamp("2012-01-01")
    assert panel.index.max() <= pd.Timestamp("2012-12-31")


def test_get_prices_values_unchanged_inside_window(tmp_path, no_network):
    """Trimming must only cut rows outside the window, never alter values
    inside it."""
    full = _write_fake_cache(tmp_path, "TEST", "2010-12-01", "2013-06-30")
    provider = YFinancePriceProvider(cache_dir=tmp_path)

    panel = provider.get_prices(["TEST"], "2012-01-01", "2012-12-31")

    expected_adj_close = full.loc["2012-01-01":"2012-12-31", "Adj Close"]
    pd.testing.assert_series_equal(
        panel["adj_close"], expected_adj_close, check_names=False, check_freq=False
    )


def test_delisted_ticker_served_from_cache_via_metadata(tmp_path, no_network):
    """A ticker delisted mid-window has data stopping years before the
    requested end date. With sidecar metadata recording that the cache was
    FETCHED for the full window, it must be served from cache - not
    re-fetched on every run."""
    _write_fake_cache(tmp_path, "GONE", "2012-01-03", "2015-06-30")
    write_price_cache_meta("GONE", "2012-01-01", "2026-06-30", tmp_path)
    provider = YFinancePriceProvider(cache_dir=tmp_path)

    panel = provider.get_prices(["GONE"], "2012-01-01", "2026-06-30")

    assert "GONE" in set(panel["ticker"])  # no_network fixture proves no download attempted
    assert panel.index.max() == pd.Timestamp("2015-06-30")


def test_stale_cache_without_metadata_triggers_refetch_attempt(tmp_path, monkeypatch):
    """The data-based fallback: an old cache file with NO metadata whose
    data stops early must still be treated as insufficient (it might be
    stale rather than delisted), so a re-fetch is attempted."""
    _write_fake_cache(tmp_path, "GONE", "2012-01-03", "2015-06-30")  # no meta file

    attempted = []

    def _record_and_fail(tickers, start, end):
        attempted.extend(tickers)
        raise ConnectionError("simulated network failure")

    monkeypatch.setattr(yfinance_prices_module, "_download_batch", _record_and_fail)
    provider = YFinancePriceProvider(cache_dir=tmp_path)

    panel = provider.get_prices(["GONE"], "2012-01-01", "2026-06-30")

    assert attempted == ["GONE"]  # the fallback correctly tried to refresh
    assert "GONE" not in set(panel["ticker"])  # whole-batch failure: ticker absent


def test_get_prices_reads_committed_fixture_cache_exactly(tmp_path, no_network):
    """Uses the committed tests/fixtures/prices_slice.parquet directly as a
    ticker's cache file (rather than a synthetic in-test frame), proving
    the provider reads a real on-disk cache layout correctly end to end."""
    fixture = pd.read_parquet(FIXTURES_DIR / "prices_slice.parquet")
    path = price_cache_path("AAPL", tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fixture.to_parquet(path)
    write_price_cache_meta("AAPL", "2021-01-04", "2021-01-08", tmp_path)
    provider = YFinancePriceProvider(cache_dir=tmp_path)

    panel = provider.get_prices(["AAPL"], "2021-01-04", "2021-01-08")

    assert len(panel) == 5
    assert set(panel["ticker"]) == {"AAPL"}
    pd.testing.assert_series_equal(
        panel["adj_close"].reset_index(drop=True),
        fixture["Adj Close"].reset_index(drop=True),
        check_names=False,
    )
    pd.testing.assert_series_equal(
        panel["close"].reset_index(drop=True),
        fixture["Close"].reset_index(drop=True),
        check_names=False,
    )


def test_get_prices_empty_result_has_expected_columns(tmp_path, no_network):
    provider = YFinancePriceProvider(cache_dir=tmp_path)
    panel = provider.get_prices(["NOPE"], "2020-01-01", "2020-12-31")
    assert list(panel.columns) == ["ticker", "open", "high", "low", "close", "adj_close", "volume"]
    assert panel.empty


@pytest.mark.network
def test_real_yfinance_download_of_aapl(tmp_path):
    provider = YFinancePriceProvider(cache_dir=tmp_path)
    panel = provider.get_prices(["AAPL"], "2023-01-03", "2023-01-10")
    assert not panel.empty
    assert "AAPL" in set(panel["ticker"])
    assert (panel["adj_close"] > 0).all()
