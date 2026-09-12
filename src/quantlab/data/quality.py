"""Data quality checks for price panels.

Vendor data isn't guaranteed to be clean - bad prints, unadjusted splits,
and other glitches happen. We can't fix bad data, but we CAN flag it
instead of trusting it silently, and record how many flagged observations a
backtest consumed. That turns "trust the vendor blindly" into "trust the
vendor, but flag what looks wrong".

Two independent checks feed `QualityGate.scan` (a REQUEST-scoped scan: it
flags individual rows within one already-fetched panel, never mutates or
drops anything, and is not itself wired into any production read path -
see the module-level `scan_price_cache` below for the mechanism that is):

1. Outlier returns (ported from the old repo's `quality_checks.py`):
   single-day |adjusted-close return| beyond a threshold (default 50%) is
   far more often a bad print or an unadjusted corporate action slipping
   through than genuine price action, especially for large, liquid names.
2. OHLC sanity (added per plans/QUANT-NOTES.md's M00 gate): low <= open/close
   <= high, non-negative volume, strictly positive prices. Individual bad
   rows are flagged, not dropped; `DataQualityError` is raised only when the
   *entire* input panel fails sanity, since that indicates wholly corrupt
   input (e.g. a malformed vendor response) rather than a handful of bad
   prints worth flagging and moving on from.

## Cache-level quarantine (M04b quant-gate VERDICT.md cycle 1 finding 2)

`QualityGate.scan` above never ran in production - no caller anywhere in
`src/` wired it into the price ingestion boundary (the M00->M01 carried
item plans/QUANT-NOTES.md tracks). The first real 2012-2026 run exposed why
that matters: Yahoo silently reassigns a delisted ticker's symbol to an
unrelated instrument, and this platform's yfinance provider requests by
bare symbol - so a cached "PTV" or "TIE" parquet can be a splice of several
genuinely different companies' price histories under one symbol. Two of
these (TIE, BMC) reached the real portfolio and moved the quoted 17.84% net
CAGR by an amount nobody can currently state - see plans/state/M04b/
HANDOFF.2.md.

`zero_volume_fraction`, `unexplained_jump_dates`, and
`symbol_reuse_gap_reasons` below are three NEW, CACHE-scoped checks (they
look at a ticker's WHOLE cached history, not one request's panel) that
`scan_price_cache` runs over every ticker in an on-disk cache directory,
quarantining (via `data/cache.py`'s `write_quarantine_meta`) any ticker that
fails one:

- **Zero-volume fraction**: a listed US equity essentially never prints a
  session with zero shares traded (padding artifacts excluded first - see
  `zero_volume_fraction`'s docstring). Quarantines ALONE only above
  `PlatformConfig.quality_zero_volume_hard_threshold` (default 0.50 -
  CCE/MHS-style genuinely dead series, 100% zero-volume real bars); between
  `quality_zero_volume_fraction_threshold` (default 0.20) and the hard bar,
  only WITH an implausible price level alongside it
  (`quality_level_implausible_ratio`, default 20x - see `_level_implausible`).
  Cycle 2: the naive "fraction alone above 0.20" version quarantined ~20
  live large caps (EA, EQR, FERG, AMCR, COL, HOT, SW, CPWR, ...) purely from
  yfinance batch-download padding; see this module's "cache-level quarantine
  checks" section comment for the confirmed root cause.
- **Unexplained price jump**: a consecutive-session close ratio beyond
  `PlatformConfig.quality_jump_ratio_threshold` (default 4.0x), in EITHER
  direction, that no split in the ticker's OWN gated actions history
  explains within `quality_jump_excuse_window_sessions` sessions (not only
  an exact ex-date match). Quarantines only at
  `quality_min_unexplained_jumps` (default 3) or more such dates - a SINGLE
  jump is as often a real, un-split corporate event (KDP's 2018 Keurig/Dr
  Pepper Snapple merger) as contamination (the gate's TIE evidence: ~$16
  bars interleaved with ~$7,000-8,200 bars across 190 separate dates, a
  >400x ratio with no split on file - the REPEATED nature is what
  distinguishes it, not any single occurrence).
- **Symbol reuse across a gap**: a ticker's cached history is missing a run
  of `PlatformConfig.quality_jump_gap_sessions` (default 5) or more
  EXPECTED trading sessions (per `core.calendar.trading_days` over the
  cache's own span), AND the trailing-year median price after the gap
  differs from the trailing-year median before it by more than the jump
  ratio threshold. A real company's price level does not usually jump this
  much across a trading halt; a NEW company trading under a reused symbol
  after the original was delisted routinely will.

A quarantined ticker is never silently invisible: `has_sufficient_price_
cache` (data/cache.py) refuses to serve it (an empty frame, no TTL) so it
never reaches a strategy, and `price_availability_from_cache`
(data/survivorship.py) reports it as lacking data with reason
"quarantined" so the coverage bound counts it rather than looking clean.
`backtest/engine.py`'s provenance records the quarantined count and ticker
list for the run. `scan_price_cache` itself has no CLI caller yet - M09's
`quantlab data scan` is expected to expose it (carried item, out of this
milestone's scope; see plans/QUANT-NOTES.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from quantlab.core.calendar import trading_days
from quantlab.core.errors import DataQualityError
from quantlab.data.cache import (
    price_cache_path,
    price_meta_path,
    read_cache,
    read_json_meta,
    write_quarantine_meta,
)
from quantlab.data.corporate_actions import read_cached_actions
from quantlab.data.interfaces import PriceProvider

REQUIRED_PRICE_COLUMNS = ("ticker", "open", "high", "low", "close", "adj_close", "volume")

_FLAG_COLUMNS = ("ticker", "date", "reason")


class QualityGate:
    """Scans a long-format price panel (see `PriceProvider.get_prices`) for
    suspicious rows and returns a flag report; never mutates or drops rows
    from the input itself."""

    def __init__(self, outlier_threshold: float = 0.5):
        self.outlier_threshold = outlier_threshold

    def scan(self, panel: pd.DataFrame) -> pd.DataFrame:
        """Return a long DataFrame of flags: columns [ticker, date, reason].

        Raises `DataQualityError` if every row in a non-empty panel fails
        the OHLC sanity check (wholly corrupt input) or if the panel is
        missing required columns.
        """
        if panel.empty:
            return pd.DataFrame(columns=list(_FLAG_COLUMNS))

        missing = [c for c in REQUIRED_PRICE_COLUMNS if c not in panel.columns]
        if missing:
            raise DataQualityError(f"price panel missing required columns: {missing}")

        ohlc_flags = self._scan_ohlc_sanity(panel)
        if len(ohlc_flags) == len(panel):
            raise DataQualityError(
                f"all {len(panel)} rows failed OHLC sanity checks - input looks wholly corrupt"
            )

        duplicate_flags, deduped = self._scan_duplicates(panel)
        outlier_flags = self._scan_outliers(deduped)

        flags = pd.concat([ohlc_flags, duplicate_flags, outlier_flags], ignore_index=True)
        if flags.empty:
            return pd.DataFrame(columns=list(_FLAG_COLUMNS))
        return flags.sort_values(["date", "ticker"]).reset_index(drop=True)

    def _scan_duplicates(self, panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Flag duplicate (date, ticker) rows and return (flags, deduped panel).

        A duplicate (date, ticker) pair is itself a data-quality bug in the
        input; silently averaging it away (as `pivot_table`'s default
        aggfunc would) runs against QualityGate's whole purpose. Instead,
        every occurrence after the first is flagged as `duplicate_row`, and
        the outlier scan runs on the first-occurrence-only panel so `pivot`
        (which raises on duplicates, rather than averaging) stays safe.
        """
        pair_key = pd.MultiIndex.from_arrays([panel.index, panel["ticker"]])
        dup_mask = pair_key.duplicated(keep="first")
        if not dup_mask.any():
            return pd.DataFrame(columns=list(_FLAG_COLUMNS)), panel

        flags = pd.DataFrame(
            {
                "ticker": panel.loc[dup_mask, "ticker"].to_numpy(),
                "date": panel.index[dup_mask],
                "reason": "duplicate_row",
            }
        )
        return flags, panel.loc[~dup_mask]

    def _scan_ohlc_sanity(self, panel: pd.DataFrame) -> pd.DataFrame:
        low_le_open = panel["low"] <= panel["open"]
        open_le_high = panel["open"] <= panel["high"]
        low_le_close = panel["low"] <= panel["close"]
        close_le_high = panel["close"] <= panel["high"]
        nonneg_volume = panel["volume"] >= 0
        price_cols = panel[["open", "high", "low", "close", "adj_close"]]
        positive_prices = (price_cols > 0).all(axis=1)

        checks = {
            "low_gt_open": ~low_le_open,
            "open_gt_high": ~open_le_high,
            "low_gt_close": ~low_le_close,
            "close_gt_high": ~close_le_high,
            "negative_volume": ~nonneg_volume,
            "non_positive_price": ~positive_prices,
        }
        invalid = pd.concat(checks.values(), axis=1).any(axis=1)
        if not invalid.any():
            return pd.DataFrame(columns=list(_FLAG_COLUMNS))

        bad_idx = panel.index[invalid]
        bad = panel.loc[invalid]
        reasons = []
        for pos in range(len(bad)):
            row_failed = [name for name, mask in checks.items() if mask.loc[invalid].iloc[pos]]
            reasons.append(",".join(row_failed))

        return pd.DataFrame(
            {
                "ticker": bad["ticker"].to_numpy(),
                "date": bad_idx,
                "reason": [f"ohlc_sanity:{r}" for r in reasons],
            }
        )

    def _scan_outliers(self, panel: pd.DataFrame) -> pd.DataFrame:
        # `panel` has already been deduplicated by _scan_duplicates, so
        # `pivot` cannot hit its duplicate-entries error; it is used instead
        # of `pivot_table` precisely because it raises rather than silently
        # averaging should that invariant ever break.
        # noqa rationale: PD010 prefers pivot_table, but pivot_table's
        # default aggfunc silently AVERAGES duplicates - the exact failure
        # mode this method must not have.
        wide = (
            panel.reset_index(names="date")  # noqa: PD010
            .pivot(index="date", columns="ticker", values="adj_close")
            .sort_index()
        )
        daily_returns = wide.pct_change()
        flagged = daily_returns[daily_returns.abs() > self.outlier_threshold]

        # NOTE: DataFrame.stack() does not drop all-NaN rows by default in
        # this pandas version, so it must be dropped explicitly - otherwise
        # every non-flagged (NaN-masked) cell would show up as a spurious
        # "flagged" row. See the old repo's quality_checks.py for the same
        # fix under pandas 2.x.
        # noqa rationale: PD013 suggests melt, but stack().dropna() is the
        # old repo's frozen ported logic (parity; see module docstring).
        flagged_long = flagged.stack().dropna().reset_index()  # noqa: PD013
        flagged_long.columns = ["date", "ticker", "daily_return"]
        if flagged_long.empty:
            return pd.DataFrame(columns=list(_FLAG_COLUMNS))

        flagged_long["reason"] = flagged_long["daily_return"].map(
            lambda r: f"outlier_return:{r:+.1%}"
        )
        return flagged_long[["ticker", "date", "reason"]]


