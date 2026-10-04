"""Unit tests for src/quantlab/data/ops.py: `prefetch`/`refresh`/`scan`/
`status`, the `quantlab data` operational commands.

Every network-touching path is exercised with FAKE downloads (a
monkeypatched module-level `_download_actions`, or a pre-populated cache
that already covers the requested window) - never the real network
(CLAUDE.md invariant #5). `scan`/`status` are exercised against a synthetic
on-disk cache built directly with `data/cache.py`'s own writers, matching
the convention tests/test_quality.py and tests/test_cli_validate.py already
use.
"""

from __future__ import annotations

import pandas as pd
import pytest

import quantlab.data.corporate_actions as corporate_actions_module
from quantlab.core.config import load_platform_config
from quantlab.core.errors import ConfigError
from quantlab.data.cache import (
    price_cache_path,
    price_meta_path,
    read_json_meta,
    write_cache,
    write_price_cache_meta,
    write_price_cache_no_data_meta,
    write_quarantine_meta,
)
from quantlab.data.ops import (
    PrefetchReport,
    RefreshReport,
    StatusReport,
    build_prefetch_universe,
    prefetch,
    refresh,
    scan,
    status,
)
from quantlab.data.providers.sp500_constituents import CACHE_FILENAME as _SP500_CACHE_FILENAME


def _write_platform_yaml(tmp_path, cache_dir=None, reports_dir=None):
    cache_dir = cache_dir or (tmp_path / "cache")
    reports_dir = reports_dir or (tmp_path / "reports")
    path = tmp_path / "platform.yaml"
    path.write_text(
        f"""
cache_dir: {cache_dir.as_posix()}
reports_dir: {reports_dir.as_posix()}
providers:
  prices: yfinance
  constituents: sp500_community
  fundamentals: edgar
benchmark: SPY
""",
        encoding="utf-8",
    )
    return load_platform_config(path)


def _write_constituents_cache(cache_dir, membership: dict[str, list[str]]) -> None:
    table = pd.DataFrame(
        {"tickers": list(membership.values())},
        index=pd.DatetimeIndex(sorted(membership.keys())),
    )
    write_cache(table, cache_dir / _SP500_CACHE_FILENAME)


