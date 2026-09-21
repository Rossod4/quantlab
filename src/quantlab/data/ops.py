"""`quantlab data` operational commands: prefetch, refresh, scan, status.

Formalises the orchestrator's 2026-09-11 ad hoc prefetch script (which
populated the shared `data/cache` this platform's real runs use) into a
tested, repeatable module, and closes three CLI-carried operational gaps
QUANT-NOTES.md has tracked since M01/M02b/M04b:

- `data/corporate_actions.py`'s `refresh_actions_cache()` had no operational
  caller (M02b verdict item, reinforced by M04) - the ONLY way to clear a
  `StaleActionsCacheError` for a ticker, with no in-product recovery path
  before this module. Wired into `refresh(actions=True)`.
- `data/cache.py`'s negative-cache (`no_data`) sidecar had no force-clear
  (M04b work packet item 3, documented there but not implemented). Wired
  into `refresh(clear_negative_cache=True)` via `data/cache.py`'s
  `clear_no_data_meta`.
- `data/quality.py`'s `scan_price_cache`/`clear_quarantine_meta` had no CLI
  caller (M04b quant-gate VERDICT.md cycle 1 finding 2 / cycle 2 residual
  item). Wired into `scan()` and `refresh(unquarantine=...)`.

All network-touching paths (`prefetch`, and `refresh`'s
`actions`/`prices`/`fundamentals`/`unquarantine` flags) go through the SAME
provider classes the backtest engine uses (`data/interfaces.py::
build_provider`, `YFinanceCorporateActionsProvider`,
`EdgarFundamentalsProvider`) - there is no second fetch mechanism to keep in
sync. `scan()` and `status()` are fully offline (read-only against the
on-disk cache). Every network-touching path here is tested with fake
providers, never the real network (CLAUDE.md invariant #5); the real
`data/cache` is prefetched, warm, and out of scope for this milestone's
tests to touch (per the M09 work packet).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from quantlab.core.config import PlatformConfig
from quantlab.core.errors import ActionsFetchError, ConfigError, StaleActionsCacheError
from quantlab.data.cache import (
    clear_no_data_meta,
    clear_quarantine_meta,
    price_cache_path,
    price_meta_path,
    read_cache,
    read_json_meta,
)
from quantlab.data.corporate_actions import (
    YFinanceCorporateActionsProvider,
    refresh_actions_cache,
)
from quantlab.data.interfaces import build_provider
from quantlab.data.providers.edgar_fundamentals import (
    EdgarFundamentalsProvider,
    get_company_facts,
    load_ticker_cik_map,
)
from quantlab.data.quality import (
    QuarantineReport,
    membership_start_by_ticker,
    read_scan_manifest,
    scan_price_cache,
    unscanned_tickers,
)

_EPOCH = pd.Timestamp("1900-01-01")
_PREFETCH_REPORT_FILENAME = "prefetch_report.json"
_DEFAULT_UNIVERSE = "sp500_history"


# --- shared helpers ----------------------------------------------------------


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True, default=str), encoding="utf-8")


def _cached_price_tickers(cache_dir: Path) -> list[str]:
    """Every ticker with a cached price PARQUET (not a bare `no_data`
    sidecar - see `_all_sidecar_tickers` for the superset that includes
    those)."""
    prices_dir = Path(cache_dir) / "prices"
    if not prices_dir.is_dir():
        return []
    return sorted(p.stem for p in prices_dir.glob("*.parquet"))


def _all_sidecar_tickers(cache_dir: Path) -> list[str]:
    """Every ticker with a price sidecar - parquet, `no_data`-only, or
    quarantine-only - the superset `--all` operations should visit."""
    prices_dir = Path(cache_dir) / "prices"
    if not prices_dir.is_dir():
        return []
    tickers = {p.stem for p in prices_dir.glob("*.parquet")}
    for meta_path in prices_dir.glob("*.meta.json"):
        tickers.add(meta_path.name[: -len(".meta.json")])
    return sorted(tickers)


def build_prefetch_universe(
    constituents_provider: Any, start: object, end: object, benchmark: str | None = None
) -> list[str]:
    """Every point-in-time S&P 500 constituent whose membership could be
    seen at any point in [start, end], plus the benchmark - the universe
    logic the orchestrator's 2026-09-11 scratchpad script used (see
    plans/M04b-engine-perf.md's description of it), formalised here so
    `prefetch` and its tests share ONE definition rather than each
    reimplementing it.

    Unions two sources, deliberately: `membership_history(start, end)` (every
    membership CHANGE recorded strictly within the window - misses a ticker
    whose only relevant row is the last change BEFORE `start`) and
    `membership(start)` (the as-of snapshot AT `start`, which `backtest/
    engine.py`'s own `_full_universe_from_history` documents as a gap its
    OWN sizing tolerates via a provider fallback - `prefetch` has no such
    fallback available to it later, since its whole point is to WARM the
    cache before a backtest ever runs, so the gap is closed directly here
    instead of documented away)."""
    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
    tickers: set[str] = set(constituents_provider.membership(start_ts))
    history = constituents_provider.membership_history(start_ts, end_ts)
    if not history.empty:
        for members in history["tickers"]:
            tickers.update(members)
    if benchmark:
        tickers.add(benchmark)
    return sorted(tickers)


# --- prefetch ----------------------------------------------------------------


@dataclass(frozen=True)
class PrefetchReport:
    start: str
    end: str
    universe_size: int
    tickers: list[str] = field(default_factory=list)
    price_failures: dict[str, str] = field(default_factory=dict)
    actions_failures: dict[str, str] = field(default_factory=dict)
    fundamentals_failures: dict[str, str] = field(default_factory=dict)
    wall_seconds: float = 0.0

    def to_json(self) -> dict[str, Any]:
        return {
            "start": self.start,
            "end": self.end,
            "universe_size": self.universe_size,
            "tickers": self.tickers,
            "price_failures": self.price_failures,
            "actions_failures": self.actions_failures,
            "fundamentals_failures": self.fundamentals_failures,
            "wall_seconds": self.wall_seconds,
        }


def prefetch(
    platform_config: PlatformConfig,
    start: object,
    end: object,
    universe: str = _DEFAULT_UNIVERSE,
) -> PrefetchReport:
    """Prefetch prices, corporate actions (with `fetched_at` provenance) and
    EDGAR fundamentals facts for every point-in-time constituent over
    [start, end] plus the benchmark - one command in place of the
    orchestrator's ad hoc 2026-09-11 script. Idempotent: every provider
    below is cache-backed, so re-running this over an already-warm cache
    only re-fetches what a narrower prior run didn't cover (a wider
    `start`/`end`, a genuinely new ticker, or a `no_data`/stale-actions
    sidecar past its TTL) - see `data/cache.py`/`data/corporate_actions.py`.

    Per-ticker failures are NEVER raised - a coverage gap is exactly what
    `data/survivorship.py`'s coverage bound and this report exist to
    surface, not something one bad ticker should abort the whole prefetch
    over. Writes a per-ticker failure summary JSON to
    `<cache_dir>/prefetch_report.json` (the packet's own requirement) in
    addition to returning it.
    """
    if universe != _DEFAULT_UNIVERSE:
        raise ConfigError(f"unknown prefetch universe: {universe!r} (only {_DEFAULT_UNIVERSE!r})")

    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
    t0 = time.perf_counter()

    price_provider = build_provider("prices", platform_config.providers.prices, platform_config)
    constituents_provider = build_provider(
        "constituents", platform_config.providers.constituents, platform_config
    )
    actions_provider = YFinanceCorporateActionsProvider(cache_dir=platform_config.cache_dir)
    fundamentals_provider = EdgarFundamentalsProvider(cache_dir=platform_config.cache_dir)

    tickers = build_prefetch_universe(
        constituents_provider, start_ts, end_ts, platform_config.benchmark
    )

    panel = price_provider.get_prices(tickers, start_ts, end_ts)
    served = set(panel["ticker"].unique()) if not panel.empty else set()
    price_failures = {
        t: "no price data returned by the price provider (see the ticker's price cache sidecar)"
        for t in tickers
        if t not in served
    }

    actions_failures: dict[str, str] = {}
    for ticker in tickers:
        try:
            actions_provider.get_actions(ticker, _EPOCH, end_ts)
        except (StaleActionsCacheError, ActionsFetchError) as exc:
            actions_failures[ticker] = str(exc)

    fundamentals_failures: dict[str, str] = {}
    for ticker in tickers:
        try:
            facts = fundamentals_provider.get_pit_fundamentals(ticker, end_ts)
        except Exception as exc:  # noqa: BLE001 - a per-ticker coverage gap, never abort the run
            fundamentals_failures[ticker] = f"{exc.__class__.__name__}: {exc}"
            continue
        if facts.get("shares_outstanding") is None and facts.get("ttm_eps") is None:
            fundamentals_failures[ticker] = (
                "no usable EDGAR facts (no CIK match, or no XBRL data on file)"
            )

    report = PrefetchReport(
        start=str(start_ts.date()),
        end=str(end_ts.date()),
        universe_size=len(tickers),
        tickers=tickers,
        price_failures=price_failures,
        actions_failures=actions_failures,
        fundamentals_failures=fundamentals_failures,
        wall_seconds=time.perf_counter() - t0,
    )
    _write_json(Path(platform_config.cache_dir) / _PREFETCH_REPORT_FILENAME, report.to_json())
    return report


# --- refresh -------------------------------------------------------------


@dataclass(frozen=True)
class RefreshReport:
    tickers: list[str] = field(default_factory=list)
    actions_refreshed: list[str] = field(default_factory=list)
    actions_failures: dict[str, str] = field(default_factory=dict)
    prices_refreshed: list[str] = field(default_factory=list)
    prices_failures: dict[str, str] = field(default_factory=dict)
    fundamentals_refreshed: list[str] = field(default_factory=list)
    fundamentals_failures: dict[str, str] = field(default_factory=dict)
    negative_cache_cleared: list[str] = field(default_factory=list)
    unquarantine_result: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "tickers": self.tickers,
            "actions_refreshed": self.actions_refreshed,
            "actions_failures": self.actions_failures,
            "prices_refreshed": self.prices_refreshed,
            "prices_failures": self.prices_failures,
            "fundamentals_refreshed": self.fundamentals_refreshed,
            "fundamentals_failures": self.fundamentals_failures,
            "negative_cache_cleared": self.negative_cache_cleared,
            "unquarantine_result": self.unquarantine_result,
        }


def _requested_start_for(ticker: str, cache_dir: Path, default: pd.Timestamp) -> pd.Timestamp:
    meta = read_json_meta(price_meta_path(ticker, cache_dir))
    if meta is not None and "requested_start" in meta:
        return pd.Timestamp(meta["requested_start"])
    return default


def refresh(
    platform_config: PlatformConfig,
    *,
    tickers: list[str] | None = None,
    do_all: bool = False,
    actions: bool = False,
    prices: bool = False,
    fundamentals: bool = False,
    clear_negative_cache: bool = False,
    unquarantine: str | None = None,
    default_start: object = pd.Timestamp("2010-01-01"),
    as_of: object | None = None,
) -> RefreshReport:
    """Operational data-refresh command. Exactly one of `tickers`/`do_all`
    resolves which tickers `actions`/`prices`/`fundamentals`/
    `clear_negative_cache` (when it isn't scoped to `tickers` alone) act on;
    `unquarantine` is independent and always acts on the single ticker it
    names, regardless of `tickers`/`do_all`.

    `actions`: force a fresh download of each ticker's corporate-actions
    history and reset the staleness sidecar (`refresh_actions_cache`) - the
    ONLY way to clear a `StaleActionsCacheError` (QUANT-NOTES.md M02b/M04
    carried item).
    `prices`: re-fetch each ticker through `as_of` (default: today) via the
    SAME price provider a backtest uses - a wider `requested_end` than the
    existing sidecar makes `has_sufficient_price_cache` (data/cache.py)
    treat the cache as insufficient and re-fetch, exactly the "re-fetches
    prices past requested_end" the work packet describes.
    `fundamentals`: force a fresh EDGAR companyfacts download
    (`get_company_facts(..., force_refresh=True)`).
    `clear_negative_cache`: force-clear a `no_data` sidecar
    (`data/cache.py`'s `clear_no_data_meta`) - scoped to `tickers` if given,
    else every ticker in the cache currently flagged `no_data` (M04b work
    packet item 3, implemented here).
    `unquarantine`: clear one ticker's quarantine verdict
    (`clear_quarantine_meta`), re-fetch its prices, and re-scan ONLY that
    ticker (`data/quality.py`'s `scan_price_cache(..., tickers=[ticker])`) -
    `unquarantine_result` is `"still_quarantined"` if the re-scan finds the
    same (or a new) reason, `"cleared"` otherwise.
    """
    as_of_ts = pd.Timestamp(as_of) if as_of is not None else pd.Timestamp.now().normalize()
    default_start_ts = pd.Timestamp(default_start)
    cache_dir = Path(platform_config.cache_dir)

    if do_all:
        resolved = _all_sidecar_tickers(cache_dir)
    else:
        resolved = sorted(tickers) if tickers else []

    report_kwargs: dict[str, Any] = {"tickers": resolved}

    if actions:
        refreshed, failed = [], {}
        for ticker in resolved:
            try:
                refresh_actions_cache(ticker, cache_dir)
                refreshed.append(ticker)
            except Exception as exc:  # noqa: BLE001 - one ticker's failure must not abort the batch
                failed[ticker] = f"{exc.__class__.__name__}: {exc}"
        report_kwargs["actions_refreshed"] = refreshed
        report_kwargs["actions_failures"] = failed

    if prices:
        price_provider = build_provider("prices", platform_config.providers.prices, platform_config)
        refreshed, failed = [], {}
        for ticker in resolved:
            requested_start = _requested_start_for(ticker, cache_dir, default_start_ts)
            try:
                price_provider.get_prices([ticker], requested_start, as_of_ts)
                refreshed.append(ticker)
            except Exception as exc:  # noqa: BLE001 - one ticker's failure must not abort the batch
                failed[ticker] = f"{exc.__class__.__name__}: {exc}"
        report_kwargs["prices_refreshed"] = refreshed
        report_kwargs["prices_failures"] = failed

    if fundamentals:
        cik_map = load_ticker_cik_map(cache_dir)
        refreshed, failed = [], {}
        for ticker in resolved:
            cik = cik_map.get(ticker)
            if cik is None:
                failed[ticker] = "no CIK match in SEC's ticker map"
                continue
            try:
                get_company_facts(ticker, cik, cache_dir, force_refresh=True)
                refreshed.append(ticker)
            except Exception as exc:  # noqa: BLE001 - one ticker's failure must not abort the batch
                failed[ticker] = f"{exc.__class__.__name__}: {exc}"
        report_kwargs["fundamentals_refreshed"] = refreshed
        report_kwargs["fundamentals_failures"] = failed

    if clear_negative_cache:
        candidates = resolved if (tickers or do_all) else _no_data_tickers(cache_dir)
        cleared = [t for t in candidates if clear_no_data_meta(t, cache_dir)]
        report_kwargs["negative_cache_cleared"] = cleared

    if unquarantine is not None:
        clear_quarantine_meta(unquarantine, cache_dir)
        # Always re-fetch before re-scanning (packet: "re-fetches and
        # re-scans one name") - a stale, un-refreshed cache would just
        # reproduce whatever verdict the earlier scan already reached.
        unquarantine_price_provider = build_provider(
            "prices", platform_config.providers.prices, platform_config
        )
        requested_start = _requested_start_for(unquarantine, cache_dir, default_start_ts)
        try:
            unquarantine_price_provider.get_prices([unquarantine], requested_start, as_of_ts)
        except Exception:  # noqa: BLE001 - re-scan whatever is on disk either way
            pass
        rescan = scan_price_cache(cache_dir, tickers=[unquarantine])
        report_kwargs["unquarantine_result"] = (
            "still_quarantined" if unquarantine in rescan.quarantined else "cleared"
        )

    return RefreshReport(**report_kwargs)


def _no_data_tickers(cache_dir: Path) -> list[str]:
    prices_dir = Path(cache_dir) / "prices"
    if not prices_dir.is_dir():
        return []
    result = []
    for meta_path in prices_dir.glob("*.meta.json"):
        ticker = meta_path.name[: -len(".meta.json")]
        meta = read_json_meta(meta_path)
        if meta is not None and meta.get("no_data"):
            result.append(ticker)
    return sorted(result)


# --- scan ------------------------------------------------------------------


def scan(
    platform_config: PlatformConfig, constituents_provider: Any | None = None
) -> QuarantineReport:
    """`data/quality.py`'s `scan_price_cache`, wired to the platform config's
    quality thresholds and (when a `ConstituentsProvider` is available) the
    membership-aware symbol-reuse detector - the CLI caller QUANT-NOTES.md
    (M04b) has tracked as missing since the checks themselves shipped.
    Fully offline: reads only what is already on disk."""
    cache_dir = Path(platform_config.cache_dir)
    membership_map: dict[str, pd.Timestamp] | None = None
    if constituents_provider is not None:
        history = constituents_provider.membership_history(_EPOCH, pd.Timestamp.now())
        membership_map = membership_start_by_ticker(history)

    return scan_price_cache(
        cache_dir,
        zero_volume_fraction_threshold=platform_config.quality_zero_volume_fraction_threshold,
        zero_volume_hard_threshold=platform_config.quality_zero_volume_hard_threshold,
        level_implausible_ratio=platform_config.quality_level_implausible_ratio,
        jump_ratio_threshold=platform_config.quality_jump_ratio_threshold,
        jump_excuse_window_sessions=platform_config.quality_jump_excuse_window_sessions,
        min_unexplained_jumps=platform_config.quality_min_unexplained_jumps,
        gap_sessions_threshold=platform_config.quality_jump_gap_sessions,
        membership_start_by_ticker_map=membership_map,
        new_listing_tolerance_sessions=platform_config.quality_new_listing_tolerance_sessions,
    )


# --- status ------------------------------------------------------------------


@dataclass(frozen=True)
class StatusReport:
    price_ticker_count: int
    actions_ticker_count: int
    fundamentals_ticker_count: int
    actions_fetched_at_oldest: str | None
    actions_fetched_at_newest: str | None
    no_data_count: int
    no_data_tickers: list[str]
    quarantined: dict[str, list[str]]
    masked_truncation_count: int
    masked_truncation_tickers: list[str]
    never_scanned_count: int
    never_scanned_tickers: list[str]
    scan_checked_at: str | None

    def to_json(self) -> dict[str, Any]:
        return {
            "price_ticker_count": self.price_ticker_count,
            "actions_ticker_count": self.actions_ticker_count,
            "fundamentals_ticker_count": self.fundamentals_ticker_count,
            "actions_fetched_at_oldest": self.actions_fetched_at_oldest,
            "actions_fetched_at_newest": self.actions_fetched_at_newest,
            "no_data_count": self.no_data_count,
            "no_data_tickers": self.no_data_tickers,
            "quarantined": self.quarantined,
            "masked_truncation_count": self.masked_truncation_count,
            "masked_truncation_tickers": self.masked_truncation_tickers,
            "never_scanned_count": self.never_scanned_count,
            "never_scanned_tickers": self.never_scanned_tickers,
            "scan_checked_at": self.scan_checked_at,
        }


# A requested_end more than this many days past the real last bar counts as
# a masked truncation - mirrors data/cache.py's CACHE_DATE_TOLERANCE_DAYS so
# a boundary date (a requested_end that lands on a weekend/holiday) is never
# misreported as truncated.
_MASKED_TRUNCATION_TOLERANCE_DAYS = 7


def status(platform_config: PlatformConfig) -> StatusReport:
    """Cache coverage report: how many tickers are cached per data kind,
    the actions cache's `fetched_at` range (the negative-cache/actions-
    staleness TTL makes runs wall-clock dependent - QUANT-NOTES.md M04b/M06
    carried item; this number is how a reader can tell), how many tickers
    are currently suppressed by a live `no_data` sidecar, which are
    quarantined and why, how many have a masked (cache-metadata-truncated)
    price history, and how many the last `scan()` never visited at all.
    Fully offline."""
    cache_dir = Path(platform_config.cache_dir)
    prices_dir = cache_dir / "prices"
    actions_dir = cache_dir / "actions"
    fundamentals_dir = cache_dir / "fundamentals"

    price_tickers = _cached_price_tickers(cache_dir)
    actions_tickers = (
        sorted(p.stem for p in actions_dir.glob("*.parquet")) if actions_dir.is_dir() else []
    )
    fundamentals_tickers = (
        sorted(p.stem for p in fundamentals_dir.glob("*.parquet"))
        if fundamentals_dir.is_dir()
        else []
    )

    fetched_ats: list[str] = []
    for ticker in actions_tickers:
        meta = read_json_meta(actions_dir / f"{ticker}.meta.json")
        if meta is not None and meta.get("fetched_at"):
            fetched_ats.append(meta["fetched_at"])
    fetched_ats.sort()

    no_data_tickers: list[str] = []
    quarantined: dict[str, list[str]] = {}
    masked_truncation_tickers: list[str] = []
    tolerance = pd.Timedelta(days=_MASKED_TRUNCATION_TOLERANCE_DAYS)
    if prices_dir.is_dir():
        for meta_path in sorted(prices_dir.glob("*.meta.json")):
            ticker = meta_path.name[: -len(".meta.json")]
            meta = read_json_meta(meta_path)
            if meta is None:
                continue
            if meta.get("no_data"):
                no_data_tickers.append(ticker)
            if meta.get("quarantined"):
                quarantined[ticker] = list(meta.get("reasons", []))
            if "requested_end" in meta:
                cached = read_cache(price_cache_path(ticker, cache_dir))
                if cached is not None and not cached.empty:
                    last_bar = pd.Timestamp(cached.index.max())
                    requested_end = pd.Timestamp(meta["requested_end"])
                    if requested_end > last_bar + tolerance:
                        masked_truncation_tickers.append(ticker)

    manifest = read_scan_manifest(cache_dir)
    never_scanned = unscanned_tickers(cache_dir, price_tickers)

    return StatusReport(
        price_ticker_count=len(price_tickers),
        actions_ticker_count=len(actions_tickers),
        fundamentals_ticker_count=len(fundamentals_tickers),
        actions_fetched_at_oldest=fetched_ats[0] if fetched_ats else None,
        actions_fetched_at_newest=fetched_ats[-1] if fetched_ats else None,
        no_data_count=len(no_data_tickers),
        no_data_tickers=sorted(no_data_tickers),
        quarantined=quarantined,
        masked_truncation_count=len(masked_truncation_tickers),
        masked_truncation_tickers=sorted(masked_truncation_tickers),
        never_scanned_count=len(never_scanned),
        never_scanned_tickers=never_scanned,
        scan_checked_at=manifest["checked_at"] if manifest else None,
    )