# -- cache-level quarantine checks (M04b quant-gate VERDICT.md finding 2) ----

# Cycle 2 (VERDICT.2.md-equivalent feedback, folded in mid-loop): the FIRST
# version of these checks quarantined ~20 live, legitimate large caps
# (EA, EQR, FERG, AMCR, COL, HOT, SW, CPWR, ...) purely on zero-volume
# fraction, and a handful more (KDP, MI, POM, STI) on a single price jump.
# Root cause, confirmed directly against the shared cache: yfinance's batch
# download forward-fills a ticker's LAST KNOWN close (with volume=0) for any
# session in the batch's combined date range where that ticker itself has no
# real bar - `ticker_df.dropna(how="all")` (providers/yfinance_prices.py)
# does not drop these rows since the price columns are non-NaN, only volume
# is zero. EA's real cache is a concrete example: 6 rows total, 4 of them an
# IDENTICAL repeated close at volume=0. The fixes below are additive
# tightenings, not a different design: zero-volume fraction now EXCLUDES
# these padding rows before computing anything, and each check requires a
# stronger, harder-to-fake signal (a HIGH bar alone, or a moderate one
# combined with an implausible price level; several unexplained jumps, not
# one) before quarantining - see each function's own docstring.
_DEFAULT_ZERO_VOLUME_FRACTION_THRESHOLD = 0.20
_DEFAULT_ZERO_VOLUME_HARD_THRESHOLD = 0.50
_DEFAULT_LEVEL_IMPLAUSIBLE_RATIO = 20.0
_DEFAULT_JUMP_RATIO_THRESHOLD = 4.0
_DEFAULT_MIN_UNEXPLAINED_JUMPS = 3
_DEFAULT_JUMP_EXCUSE_WINDOW_SESSIONS = 3
_DEFAULT_GAP_SESSIONS_THRESHOLD = 5
_DEFAULT_NEW_LISTING_TOLERANCE_SESSIONS = 400
_ACTION_TYPE_SPLIT = "split"
_TRAILING_YEAR_SESSIONS = 252

