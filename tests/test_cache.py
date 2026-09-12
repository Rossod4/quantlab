from __future__ import annotations

import json

import pandas as pd

import quantlab.data.cache as cache_module
import quantlab.data.providers.yfinance_prices as yfinance_prices_module
from quantlab.data.cache import (
    has_sufficient_price_cache,
    price_cache_path,
    price_meta_path,
    read_cache,
    write_cache,
    write_price_cache_meta,
    write_price_cache_no_data_meta,
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


# -- negative price cache with TTL (M04b work packet item 3) -----------------


def test_has_sufficient_price_cache_returns_empty_frame_for_no_data_within_ttl(tmp_path):
    write_price_cache_no_data_meta("GONE", "2020-01-01", "2020-12-31", tmp_path)

    result = has_sufficient_price_cache("GONE", "2020-01-01", "2020-12-31", tmp_path)

    assert result is not None
    assert result.empty


def test_has_sufficient_price_cache_returns_none_for_no_data_after_ttl(tmp_path, monkeypatch):
    monkeypatch.setattr(cache_module, "_today", lambda: pd.Timestamp("2020-01-01"))
    write_price_cache_no_data_meta("GONE", "2020-01-01", "2020-12-31", tmp_path)

    monkeypatch.setattr(cache_module, "_today", lambda: pd.Timestamp("2020-03-01"))  # 60 days later
    result = has_sufficient_price_cache(
        "GONE", "2020-01-01", "2020-12-31", tmp_path, retry_after_days=30
    )

    assert result is None


def test_has_sufficient_price_cache_no_data_requires_the_request_to_still_be_covered(tmp_path):
    """A no_data sidecar recorded for a NARROWER range than is now requested
    must not be trusted, even within the TTL - the retry must happen for the
    newly-widened part of the window."""
    write_price_cache_no_data_meta("GONE", "2020-06-01", "2020-12-31", tmp_path)

    result = has_sufficient_price_cache("GONE", "2015-01-01", "2020-12-31", tmp_path)

    assert result is None


def test_negative_cache_hit_within_ttl_makes_zero_provider_calls(tmp_path, monkeypatch):
    """M04b acceptance test (a): a second `get_prices` call within the TTL
    for a ticker that came back with zero rows must make ZERO further
    provider calls - the bug this milestone fixes (a failed download
    re-fetched, and re-throttled, on every single call)."""
    call_count = {"n": 0}

    def _empty_fetch(tickers, start, end):
        call_count["n"] += 1
        return pd.DataFrame()  # simulates "no rows for any requested ticker"

    monkeypatch.setattr(yfinance_prices_module, "_download_batch", _empty_fetch)
    provider = YFinancePriceProvider(cache_dir=tmp_path)

    provider.get_prices(["GONE"], "2020-01-01", "2020-12-31")
    assert call_count["n"] == 1

    provider.get_prices(["GONE"], "2020-01-01", "2020-12-31")
    assert call_count["n"] == 1  # negative-cache hit - no second network call

    meta = json.loads(price_meta_path("GONE", tmp_path).read_text())
    assert meta["no_data"] is True


def test_negative_cache_expires_after_ttl_and_retries(tmp_path, monkeypatch):
    """M04b acceptance test (b): after the TTL lapses, the SAME ticker is
    retried - a genuinely transient failure is not frozen forever (the M01
    hazard plans/QUANT-NOTES.md warns against), just not retried on EVERY
    call."""
    monkeypatch.setattr(cache_module, "_today", lambda: pd.Timestamp("2020-01-01"))
    call_count = {"n": 0}

    def _empty_fetch(tickers, start, end):
        call_count["n"] += 1
        return pd.DataFrame()

    monkeypatch.setattr(yfinance_prices_module, "_download_batch", _empty_fetch)
    provider = YFinancePriceProvider(cache_dir=tmp_path, retry_after_days=30)

    provider.get_prices(["GONE"], "2020-01-01", "2020-12-31")
    assert call_count["n"] == 1

    monkeypatch.setattr(cache_module, "_today", lambda: pd.Timestamp("2020-02-15"))  # 45 days later
    provider.get_prices(["GONE"], "2020-01-01", "2020-12-31")
    assert call_count["n"] == 2  # TTL lapsed - retried, not silently trusted forever


def test_negative_cache_is_replaced_once_a_download_succeeds(tmp_path, monkeypatch):
    """M04b acceptance test (c): once a retry succeeds, the no_data sidecar
    is fully replaced (never lingers) - `write_price_cache_meta` overwrites
    the sidecar file wholesale on a successful download."""
    monkeypatch.setattr(cache_module, "_today", lambda: pd.Timestamp("2020-01-01"))
    monkeypatch.setattr(yfinance_prices_module, "_download_batch", lambda t, s, e: pd.DataFrame())
    provider = YFinancePriceProvider(cache_dir=tmp_path, retry_after_days=30)
    provider.get_prices(["BACK"], "2020-01-01", "2020-12-31")
    assert json.loads(price_meta_path("BACK", tmp_path).read_text())["no_data"] is True

    monkeypatch.setattr(cache_module, "_today", lambda: pd.Timestamp("2020-03-01"))  # TTL lapsed

    def _real_fetch(tickers, start, end):
        dates = pd.date_range("2020-01-01", "2020-01-05", freq="B")
        columns = pd.MultiIndex.from_product(
            [tickers, ["Open", "High", "Low", "Close", "Adj Close", "Volume"]]
        )
        return pd.DataFrame(1.0, index=dates, columns=columns)

    monkeypatch.setattr(yfinance_prices_module, "_download_batch", _real_fetch)
    result = provider.get_prices(["BACK"], "2020-01-01", "2020-12-31")

    meta_after = json.loads(price_meta_path("BACK", tmp_path).read_text())
    assert "no_data" not in meta_after
    assert "BACK" in set(result["ticker"])


def test_negative_cache_ticker_reports_no_data_to_survivorship(tmp_path):
    """M04b acceptance test (d): survivorship must still count a
    negative-cached ticker as lacking data - no parquet price file is ever
    written for it, so `price_availability_from_cache` degrades to
    `has_data=False` with no changes needed to that module at all."""
    from quantlab.data.survivorship import price_availability_from_cache

    write_price_cache_no_data_meta("GONE", "2020-01-01", "2020-12-31", tmp_path)

    availability = price_availability_from_cache(["GONE"], tmp_path)

    assert availability["GONE"].has_data is False


# -- quant-gate VERDICT.md cycle 1 finding 1 (BLOCKING): a no_data sidecar --
# -- must never mask a ticker's REAL cached data -----------------------------


def test_has_sufficient_price_cache_prefers_a_real_parquet_over_a_stale_no_data_sidecar(
    tmp_path,
):
    """Defense in depth at the READ side: even if a `no_data` sidecar and a
    real, covering parquet somehow coexist (e.g. written by an older/buggy
    code path), reads must prefer the parquet - a no_data claim must never
    mask real data."""
    _write_fake_cache(tmp_path, "GOOD", "2012-01-01", "2019-12-31")
    write_price_cache_no_data_meta("GOOD", "2012-01-01", "2019-12-31", tmp_path)

    result = has_sufficient_price_cache("GOOD", "2012-01-01", "2019-12-31", tmp_path)

    assert result is not None
    assert not result.empty


def test_transient_empty_download_never_overwrites_a_healthy_tickers_sidecar(tmp_path, monkeypatch):
    """M04b quant-gate VERDICT.md cycle 1 finding 1 (BLOCKING), reproducing
    the gate's exact repro: a ticker with REAL, healthy cached data must
    never have its sidecar silently replaced by a `no_data` marker just
    because one download attempt (here, triggered by requesting a WIDER
    range than the cache currently covers) comes back empty inside an
    otherwise-successful batch. That would mask real, already-cached data
    behind a negative-cache TTL, with survivorship still reporting
    has_data=True (correctly, since the parquet is untouched) while the
    PROVIDER would otherwise serve nothing for a live ticker."""
    dates = pd.date_range("2012-01-01", "2019-12-31", freq="B")
    healthy = pd.DataFrame(
        {
            "Open": [1.0] * len(dates),
            "High": [1.0] * len(dates),
            "Low": [1.0] * len(dates),
            "Close": [1.0] * len(dates),
            "Adj Close": [1.0] * len(dates),
            "Volume": [100] * len(dates),
        },
        index=dates,
    )
    path = price_cache_path("GOOD", tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    healthy.to_parquet(path)
    write_price_cache_meta("GOOD", "2012-01-01", "2019-12-31", tmp_path)

    monkeypatch.setattr(yfinance_prices_module, "_download_batch", lambda t, s, e: pd.DataFrame())
    provider = YFinancePriceProvider(cache_dir=tmp_path)

    # A WIDER request than the existing cache covers - forces a fetch
    # attempt for "GOOD", which (transiently) comes back empty.
    provider.get_prices(["GOOD"], "2012-01-01", "2026-06-30")

    # The sidecar must be UNCHANGED - the original, positive metadata,
    # never overwritten with `no_data`.
    meta = json.loads(price_meta_path("GOOD", tmp_path).read_text())
    assert meta == {"requested_start": "2012-01-01", "requested_end": "2019-12-31"}

    # The ORIGINAL, already-covered range must still be served from the
    # untouched parquet.
    result = provider.get_prices(["GOOD"], "2012-01-01", "2019-12-31")
    assert "GOOD" in set(result["ticker"])
    assert len(result) == len(dates)

    from quantlab.data.survivorship import price_availability_from_cache

    availability = price_availability_from_cache(["GOOD"], tmp_path)
    assert availability["GOOD"].has_data is True


# -- quant-gate VERDICT.md cycle 1 finding 2: quarantine sidecar -------------


def test_has_sufficient_price_cache_never_serves_a_quarantined_ticker(tmp_path):
    """A quarantined ticker must never be served, even though a real,
    otherwise-covering parquet sits right there on disk."""
    from quantlab.data.cache import write_quarantine_meta

    _write_fake_cache(tmp_path, "PTV", "2005-01-01", "2011-12-31")
    write_price_cache_meta("PTV", "2005-01-01", "2011-12-31", tmp_path)
    write_quarantine_meta("PTV", ["zero_volume_fraction:47.7%"], tmp_path)

    result = has_sufficient_price_cache("PTV", "2005-01-01", "2011-12-31", tmp_path)

    assert result is not None
    assert result.empty


def test_quarantine_has_no_ttl_unlike_the_negative_cache(tmp_path, monkeypatch):
    """Unlike `no_data`, a quarantine verdict never expires on its own -
    only an explicit clear (`clear_quarantine_meta`) removes it."""
    from quantlab.data.cache import write_quarantine_meta

    monkeypatch.setattr(cache_module, "_today", lambda: pd.Timestamp("2020-01-01"))
    _write_fake_cache(tmp_path, "PTV", "2005-01-01", "2011-12-31")
    write_quarantine_meta("PTV", ["zero_volume_fraction:47.7%"], tmp_path)

    monkeypatch.setattr(cache_module, "_today", lambda: pd.Timestamp("2030-01-01"))  # 10 yrs later
    result = has_sufficient_price_cache("PTV", "2005-01-01", "2011-12-31", tmp_path)

    assert result is not None
    assert result.empty


def test_clear_quarantine_meta_preserves_other_sidecar_fields(tmp_path):
    from quantlab.data.cache import clear_quarantine_meta, write_quarantine_meta

    write_price_cache_meta("PTV", "2005-01-01", "2011-12-31", tmp_path)
    write_quarantine_meta("PTV", ["zero_volume_fraction:47.7%"], tmp_path)

    clear_quarantine_meta("PTV", tmp_path)

    meta = json.loads(price_meta_path("PTV", tmp_path).read_text())
    assert "quarantined" not in meta
    assert meta["requested_start"] == "2005-01-01"
