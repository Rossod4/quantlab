"""Quarantine and scan-coverage state must survive every ordinary data
operation (prefetch, refresh --prices/--actions/--all, --clear-negative-cache)
and be released ONLY by `refresh --unquarantine <ticker>`; a price file
rewritten by a refresh must stop counting as scanned. Motivated by the
2026-09-12 cache rebuild, which silently lost every quarantine verdict."""

from __future__ import annotations

import pandas as pd
import pytest

import quantlab.data.corporate_actions as corporate_actions_module
import quantlab.data.providers.yfinance_prices as yfinance_prices_module
from quantlab.data.cache import (
    price_meta_path,
    read_json_meta,
    write_cache,
    write_json_meta,
    write_quarantine_meta,
)
from quantlab.data.ops import prefetch, refresh, scan, status
from quantlab.data.quality import read_scan_manifest, unscanned_tickers
from tests.test_data_ops import (
    _fake_no_actions,
    _write_constituents_cache,
    _write_platform_yaml,
    _write_warm_price_cache,
)

REASONS = ["symbol_reuse_new_listing (first_bar=2018-01-19, membership=2012-10-02)"]


@pytest.fixture
def world(tmp_path, monkeypatch):
    """QQQ is quarantined; AAA and BBB are clean; all three were scanned. AAA's
    cached range is old (a refresh/prefetch to 2020 must re-fetch it); BBB's
    already covers 2020 (never re-fetched)."""
    cache_dir = tmp_path / "cache"
    platform_config = _write_platform_yaml(tmp_path, cache_dir=cache_dir)
    _write_constituents_cache(cache_dir, {"2015-01-01": ["AAA", "BBB", "QQQ"]})
    for ticker in ("AAA", "QQQ"):
        _write_warm_price_cache(ticker, cache_dir, "2015-01-01", "2016-12-31")
    for ticker in ("BBB", "SPY"):
        _write_warm_price_cache(ticker, cache_dir, "2015-01-01", "2020-12-31")
    scan(platform_config)  # writes the manifest covering every cached ticker
    write_quarantine_meta("QQQ", REASONS, cache_dir)

    downloads: list[str] = []

    def _fake_download(tickers, start, end):
        downloads.extend(tickers)
        dates = pd.date_range("2015-01-01", "2020-12-31", freq="B")
        return pd.DataFrame(
            {
                "Open": 100.0,
                "High": 101.0,
                "Low": 99.0,
                "Close": 100.0,
                "Adj Close": 100.0,
                "Volume": 5_000_000.0,
            },
            index=dates,
        )

    monkeypatch.setattr(yfinance_prices_module, "_download_batch", _fake_download)
    monkeypatch.setattr(corporate_actions_module, "_download_actions", _fake_no_actions)
    write_cache(pd.DataFrame(columns=["ticker", "cik"]), cache_dir / "sec_ticker_cik_map.parquet")
    return {"cache_dir": cache_dir, "platform": platform_config, "downloads": downloads}


def _assert_still_quarantined(world):
    meta = read_json_meta(price_meta_path("QQQ", world["cache_dir"]))
    assert meta["quarantined"] is True
    assert meta["reasons"] == REASONS
    assert "QQQ" not in world["downloads"], "a quarantined ticker must never be re-downloaded"
    assert "QQQ" in status(world["platform"]).quarantined


def test_prefetch_over_a_wider_window_leaves_quarantine_intact(world):
    prefetch(world["platform"], "2015-01-01", "2020-12-31")
    _assert_still_quarantined(world)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"prices": True},
        {"actions": True},
        {"prices": True, "actions": True},
        {"fundamentals": True},
    ],
)
def test_refresh_named_ticker_leaves_quarantine_intact(world, kwargs):
    refresh(world["platform"], tickers=["QQQ"], as_of=pd.Timestamp("2020-12-31"), **kwargs)
    _assert_still_quarantined(world)


def test_refresh_all_leaves_quarantine_intact(world):
    refresh(
        world["platform"],
        do_all=True,
        prices=True,
        actions=True,
        as_of=pd.Timestamp("2020-12-31"),
    )
    _assert_still_quarantined(world)


def test_clear_negative_cache_leaves_quarantine_intact_even_on_a_no_data_sidecar(world):
    cache_dir = world["cache_dir"]
    meta = read_json_meta(price_meta_path("QQQ", cache_dir))
    meta.update({"no_data": True, "fetched_at": "2026-09-12"})
    write_json_meta(price_meta_path("QQQ", cache_dir), meta)

    for kwargs in ({"tickers": ["QQQ"]}, {}):
        refresh(world["platform"], clear_negative_cache=True, **kwargs)
    after = read_json_meta(price_meta_path("QQQ", cache_dir))
    assert "no_data" not in after
    assert after["quarantined"] is True and after["reasons"] == REASONS


def test_only_unquarantine_releases_and_it_re_fetches_and_re_scans(world):
    report = refresh(world["platform"], unquarantine="QQQ", as_of=pd.Timestamp("2020-12-31"))

    assert "QQQ" in world["downloads"]
    assert report.unquarantine_result == "cleared"
    assert "quarantined" not in read_json_meta(price_meta_path("QQQ", world["cache_dir"]))
    assert "QQQ" not in status(world["platform"]).quarantined


# --- scan-coverage manifest --------------------------------------------------


def test_a_price_file_rewritten_by_refresh_no_longer_counts_as_scanned(world):
    cache_dir = world["cache_dir"]
    assert unscanned_tickers(cache_dir, ["AAA", "BBB"]) == []

    refresh(world["platform"], tickers=["AAA"], prices=True, as_of=pd.Timestamp("2020-12-31"))

    assert "AAA" in world["downloads"]
    assert unscanned_tickers(cache_dir, ["AAA", "BBB"]) == ["AAA"]
    assert status(world["platform"]).never_scanned_count == 1


def test_prefetch_rewriting_a_price_file_invalidates_only_that_tickers_scan(world):
    prefetch(world["platform"], "2015-01-01", "2020-12-31")
    assert unscanned_tickers(world["cache_dir"], ["AAA", "BBB", "QQQ", "SPY"]) == ["AAA"]


def test_unquarantine_rescan_preserves_scan_coverage_of_every_other_ticker(world):
    refresh(world["platform"], unquarantine="QQQ", as_of=pd.Timestamp("2020-12-31"))

    manifest = read_scan_manifest(world["cache_dir"])
    assert {"BBB", "SPY", "QQQ"} <= set(manifest["scanned_tickers"])
    assert unscanned_tickers(world["cache_dir"], ["BBB", "SPY", "QQQ"]) == []