# The on-disk price cache (data/cache.py's `price_cache_path`) stores
# yfinance's RAW, Yahoo-style capitalized columns as written by
# `YFinancePriceProvider.get_prices` - the lowercase rename
# (`providers/yfinance_prices.py`'s `_YF_COLUMN_MAP`) happens only on the
# PROVIDER's own read path, not in the cached file itself. `scan_price_cache`
# reads the cache directly (never through the provider), so it must apply
# the identical rename here - duplicated rather than imported, since
# `data/quality.py` must not depend on a specific vendor's provider module
# (the same reasoning `data/cache.py`'s own `_EMPTY_RAW_PRICE_COLUMNS`
# documents). Keep the two in sync if either changes.
_RAW_COLUMN_MAP = {
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Adj Close": "adj_close",
    "Volume": "volume",
}


def zero_volume_fraction(panel: pd.DataFrame) -> float:
    """Fraction of `panel`'s REAL trading bars with `volume == 0` - a listed
    US equity essentially never prints a genuine zero-volume session.

    EXCLUDES yfinance forward-fill padding first: a row with `volume == 0`
    AND a `close` IDENTICAL to the prior row's is a non-trading-day
    placeholder the vendor's batch download stitched in (confirmed against
    the shared cache - see this section's module-level comment), not a
    genuine session. A real zero-volume print, if one ever occurred, would
    still have its own independently-reported (not repeated) close, so this
    exclusion cannot hide a genuine anomaly - it only removes rows that are
    ALSO indistinguishable from "no data for this date at all"."""
    if panel.empty:
        return 0.0
    volume, close = panel["volume"], panel["close"]
    padding = (volume == 0) & (close == close.shift(1))
    real = panel.loc[~padding]
    if real.empty:
        return 0.0
    return float((real["volume"] == 0).mean())


