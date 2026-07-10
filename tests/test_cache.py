from __future__ import annotations

import json

import pandas as pd

import quantlab.data.providers.yfinance_prices as yfinance_prices_module
from quantlab.data.cache import (
    has_sufficient_price_cache,
    price_cache_path,
    price_meta_path,
    read_cache,
    write_cache,
    write_price_cache_meta,
)
from quantlab.data.providers.yfinance_prices import YFinancePriceProvider


def test_read_cache_missing_path_returns_none(tmp_path):
    assert read_cache(tmp_path / "nope.parquet") is None


def test_write_then_read_cache_roundtrips_exactly(tmp_path):
    df = pd.DataFrame(
        {"a": [1.0, 2.0, 3.0], "b": [4, 5, 6]},
        index=pd.date_range("2021-01-04", periods=3, freq="B"),
    )
    path = tmp_path / "sub" / "cached.parquet"

    write_cache(df, path)
    result = read_cache(path)

    pd.testing.assert_frame_equal(result, df, check_freq=False)


def test_write_price_cache_meta_then_read(tmp_path):
    write_price_cache_meta("AAPL", "2020-01-01", "2020-12-31", tmp_path)
    meta = json.loads(price_meta_path("AAPL", tmp_path).read_text())
    assert meta == {"requested_start": "2020-01-01", "requested_end": "2020-12-31"}


def _write_fake_cache(cache_dir, ticker: str, start: str, end: str) -> pd.DataFrame:
    dates = pd.date_range(start, end, freq="B")
    df = pd.DataFrame(
        {
            "Open": [1.0] * len(dates),
            "High": [1.0] * len(dates),
            "Low": [1.0] * len(dates),
            "Close": [1.0] * len(dates),
            "Adj Close": [float(i) for i in range(1, len(dates) + 1)],
            "Volume": [100] * len(dates),
        },
        index=dates,
    )
    path = price_cache_path(ticker, cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path)
    return df


def test_has_sufficient_price_cache_returns_none_when_no_file(tmp_path):
    assert has_sufficient_price_cache("AAPL", "2020-01-01", "2020-12-31", tmp_path) is None


def test_has_sufficient_price_cache_data_fallback_within_tolerance(tmp_path):
    _write_fake_cache(tmp_path, "AAPL", "2020-01-01", "2020-12-31")
    result = has_sufficient_price_cache("AAPL", "2020-01-02", "2020-12-30", tmp_path)
    assert result is not None


def test_has_sufficient_price_cache_data_fallback_outside_tolerance_returns_none(tmp_path):
    _write_fake_cache(tmp_path, "AAPL", "2020-01-01", "2020-12-31")
    result = has_sufficient_price_cache("AAPL", "2019-01-01", "2021-12-31", tmp_path)
    assert result is None


def test_has_sufficient_price_cache_uses_metadata_for_delisted_ticker(tmp_path):
    """The valuable "known empty range" logic: a ticker delisted in 2015
    has no data after that, but if the cache was fetched FOR a much wider
    window, metadata proves the cache is complete - not stale."""
    _write_fake_cache(tmp_path, "GONE", "2012-01-03", "2015-06-30")
    write_price_cache_meta("GONE", "2012-01-01", "2026-06-30", tmp_path)

    result = has_sufficient_price_cache("GONE", "2012-01-01", "2026-06-30", tmp_path)

    assert result is not None
    assert result.index.max() == pd.Timestamp("2015-06-30")


def test_delisted_ticker_prevents_refetch_with_mock_fetcher_counting_calls(tmp_path, monkeypatch):
    """End-to-end through YFinancePriceProvider: with metadata present, a
    delisted ticker's cache must be served without ever calling the
    (mocked, call-counting) fetcher."""
    _write_fake_cache(tmp_path, "GONE", "2012-01-03", "2015-06-30")
    write_price_cache_meta("GONE", "2012-01-01", "2026-06-30", tmp_path)

    call_count = {"n": 0}

    def _counting_fetch(tickers, start, end):
        call_count["n"] += 1
        raise AssertionError("network download attempted - cache should have been used")

    monkeypatch.setattr(yfinance_prices_module, "_download_batch", _counting_fetch)

    provider = YFinancePriceProvider(cache_dir=tmp_path)
    panel = provider.get_prices(["GONE"], "2012-01-01", "2026-06-30")

    assert call_count["n"] == 0
    assert "GONE" in set(panel["ticker"])
    assert panel.index.max() == pd.Timestamp("2015-06-30")
