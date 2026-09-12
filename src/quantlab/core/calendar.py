"""Thin wrapper over `exchange_calendars` XNYS.

All public functions accept anything `pd.Timestamp` can parse and normalize
it to a timezone-naive, midnight-aligned timestamp before querying the
underlying calendar.

## Pinned calendar bounds (M04b work packet item 1)

`xcals.get_calendar("XNYS")` with no explicit `start`/`end` defaults to a
MOVING twenty-year window ending "today" (wall-clock time when the process
started) - i.e. `first_session` silently changes, day by day, as real time
passes. This is wrong for a reproducibility-first research platform in two
ways: (a) the SAME backtest config (e.g. a fixed 2012-2026 date range) can
raise `exchange_calendars.errors.DateOutOfBounds` on one machine/day and not
another, purely because the calendar's own floor drifted past a date the
config never changed; (b) it silently changes what "the earliest date this
platform can compute a trading day for" MEANS between two runs months apart,
which is exactly the kind of non-determinism CLAUDE.md invariant #5 rules
out. Measured in production: a 2012-2026 momentum backtest's benchmark
computation requested a window reaching back to ~2006 (see
`backtest/engine.py`'s module docstring / plans/M04b-engine-perf.md), which
raised `DateOutOfBounds` against the moving calendar's own `first_session`
that day - not because the request was unreasonable, but because "reasonable"
itself was a moving target.

The bounds below are pinned to fixed, explicit dates instead: 1990-01-01
comfortably predates any data this platform's providers can serve (yfinance/
SEC EDGAR have nothing usable before then for this platform's universe) and
2040-12-31 is a generous, arbitrary future bound (this is a research
platform, not a live trading system with same-day settlement needs beyond
that date). Pinning both bounds means `first_session`/`last_session` are
now genuinely CONSTANTS - the same today as in ten years - and any
"reaches before 1990" request is a real, catchable modeling bug (a lookback
that's too generous for the data available), not calendar drift.
"""

from __future__ import annotations

from typing import Literal

import exchange_calendars as xcals
import pandas as pd

from quantlab.core.types import normalize_timestamp

_CALENDAR_NAME = "XNYS"
# See module docstring's "Pinned calendar bounds" section - fixed, not the
# default moving twenty-year window.
_CALENDAR_START = "1990-01-01"
_CALENDAR_END = "2040-12-31"
_calendar = xcals.get_calendar(_CALENDAR_NAME, start=_CALENDAR_START, end=_CALENDAR_END)

RebalanceFreq = Literal["daily", "weekly", "month_end"]


def calendar_first_session() -> pd.Timestamp:
    """The calendar's pinned earliest session (see module docstring) - a
    fixed constant, not a function of wall-clock time. Used by
    `data/pit.py`'s window clamp and `backtest/panel_store.py`'s run-level
    warmup-window sizing to guarantee neither ever requests a date the
    calendar itself considers out of bounds."""
    return pd.Timestamp(_calendar.first_session)


def trading_days(start: object, end: object) -> pd.DatetimeIndex:
    """Trading days in [start, end], inclusive, tz-naive and midnight-normalized."""
    sessions = _calendar.sessions_in_range(normalize_timestamp(start), normalize_timestamp(end))
    return pd.DatetimeIndex(sessions)


def is_trading_day(date: object) -> bool:
    return bool(_calendar.is_session(normalize_timestamp(date)))


def next_trading_day(date: object) -> pd.Timestamp:
    """Strictly the next trading day after `date` (normalized).

    Accepts any date: if `date` is a session, returns the session after it;
    if it is a weekend/holiday, returns the first session after it.
    """
    ts = normalize_timestamp(date)
    if _calendar.is_session(ts):
        return pd.Timestamp(_calendar.next_session(ts))
    return pd.Timestamp(_calendar.date_to_session(ts, direction="next"))


def prev_trading_day(date: object) -> pd.Timestamp:
    """Strictly the previous trading day before `date` (normalized).

    Accepts any date: if `date` is a session, returns the session before it;
    if it is a weekend/holiday, returns the first session before it.
    """
    ts = normalize_timestamp(date)
    if _calendar.is_session(ts):
        return pd.Timestamp(_calendar.previous_session(ts))
    return pd.Timestamp(_calendar.date_to_session(ts, direction="previous"))


def rebalance_dates(start: object, end: object, freq: RebalanceFreq) -> pd.DatetimeIndex:
    """Rebalance dates in [start, end].

    - "daily": every trading day.
    - "weekly": the last trading day of each ISO week.
    - "month_end": the last trading day of each calendar month.
    """
    days = trading_days(start, end)
    if freq == "daily" or len(days) == 0:
        return days

    if freq == "weekly":
        iso = days.isocalendar()
        keys = list(zip(iso["year"], iso["week"], strict=True))
    elif freq == "month_end":
        keys = list(zip(days.year, days.month, strict=True))
    else:
        raise ValueError(f"unknown freq: {freq!r}")

    last_idx = len(days) - 1
    selected = [days[i] for i in range(len(days)) if i == last_idx or keys[i] != keys[i + 1]]
    return pd.DatetimeIndex(selected)