def _level_implausible(
    closes: pd.Series, ratio_threshold: float = _DEFAULT_LEVEL_IMPLAUSIBLE_RATIO
) -> bool:
    """Whether `closes`' OVERALL median differs from its OWN trailing-year
    median by more than `ratio_threshold`x - the signature of a series
    spanning two wildly different price regimes (e.g. a splice of two
    different instruments under one symbol). Used as a companion condition:
    a MODERATE zero-volume fraction alone is not damning (see
    `zero_volume_fraction`'s docstring on padding), but combined with an
    implausible price level it is much more likely genuine contamination."""
    if closes.empty:
        return False
    trailing = closes.tail(_TRAILING_YEAR_SESSIONS)
    if trailing.empty:
        return False
    overall_median, trailing_median = float(closes.median()), float(trailing.median())
    if overall_median <= 0 or trailing_median <= 0:
        return False
    ratio = max(overall_median / trailing_median, trailing_median / overall_median)
    return ratio > ratio_threshold


def unexplained_jump_dates(
    panel: pd.DataFrame,
    actions: pd.DataFrame | None,
    ratio_threshold: float = _DEFAULT_JUMP_RATIO_THRESHOLD,
    excuse_window_sessions: int = _DEFAULT_JUMP_EXCUSE_WINDOW_SESSIONS,
) -> list[pd.Timestamp]:
    """Dates where `panel`'s close moved by more than `ratio_threshold`x
    (either direction) from the PRIOR cached session, with no split action
    in `actions` (the format `data/corporate_actions.py` emits) dated within
    `excuse_window_sessions` CACHED SESSIONS of that jump (not only an exact
    ex-date match - cycle-2 widening: a genuine corporate action can be
    recorded by the vendor's actions feed a session or two off from where
    its price effect actually lands, e.g. a reverse split; this widening is
    still restrict-only relative to over-quarantining - it can only EXCUSE
    more jumps, never manufacture new ones). See module docstring's
    "Unexplained price jump" section.

    A single (or even two) unexplained jump is deliberately NOT treated as
    quarantine-worthy by the CALLER (`scan_price_cache`) on its own - a
    genuine, un-split corporate restructuring (a merger, a large special
    distribution) produces exactly one clean level transition, and the
    shared cache's own evidence (KDP's 2018 Keurig/Dr Pepper Snapple merger:
    1 date; MI, POM, STI: 1-2 dates each) is indistinguishable from that at
    the single-jump level. Multiple names days apart (PTV: 5, MEE: 25,
    CPWR: 19, BMC: 33, TIE: 190, CBE: 329) is the actual reuse signature.
    This function only reports the raw (excused-by-proximity) list; the
    count-based decision lives in `scan_price_cache`."""
    if len(panel) < 2:
        return []
    closes = panel["close"].sort_index()
    ratios = closes / closes.shift(1)
    jump_mask = (ratios > ratio_threshold) | (ratios < 1.0 / ratio_threshold)
    jump_dates = list(closes.index[jump_mask.fillna(False)])
    if not jump_dates:
        return []

    split_dates: set[pd.Timestamp] = set()
    if actions is not None and not actions.empty:
        split_dates = set(actions.loc[actions["action_type"] == _ACTION_TYPE_SPLIT].index)
    if not split_dates:
        return jump_dates

    panel_dates = list(closes.index)
    position = {d: i for i, d in enumerate(panel_dates)}
    unexplained = []
    for d in jump_dates:
        i = position[d]
        window = panel_dates[max(0, i - excuse_window_sessions) : i + excuse_window_sessions + 1]
        if split_dates.isdisjoint(window):
            unexplained.append(d)
    return unexplained