def _write_warm_price_cache(ticker: str, cache_dir, start: str, end: str) -> None:
    dates = pd.date_range(start, end, freq="B")
    frame = pd.DataFrame(
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
    path = price_cache_path(ticker, cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path)
    write_price_cache_meta(ticker, start, end, cache_dir)


def _fake_no_actions(ticker: str) -> pd.DataFrame:
    empty = pd.DataFrame(columns=["ticker", "action_type", "value"])
    empty.index = pd.DatetimeIndex([], name="date")
    return empty


# --- build_prefetch_universe -------------------------------------------------


class _FakeConstituentsProvider:
    def __init__(self, at_start: list[str], history: dict[str, list[str]]):
        self._at_start = at_start
        self._history = history

    def membership(self, asof: object) -> list[str]:
        return self._at_start

    def membership_history(self, start: object, end: object) -> pd.DataFrame:
        return pd.DataFrame(
            {"tickers": list(self._history.values())},
            index=pd.DatetimeIndex(sorted(self._history.keys())),
        )


def test_build_prefetch_universe_unions_start_snapshot_history_and_benchmark():
    # "AAA" only appears in the as-of-start snapshot (its own membership
    # change predates the history window); "CCC" only appears inside the
    # history window; "BBB" appears in both.
    provider = _FakeConstituentsProvider(
        at_start=["AAA", "BBB"],
        history={"2016-06-01": ["BBB", "CCC"]},
    )
    universe = build_prefetch_universe(provider, "2015-01-01", "2020-01-01", benchmark="SPY")
    assert universe == ["AAA", "BBB", "CCC", "SPY"]


def test_build_prefetch_universe_without_benchmark():
    provider = _FakeConstituentsProvider(at_start=["AAA"], history={})
    universe = build_prefetch_universe(provider, "2015-01-01", "2020-01-01", benchmark=None)
    assert universe == ["AAA"]


# --- prefetch ----------------------------------------------------------------


def test_prefetch_covers_prices_actions_and_fundamentals_and_writes_a_report(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    platform_config = _write_platform_yaml(tmp_path, cache_dir=cache_dir)
    _write_constituents_cache(cache_dir, {"2015-01-01": ["AAA", "BBB"]})
    # Warm price cache covering the requested window - no network call.
    _write_warm_price_cache("AAA", cache_dir, "2015-01-01", "2016-12-31")
    _write_warm_price_cache("BBB", cache_dir, "2015-01-01", "2016-12-31")
    _write_warm_price_cache("SPY", cache_dir, "2015-01-01", "2016-12-31")
    monkeypatch.setattr(corporate_actions_module, "_download_actions", _fake_no_actions)
    # No SEC ticker-CIK cache pre-populated -> load_ticker_cik_map would hit
    # the network; pre-populate an EMPTY map so every ticker takes the
    # "no CIK match" branch instead, offline.
    write_cache(pd.DataFrame(columns=["ticker", "cik"]), cache_dir / "sec_ticker_cik_map.parquet")

    report = prefetch(platform_config, "2015-01-01", "2016-12-31")

    assert isinstance(report, PrefetchReport)
    assert report.universe_size == 3
    assert report.tickers == ["AAA", "BBB", "SPY"]
    assert report.price_failures == {}
    assert report.actions_failures == {}
    # No CIK match for any ticker -> every one is a fundamentals failure,
    # named as such rather than silently absent.
    assert set(report.fundamentals_failures) == {"AAA", "BBB", "SPY"}
    assert all("CIK" in reason for reason in report.fundamentals_failures.values())
    assert report.wall_seconds >= 0.0

    written = (cache_dir / "prefetch_report.json").read_text(encoding="utf-8")
    assert '"universe_size": 3' in written


def test_prefetch_names_a_ticker_with_no_price_data_as_a_failure(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    platform_config = _write_platform_yaml(tmp_path, cache_dir=cache_dir)
    _write_constituents_cache(cache_dir, {"2015-01-01": ["AAA", "MISSING"]})
    _write_warm_price_cache("AAA", cache_dir, "2015-01-01", "2016-12-31")
    _write_warm_price_cache("SPY", cache_dir, "2015-01-01", "2016-12-31")
    # "MISSING" has no warm cache and no fake download - the real
    # `_download_batch` would be called; monkeypatch it to simulate a
    # vendor returning nothing for it (never touches the network).
    import quantlab.data.providers.yfinance_prices as yfinance_prices_module

    def _empty_download(tickers, start, end):
        return pd.DataFrame()

    monkeypatch.setattr(yfinance_prices_module, "_download_batch", _empty_download)
    monkeypatch.setattr(corporate_actions_module, "_download_actions", _fake_no_actions)
    write_cache(pd.DataFrame(columns=["ticker", "cik"]), cache_dir / "sec_ticker_cik_map.parquet")

    report = prefetch(platform_config, "2015-01-01", "2016-12-31")

    assert "MISSING" in report.price_failures
    assert "AAA" not in report.price_failures
    assert "SPY" not in report.price_failures


def test_prefetch_rejects_an_unknown_universe(tmp_path):
    cache_dir = tmp_path / "cache"
    platform_config = _write_platform_yaml(tmp_path, cache_dir=cache_dir)
    _write_constituents_cache(cache_dir, {"2015-01-01": ["AAA"]})

    with pytest.raises(ConfigError):
        prefetch(platform_config, "2015-01-01", "2016-12-31", universe="nasdaq100")


# --- refresh -------------------------------------------------------------


def test_refresh_actions_calls_refresh_actions_cache_for_each_ticker(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    platform_config = _write_platform_yaml(tmp_path, cache_dir=cache_dir)
    calls: list[str] = []

    def _fake_download(ticker: str) -> pd.DataFrame:
        calls.append(ticker)
        return _fake_no_actions(ticker)

    monkeypatch.setattr(corporate_actions_module, "_download_actions", _fake_download)

    report = refresh(platform_config, tickers=["AAA", "BBB"], actions=True)

    assert isinstance(report, RefreshReport)
    assert sorted(report.actions_refreshed) == ["AAA", "BBB"]
    assert report.actions_failures == {}
    assert sorted(calls) == ["AAA", "BBB"]  # a genuine fresh download, not a cache hit


def test_refresh_actions_clears_a_stale_actions_cache_error(tmp_path, monkeypatch):
    """QUANT-NOTES.md M02b/M04 carried item: `refresh_actions_cache` is the
    ONLY way to clear a StaleActionsCacheError - this is the operational
    caller that closes the gap."""
    from quantlab.core.errors import StaleActionsCacheError
    from quantlab.data.corporate_actions import YFinanceCorporateActionsProvider

    cache_dir = tmp_path / "cache"
    platform_config = _write_platform_yaml(tmp_path, cache_dir=cache_dir)
    monkeypatch.setattr(corporate_actions_module, "_download_actions", _fake_no_actions)
    monkeypatch.setattr(corporate_actions_module, "_today", lambda: pd.Timestamp("2020-01-01"))

    provider = YFinanceCorporateActionsProvider(cache_dir=cache_dir)
    provider.get_actions("AAA", "1900-01-01", "2020-01-01")  # populates the cache, fetched_at 2020

    with pytest.raises(StaleActionsCacheError):
        provider.get_actions("AAA", "1900-01-01", "2021-01-01")  # asof past fetched_at -> stale

    monkeypatch.setattr(corporate_actions_module, "_today", lambda: pd.Timestamp("2021-06-01"))
    refresh(platform_config, tickers=["AAA"], actions=True)

    # A FRESH provider instance (no in-memory memo) confirms the on-disk
    # sidecar itself was refreshed, not just this one instance's cache.
    fresh_provider = YFinanceCorporateActionsProvider(cache_dir=cache_dir)
    fresh_provider.get_actions("AAA", "1900-01-01", "2021-01-01")  # no longer stale


def test_refresh_prices_refetches_past_requested_end(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    platform_config = _write_platform_yaml(tmp_path, cache_dir=cache_dir)
    _write_warm_price_cache("AAA", cache_dir, "2015-01-01", "2016-12-31")

    import quantlab.data.providers.yfinance_prices as yfinance_prices_module

    calls: list[tuple[str, ...]] = []

    def _fake_download(tickers, start, end):
        calls.append(tuple(tickers))
        dates = pd.date_range("2015-01-01", "2020-12-31", freq="B")
        frame = pd.DataFrame(
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
        return frame  # single-ticker batch: flat columns, per yfinance's own shape

    monkeypatch.setattr(yfinance_prices_module, "_download_batch", _fake_download)

    report = refresh(
        platform_config, tickers=["AAA"], prices=True, as_of=pd.Timestamp("2020-12-31")
    )

    assert report.prices_refreshed == ["AAA"]
    assert calls, "a wider requested_end must trigger a genuine re-fetch, not a cache hit"

    meta = read_json_meta(price_meta_path("AAA", cache_dir))
    assert pd.Timestamp(meta["requested_end"]) >= pd.Timestamp("2020-12-31")


def _plant_no_data_sidecar(cache_dir, ticker: str, fetched_at: str) -> None:
    from quantlab.data.cache import write_json_meta

    write_json_meta(
        price_meta_path(ticker, cache_dir),
        {
            "no_data": True,
            "fetched_at": fetched_at,
            "requested_start": "2015-01-01",
            "requested_end": "2016-12-31",
        },
    )


def _fake_price_download_counter(monkeypatch):
    import quantlab.data.providers.yfinance_prices as yfinance_prices_module

    calls: list[tuple[str, ...]] = []

    def _fake_download(tickers, start, end):
        calls.append(tuple(tickers))
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
    return calls


def test_refresh_prices_replaces_an_expired_negative_sidecar(tmp_path, monkeypatch):
    """Carried M09 acceptance criterion 3: an EXPIRED no_data sidecar is
    re-fetched by `refresh --prices` (no `--clear-negative-cache` needed) and
    the successful download overwrites it with a real range sidecar."""
    cache_dir = tmp_path / "cache"
    platform_config = _write_platform_yaml(tmp_path, cache_dir=cache_dir)
    _plant_no_data_sidecar(cache_dir, "AAA", "2000-01-01")  # far past retry_after_days
    calls = _fake_price_download_counter(monkeypatch)

    report = refresh(
        platform_config, tickers=["AAA"], prices=True, as_of=pd.Timestamp("2020-12-31")
    )

    assert report.prices_refreshed == ["AAA"]
    assert calls, "an expired negative sidecar must trigger a live re-fetch"
    meta = read_json_meta(price_meta_path("AAA", cache_dir))
    assert "no_data" not in meta
    assert price_cache_path("AAA", cache_dir).exists()


def test_refresh_prices_leaves_an_unexpired_negative_sidecar_alone(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    platform_config = _write_platform_yaml(tmp_path, cache_dir=cache_dir)
    _plant_no_data_sidecar(cache_dir, "AAA", str(pd.Timestamp.now().date()))
    calls = _fake_price_download_counter(monkeypatch)

    refresh(platform_config, tickers=["AAA"], prices=True, as_of=pd.Timestamp("2020-12-31"))

    assert not calls, "a within-TTL negative sidecar must suppress the re-fetch"
    assert read_json_meta(price_meta_path("AAA", cache_dir))["no_data"] is True


def test_refresh_fundamentals_forces_a_fresh_company_facts_download(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    platform_config = _write_platform_yaml(tmp_path, cache_dir=cache_dir)
    write_cache(
        pd.DataFrame({"ticker": ["AAA"], "cik": [1]}), cache_dir / "sec_ticker_cik_map.parquet"
    )

    import quantlab.data.providers.edgar_fundamentals as edgar_module

    calls: list[str] = []

    class _FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"facts": {}}

    def _fake_get(url, headers, timeout):
        calls.append(url)
        return _FakeResponse()

    monkeypatch.setattr(edgar_module.requests, "get", _fake_get)
    monkeypatch.setattr(edgar_module.time, "sleep", lambda _s: None)

    report = refresh(platform_config, tickers=["AAA"], fundamentals=True)

    # The refresh ATTEMPT succeeded (a real network call was made, no
    # exception raised) even though the fake payload has no usable tags -
    # `get_company_facts` returning None (empty facts) is a normal outcome,
    # not a failure this report should name.
    assert report.fundamentals_refreshed == ["AAA"]
    assert report.fundamentals_failures == {}
    assert calls, "force_refresh=True must re-hit the network, not reuse a cache miss silently"


def test_refresh_fundamentals_reports_no_cik_match(tmp_path):
    cache_dir = tmp_path / "cache"
    platform_config = _write_platform_yaml(tmp_path, cache_dir=cache_dir)
    write_cache(pd.DataFrame(columns=["ticker", "cik"]), cache_dir / "sec_ticker_cik_map.parquet")

    report = refresh(platform_config, tickers=["AAA"], fundamentals=True)

    assert report.fundamentals_refreshed == []
    assert "no CIK match" in report.fundamentals_failures["AAA"]


def test_refresh_all_resolves_every_sidecar_ticker(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    platform_config = _write_platform_yaml(tmp_path, cache_dir=cache_dir)
    _write_warm_price_cache("AAA", cache_dir, "2015-01-01", "2016-12-31")
    write_price_cache_no_data_meta("BBB", "2015-01-01", "2016-12-31", cache_dir)
    monkeypatch.setattr(corporate_actions_module, "_download_actions", _fake_no_actions)

    report = refresh(platform_config, do_all=True, actions=True)

    assert sorted(report.tickers) == ["AAA", "BBB"]
    assert sorted(report.actions_refreshed) == ["AAA", "BBB"]


def test_refresh_clear_negative_cache_scoped_to_tickers(tmp_path):
    cache_dir = tmp_path / "cache"
    platform_config = _write_platform_yaml(tmp_path, cache_dir=cache_dir)
    write_price_cache_no_data_meta("AAA", "2015-01-01", "2016-12-31", cache_dir)
    write_price_cache_no_data_meta("BBB", "2015-01-01", "2016-12-31", cache_dir)

    report = refresh(platform_config, tickers=["AAA"], clear_negative_cache=True)

    assert report.negative_cache_cleared == ["AAA"]
    assert read_json_meta(price_meta_path("AAA", cache_dir)).get("no_data") is None
    assert read_json_meta(price_meta_path("BBB", cache_dir)).get("no_data") is True


def test_refresh_clear_negative_cache_covers_every_no_data_ticker_without_scoping(tmp_path):
    cache_dir = tmp_path / "cache"
    platform_config = _write_platform_yaml(tmp_path, cache_dir=cache_dir)
    write_price_cache_no_data_meta("AAA", "2015-01-01", "2016-12-31", cache_dir)
    write_price_cache_no_data_meta("BBB", "2015-01-01", "2016-12-31", cache_dir)

    report = refresh(platform_config, clear_negative_cache=True)

    assert sorted(report.negative_cache_cleared) == ["AAA", "BBB"]


def test_refresh_unquarantine_reports_cleared_when_the_rescan_finds_nothing(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    platform_config = _write_platform_yaml(tmp_path, cache_dir=cache_dir)
    _write_warm_price_cache("AAA", cache_dir, "2010-06-01", "2020-12-30")
    write_quarantine_meta("AAA", ["some old reason"], cache_dir)

    import quantlab.data.providers.yfinance_prices as yfinance_prices_module

    monkeypatch.setattr(
        yfinance_prices_module, "_download_batch", lambda tickers, start, end: pd.DataFrame()
    )

    report = refresh(platform_config, unquarantine="AAA", as_of=pd.Timestamp("2020-12-30"))

    assert report.unquarantine_result == "cleared"
    assert read_json_meta(price_meta_path("AAA", cache_dir)).get("quarantined") is None


def test_refresh_unquarantine_reports_still_quarantined_when_the_rescan_still_fails(tmp_path):
    from quantlab.core.calendar import trading_days

    cache_dir = tmp_path / "cache"
    platform_config = _write_platform_yaml(tmp_path, cache_dir=cache_dir)
    sessions = trading_days("2010-06-01", "2020-12-30")
    # Genuinely contaminated: alternating price levels differing by >4x
    # across 200+ dates - the same shape test_quality.py's TIE fixture uses.
    frame = pd.DataFrame(
        {
            "Open": [16.0 if i % 2 == 0 else 8000.0 for i in range(len(sessions))],
            "High": [16.1 if i % 2 == 0 else 8001.0 for i in range(len(sessions))],
            "Low": [15.9 if i % 2 == 0 else 7999.0 for i in range(len(sessions))],
            "Close": [16.0 if i % 2 == 0 else 8000.0 for i in range(len(sessions))],
            "Adj Close": [16.0 if i % 2 == 0 else 8000.0 for i in range(len(sessions))],
            "Volume": [11_000] * len(sessions),
        },
        index=sessions,
    )
    path = price_cache_path("TIE", cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path)
    write_price_cache_meta("TIE", sessions[0], sessions[-1], cache_dir)
    write_quarantine_meta("TIE", ["old reason"], cache_dir)

    report = refresh(platform_config, unquarantine="TIE", as_of=sessions[-1])

    assert report.unquarantine_result == "still_quarantined"
    assert read_json_meta(price_meta_path("TIE", cache_dir)).get("quarantined") is True


# --- scan --------------------------------------------------------------------


def test_scan_wires_platform_config_thresholds_and_returns_a_report(tmp_path):
    cache_dir = tmp_path / "cache"
    platform_config = _write_platform_yaml(tmp_path, cache_dir=cache_dir)
    _write_warm_price_cache("AAA", cache_dir, "2015-01-01", "2016-12-31")

    report = scan(platform_config)

    assert report.scanned_count == 1
    assert report.quarantined == {}


def test_scan_uses_membership_aware_detector_when_a_constituents_provider_is_given(tmp_path):
    from quantlab.core.calendar import trading_days

    cache_dir = tmp_path / "cache"
    platform_config = _write_platform_yaml(tmp_path, cache_dir=cache_dir)
    sessions = trading_days("2024-01-02", "2025-12-30")
    frame = pd.DataFrame(
        {
            "Open": 50.0,
            "High": 50.1,
            "Low": 49.9,
            "Close": 50.0,
            "Adj Close": 50.0,
            "Volume": 100_000.0,
        },
        index=sessions,
    )
    path = price_cache_path("REUSED", cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path)
    write_price_cache_meta("REUSED", "2010-06-01", sessions[-1], cache_dir)

    provider = _FakeConstituentsProvider(at_start=[], history={"2010-06-01": ["REUSED"]})

    report = scan(platform_config, constituents_provider=provider)

    assert "REUSED" in report.quarantined
    assert any("symbol_reuse_new_listing" in r for r in report.quarantined["REUSED"])


# --- status ------------------------------------------------------------------


def test_status_reports_coverage_negative_cache_and_quarantine(tmp_path):
    cache_dir = tmp_path / "cache"
    platform_config = _write_platform_yaml(tmp_path, cache_dir=cache_dir)
    _write_warm_price_cache("AAA", cache_dir, "2015-01-01", "2016-12-31")
    write_price_cache_no_data_meta("BBB", "2015-01-01", "2016-12-31", cache_dir)
    write_quarantine_meta("AAA", ["some reason"], cache_dir)

    report = status(platform_config)

    assert isinstance(report, StatusReport)
    assert report.price_ticker_count == 1  # only AAA has a real parquet
    assert report.no_data_count == 1
    assert report.no_data_tickers == ["BBB"]
    assert report.quarantined == {"AAA": ["some reason"]}
    # Neither AAA nor BBB has ever been scanned - status must say so, not
    # read a never-scanned cache as clean (QUANT-NOTES.md "M09 (quantlab
    # data scan), must-fix").
    assert report.never_scanned_count == 1  # only AAA has a parquet to count
    assert report.scan_checked_at is None


def test_status_reports_masked_truncation(tmp_path):
    cache_dir = tmp_path / "cache"
    platform_config = _write_platform_yaml(tmp_path, cache_dir=cache_dir)
    _write_warm_price_cache("AAA", cache_dir, "2015-01-01", "2016-06-30")
    # Overwrite the sidecar to claim a WIDER requested range than the data
    # actually covers - a frozen truncation (M01 hazard).
    write_price_cache_meta("AAA", "2015-01-01", "2020-12-31", cache_dir)

    report = status(platform_config)

    assert report.masked_truncation_tickers == ["AAA"]
    assert report.masked_truncation_count == 1


def test_status_reflects_a_completed_scan(tmp_path):
    cache_dir = tmp_path / "cache"
    platform_config = _write_platform_yaml(tmp_path, cache_dir=cache_dir)
    _write_warm_price_cache("AAA", cache_dir, "2015-01-01", "2016-12-31")

    scan(platform_config)
    report = status(platform_config)

    assert report.never_scanned_count == 0
    assert report.scan_checked_at is not None


def test_prefetch_requests_actions_from_the_epoch_not_from_the_window_start(tmp_path, monkeypatch):
    """The adjustment replay needs every corporate action BEFORE the backtest
    window too, so prefetch must ask for the full history, not [start, end].
    (Mutation: `_EPOCH` -> `start_ts` in `prefetch` made nothing fail.)"""
    import quantlab.data.ops as ops_module

    cache_dir = tmp_path / "cache"
    platform_config = _write_platform_yaml(tmp_path, cache_dir=cache_dir)
    _write_constituents_cache(cache_dir, {"2015-01-01": ["AAA"]})
    _write_warm_price_cache("AAA", cache_dir, "2015-01-01", "2016-12-31")
    _write_warm_price_cache("SPY", cache_dir, "2015-01-01", "2016-12-31")
    write_cache(pd.DataFrame(columns=["ticker", "cik"]), cache_dir / "sec_ticker_cik_map.parquet")
    requested: list[tuple[str, pd.Timestamp, pd.Timestamp]] = []

    class _SpyActionsProvider(ops_module.YFinanceCorporateActionsProvider):
        def get_actions(self, ticker, start, end):
            requested.append((ticker, pd.Timestamp(start), pd.Timestamp(end)))
            return _fake_no_actions(ticker)

    monkeypatch.setattr(ops_module, "YFinanceCorporateActionsProvider", _SpyActionsProvider)

    prefetch(platform_config, "2015-01-01", "2016-12-31")

    assert {t for t, _s, _e in requested} == {"AAA", "SPY"}
    assert all(start == ops_module._EPOCH for _t, start, _e in requested)
    assert all(start < pd.Timestamp("2015-01-01") for _t, start, _e in requested)
