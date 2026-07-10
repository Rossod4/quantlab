"""Thin wrapper over `exchange_calendars` XNYS.

All public functions accept anything `pd.Timestamp` can parse and normalize
it to a timezone-naive, midnight-aligned timestamp before querying the
underlying calendar.
"""

from __future__ import annotations

from typing import Literal

import exchange_calendars as xcals
import pandas as pd

from quantlab.core.types import normalize_timestamp

_CALENDAR_NAME = "XNYS"
_calendar = xcals.get_calendar(_CALENDAR_NAME)

RebalanceFreq = Literal["daily", "weekly", "month_end"]


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