def _consecutive_missing_runs(
    expected_sessions: pd.DatetimeIndex, present: set[pd.Timestamp]
) -> list[tuple[int, int]]:
    """(start_idx, end_idx) INCLUSIVE index pairs into `expected_sessions`
    for each maximal run of sessions absent from `present`."""
    runs: list[tuple[int, int]] = []
    n = len(expected_sessions)
    i = 0
    while i < n:
        if expected_sessions[i] not in present:
            j = i
            while j + 1 < n and expected_sessions[j + 1] not in present:
                j += 1
            runs.append((i, j))
            i = j + 1
        else:
            i += 1
    return runs


def symbol_reuse_gap_reasons(
    panel: pd.DataFrame,
    ratio_threshold: float = _DEFAULT_JUMP_RATIO_THRESHOLD,
    min_gap_sessions: int = _DEFAULT_GAP_SESSIONS_THRESHOLD,
) -> list[str]:
    """Human-readable reason strings for each GAP (a run of at least
    `min_gap_sessions` consecutive EXPECTED trading sessions - per
    `core.calendar.trading_days` over `panel`'s own cached span - missing
    from `panel`'s index) across which the trailing-year median close moves
    by more than `ratio_threshold`x. See module docstring's "Symbol reuse
    across a gap" section."""
    if panel.empty or len(panel) < 2:
        return []

    expected = trading_days(panel.index.min(), panel.index.max())
    present = set(panel.index)
    runs = _consecutive_missing_runs(expected, present)
    if not runs:
        return []

    closes = panel["close"].sort_index()
    reasons: list[str] = []
    for start_idx, end_idx in runs:
        if (end_idx - start_idx + 1) < min_gap_sessions:
            continue
        gap_start, gap_end = expected[start_idx], expected[end_idx]
        before = closes.loc[closes.index < gap_start].tail(_TRAILING_YEAR_SESSIONS)
        after = closes.loc[closes.index > gap_end].head(_TRAILING_YEAR_SESSIONS)
        if before.empty or after.empty:
            continue
        median_before, median_after = float(before.median()), float(after.median())
        if median_before <= 0 or median_after <= 0:
            continue
        ratio = max(median_after / median_before, median_before / median_after)
        if ratio > ratio_threshold:
            reasons.append(
                f"symbol_reuse_across_gap:{gap_start.date()}..{gap_end.date()} "
                f"median_ratio={ratio:.1f}x"
            )
    return reasons


def membership_start_by_ticker(history: pd.DataFrame) -> dict[str, pd.Timestamp]:
    """Start of each ticker's MOST RECENT CONTIGUOUS point-in-time
    membership span - the change-event date at which it last transitioned
    from ABSENT to PRESENT across consecutive rows of `history`'s `tickers`
    column (the format `ConstituentsProvider.membership_history` returns).

    Deliberately NOT "the earliest date this ticker ever appears": a symbol
    that left the index and was later reused by an unrelated company (or
    genuinely re-admitted) shows up in the record as two separate spans, and
    `symbol_reuse_new_listing_reason` needs the CURRENT holder's own span
    start to judge whether ITS listing is genuine - an old, unrelated span
    decades ago must not count against a symbol legitimately in use today
    (confirmed against the shared cache's own evidence: SanDisk's original
    "SNDK" membership predates 2010, but the CURRENT "SNDK" - a 2025
    re-spinoff - re-enters the index with its own new span, and only that
    new span's start is the relevant comparison point). A ticker with no
    gap in its whole recorded history (the common case) gets the same
    answer either way - its first-ever appearance IS its only span's start."""
    starts: dict[str, pd.Timestamp] = {}
    if history.empty or "tickers" not in history.columns:
        return starts
    previously_present: set[str] = set()
    for date, members in history.sort_index()["tickers"].items():
        current = set(members)
        for ticker in current - previously_present:
            starts[ticker] = pd.Timestamp(date)
        previously_present = current
    return starts


def symbol_reuse_new_listing_reason(
    first_bar: pd.Timestamp,
    membership_start: pd.Timestamp | None,
    requested_start: pd.Timestamp | None,
    tolerance_sessions: int = _DEFAULT_NEW_LISTING_TOLERANCE_SESSIONS,
) -> str | None:
    """Whether a ticker's cached price history starts suspiciously LATER
    than BOTH (a) what this cache was actually asked to fetch from
    (`requested_start` - the sidecar's own recorded floor, `data/cache.py`'s
    `write_price_cache_meta`) and (b) its point-in-time index membership
    (`membership_start`) - Yahoo silently reassigns a delisted ticker's
    symbol to an unrelated instrument, and that new instrument's price
    history naturally starts recently, long after both the ORIGINAL
    constituent joined the index AND this cache's own fetch window began
    (confirmed: EA - requested from 2010-06-01, membership since
    2002-07-22, cached history starts 2026-07-17, the week Electronic Arts
    was taken private and the symbol was reissued; EQR, LEG, AVB are the
    same pattern).

    BOTH conditions are required, not just (b) alone - an earlier version of
    this check compared only against `membership_start` and flagged nearly
    the ENTIRE shared cache (IBM, MSFT, JNJ, ... every long-standing
    constituent whose S&P membership predates this cache's own 2010-06-01
    prefetch floor, which is a documented, deliberate limitation of THIS
    cache's fetch window - not evidence of anything wrong with the ticker).
    Requiring the cache's OWN requested_start to also be exceeded correctly
    excludes every such case (their first bar sits exactly AT the requested
    floor) while still catching every confirmed reuse case (whose first bar
    sits far past it).

    `None` if either date is unknown, or the cached history starts ON OR
    BEFORE either reference point (a company's price history routinely
    predates its OWN index membership, e.g. FERG/AMCR/PARA in the shared
    cache, and must never trigger this) or within `tolerance_sessions`
    TRADING SESSIONS of either (index-membership dates from a free,
    community source are approximate, and a real vendor gap of a few
    months is not on its own suspicious)."""
    if membership_start is None or requested_start is None:
        return None
    if first_bar <= requested_start or first_bar <= membership_start:
        return None
    if len(trading_days(requested_start, first_bar)) <= tolerance_sessions:
        return None
    if len(trading_days(membership_start, first_bar)) <= tolerance_sessions:
        return None
    return (
        f"symbol_reuse_new_listing (first_bar={first_bar.date()}, "
        f"membership={membership_start.date()}, requested_start={requested_start.date()})"
    )


def heal_or_flag_new_listings(
    cache_dir: Path,
    price_provider: PriceProvider,
    membership_start_by_ticker_map: dict[str, pd.Timestamp],
    requested_start: object,
    requested_end: object,
    tolerance_sessions: int = _DEFAULT_NEW_LISTING_TOLERANCE_SESSIONS,
) -> dict[str, str]:
    """Before trusting `symbol_reuse_new_listing_reason`'s verdict, give
    every CANDIDATE ticker (cached first bar later than its point-in-time
    membership start by more than `tolerance_sessions`) one genuine chance
    to prove the short cache was itself just an incomplete/stale fetch (the
    M01 hazard), not a reused symbol.

    Clears each candidate's sidecar (never its parquet) so `has_sufficient_
    price_cache` judges sufficiency from the ACTUAL cached data range - a
    wide `requested_end` alone was never enough to prove the START is
    covered - then calls `price_provider.get_prices` for exactly the
    candidates, through the provider's own normal write path (batching,
    negative-cache handling, everything unchanged).

    Returns `{ticker: "healed" | "still_late"}` for every candidate: healed
    if the re-fetched first bar now falls within tolerance of membership
    start (the cache genuinely grew); still_late if it does not (Yahoo
    itself has nothing earlier for the current holder of the symbol - a
    genuine reuse, left for a subsequent `scan_price_cache` call, given the
    same `membership_start_by_ticker_map`, to quarantine).

    NETWORK-TOUCHING via `price_provider` - a deliberate, explicit,
    one-time operational step (mirroring `data/corporate_actions.py`'s
    `refresh_actions_cache` - a real fetch, not a new caching mechanism),
    never called from `scan_price_cache` itself (which stays fully
    offline) or from any test without an explicit fake provider."""
    requested_start_ts = pd.Timestamp(requested_start)
    candidates: list[str] = []
    for ticker, membership_start in membership_start_by_ticker_map.items():
        cached = read_cache(price_cache_path(ticker, cache_dir))
        if cached is None or cached.empty:
            continue
        first_bar = pd.Timestamp(cached.index.min())
        if symbol_reuse_new_listing_reason(
            first_bar, membership_start, requested_start_ts, tolerance_sessions
        ):
            candidates.append(ticker)

    if not candidates:
        return {}

    for ticker in candidates:
        meta_path = price_meta_path(ticker, cache_dir)
        if meta_path.exists():
            meta_path.unlink()

    price_provider.get_prices(candidates, requested_start, requested_end)

    results: dict[str, str] = {}
    for ticker in candidates:
        cached = read_cache(price_cache_path(ticker, cache_dir))
        first_bar = (
            pd.Timestamp(cached.index.min()) if cached is not None and not cached.empty else None
        )
        membership_start = membership_start_by_ticker_map[ticker]
        still_flagged = first_bar is None or symbol_reuse_new_listing_reason(
            first_bar, membership_start, requested_start_ts, tolerance_sessions
        )
        results[ticker] = "still_late" if still_flagged else "healed"
    return results


@dataclass(frozen=True)
class QuarantineReport:
    """Result of one `scan_price_cache` run.

    `quarantined`: ticker -> the reason string(s) that triggered quarantine
    (the exact strings written to that ticker's sidecar).
    `scanned_count`: how many tickers had a price cache file to examine.
    `checked_at`: when this scan ran (also written into each quarantined
    ticker's own sidecar - see `data/cache.py`'s `write_quarantine_meta`).
    """

    quarantined: dict[str, list[str]] = field(default_factory=dict)
    scanned_count: int = 0
    checked_at: pd.Timestamp = field(default_factory=lambda: pd.Timestamp.now().normalize())


def scan_price_cache(
    cache_dir: Path,
    zero_volume_fraction_threshold: float = _DEFAULT_ZERO_VOLUME_FRACTION_THRESHOLD,
    zero_volume_hard_threshold: float = _DEFAULT_ZERO_VOLUME_HARD_THRESHOLD,
    level_implausible_ratio: float = _DEFAULT_LEVEL_IMPLAUSIBLE_RATIO,
    jump_ratio_threshold: float = _DEFAULT_JUMP_RATIO_THRESHOLD,
    jump_excuse_window_sessions: int = _DEFAULT_JUMP_EXCUSE_WINDOW_SESSIONS,
    min_unexplained_jumps: int = _DEFAULT_MIN_UNEXPLAINED_JUMPS,
    gap_sessions_threshold: int = _DEFAULT_GAP_SESSIONS_THRESHOLD,
    membership_start_by_ticker_map: dict[str, pd.Timestamp] | None = None,
    new_listing_tolerance_sessions: int = _DEFAULT_NEW_LISTING_TOLERANCE_SESSIONS,
) -> QuarantineReport:
    """Scan every ticker with a cached price file under `cache_dir` against
    the three checks above; any ticker failing ONE OR MORE is quarantined
    via `data/cache.py`'s `write_quarantine_meta` (merged into its existing
    sidecar, never overwriting its positive `requested_start`/
    `requested_end` metadata) and recorded in the returned report.

    Quarantine conditions (cycle 2, tightened - see this section's
    module-level comment for why): zero-volume fraction quarantines ALONE
    only above `zero_volume_hard_threshold` (default 0.5 - CCE/MHS-style
    genuinely dead series); between `zero_volume_fraction_threshold` (0.20)
    and the hard bar, it quarantines only WITH an implausible price level
    (`_level_implausible`) alongside it. Unexplained price jumps quarantine
    only at `min_unexplained_jumps` (default 3) or more - a single clean
    jump is a real corporate event as often as it is contamination, and the
    shared cache cannot tell those apart at n=1 (see `unexplained_jump_
    dates`'s docstring). Symbol-reuse-across-a-gap is UNCHANGED - it already
    requires both a genuine trading-day gap and a level shift, the strongest
    combination here.

    `membership_start_by_ticker_map` (optional, from `membership_start_by_
    ticker`): when supplied, ALSO checks `symbol_reuse_new_listing_reason`
    for each ticker - the membership-aware detector added after this
    milestone's cycle-2 review found that several of the price-arithmetic
    checks' "false positives" (EA, EQR, LEG, AVB) were not false at all: the
    cached history genuinely belongs to a DIFFERENT, newly-listed company
    reusing a delisted constituent's ticker symbol, which the price-shape
    checks above cannot see (a clean, healthy-looking series is exactly what
    a genuine new listing looks like) but a membership-start comparison
    catches directly. `None` (the default) skips this check entirely - every
    caller that has no `ConstituentsProvider` handy (most direct tests) is
    unaffected.

    Read-only with respect to any parquet: only sidecar JSON files are
    written (quarantine verdicts), never a price file itself - see
    CLAUDE.md's "regenerable cache" principle. Offline: reads only what is
    already on disk, never touches the network. No CLI caller yet - see
    module docstring's closing paragraph (M09 scope)."""
    prices_dir = Path(cache_dir) / "prices"
    tickers = sorted(p.stem for p in prices_dir.glob("*.parquet")) if prices_dir.is_dir() else []

    quarantined: dict[str, list[str]] = {}
    for ticker in tickers:
        panel = read_cache(price_cache_path(ticker, cache_dir))
        if panel is None or panel.empty:
            continue
        if set(_RAW_COLUMN_MAP) <= set(panel.columns):
            panel = panel.rename(columns=_RAW_COLUMN_MAP)

        reasons: list[str] = []

        zvf = zero_volume_fraction(panel)
        if zvf > zero_volume_hard_threshold:
            reasons.append(f"zero_volume_fraction:{zvf:.1%} (over real trading bars)")
        elif zvf > zero_volume_fraction_threshold and _level_implausible(
            panel["close"], level_implausible_ratio
        ):
            reasons.append(
                f"zero_volume_fraction:{zvf:.1%} (over real trading bars) "
                "with an implausible price-level shift"
            )

        actions = read_cached_actions(ticker, cache_dir)
        jump_dates = unexplained_jump_dates(
            panel, actions, jump_ratio_threshold, jump_excuse_window_sessions
        )
        if len(jump_dates) >= min_unexplained_jumps:
            reasons.append(
                f"unexplained_price_jump:{len(jump_dates)} date(s), first {jump_dates[0].date()}"
            )

        reasons.extend(
            symbol_reuse_gap_reasons(panel, jump_ratio_threshold, gap_sessions_threshold)
        )

        if membership_start_by_ticker_map is not None:
            sidecar_meta = read_json_meta(price_meta_path(ticker, cache_dir))
            requested_start = (
                pd.Timestamp(sidecar_meta["requested_start"])
                if sidecar_meta is not None and "requested_start" in sidecar_meta
                else None
            )
            reuse_reason = symbol_reuse_new_listing_reason(
                pd.Timestamp(panel.index.min()),
                membership_start_by_ticker_map.get(ticker),
                requested_start,
                new_listing_tolerance_sessions,
            )
            if reuse_reason is not None:
                reasons.append(reuse_reason)

        if reasons:
            quarantined[ticker] = reasons
            write_quarantine_meta(ticker, reasons, cache_dir)

    return QuarantineReport(
        quarantined=quarantined,
        scanned_count=len(tickers),
        checked_at=pd.Timestamp.now().normalize(),
    )
