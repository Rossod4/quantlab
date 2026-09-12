from __future__ import annotations

import pandas as pd

from quantlab.core.calendar import (
    calendar_first_session,
    is_trading_day,
    next_trading_day,
    prev_trading_day,
    rebalance_dates,
    trading_days,
)

# -- pinned calendar bounds (M04b work packet item 1) ------------------------


def test_trading_days_far_in_the_past_works_under_the_pinned_calendar() -> None:
    """Before pinning, `xcals.get_calendar("XNYS")` defaulted to a MOVING
    twenty-year window ending "today" - `trading_days("2000-01-03",
    "2000-01-10")` would raise `DateOutOfBounds` once wall-clock time moved
    far enough past 2000 (exactly the failure mode this milestone closes)."""
    days = trading_days("2000-01-03", "2000-01-10")
    assert len(days) == 6  # Mon 1/3 .. Fri 1/7, then Mon 1/10 (weekend skipped)
    assert days[0] == pd.Timestamp("2000-01-03")
    assert days[-1] == pd.Timestamp("2000-01-10")


def test_calendar_first_session_is_fixed_and_independent_of_today() -> None:
    """The calendar's `first_session` must be a genuine CONSTANT (see
    core/calendar.py's module docstring), not a function of wall-clock time -
    compared against the literal pinned bound, no monkeypatching of "today"
    involved (there would be nothing to monkeypatch: nothing here reads the
    clock at all)."""
    assert calendar_first_session() == pd.Timestamp("1990-01-02")


def test_thanksgiving_2020_is_not_a_trading_day() -> None:
    assert is_trading_day("2020-11-26") is False


def test_day_after_thanksgiving_2020_is_a_trading_day() -> None:
    assert is_trading_day("2020-11-27") is True


def test_trading_days_2024_count() -> None:
    days = trading_days("2024-01-01", "2024-12-31")
    assert len(days) == 252
    assert isinstance(days, pd.DatetimeIndex)
    assert days.tz is None
    assert (days == days.normalize()).all()


def test_month_end_rebalance_dates_2023() -> None:
    dates = rebalance_dates("2023-01-01", "2023-12-31", "month_end")
    assert len(dates) == 12
    assert pd.Timestamp("2023-06-30") in dates
    assert pd.Timestamp("2023-12-29") in dates


def test_weekly_rebalance_dates_2023_count() -> None:
    dates = rebalance_dates("2023-01-01", "2023-12-31", "weekly")
    assert len(dates) == 52


def test_daily_rebalance_dates_equal_trading_days() -> None:
    daily = rebalance_dates("2023-01-01", "2023-01-31", "daily")
    days = trading_days("2023-01-01", "2023-01-31")
    assert list(daily) == list(days)


def test_next_trading_day_normalizes_time_component() -> None:
    result = next_trading_day(pd.Timestamp("2024-07-05 18:00"))
    assert result == pd.Timestamp("2024-07-08")


def test_prev_trading_day_normalizes_time_component() -> None:
    result = prev_trading_day(pd.Timestamp("2024-07-08 03:00"))
    assert result == pd.Timestamp("2024-07-05")


def test_next_trading_day_accepts_holiday_input() -> None:
    # Thanksgiving 2020 is not a session; must not raise (regression: REVIEW #1).
    assert next_trading_day("2020-11-26") == pd.Timestamp("2020-11-27")


def test_next_trading_day_accepts_weekend_input() -> None:
    # Saturday after July 4th weekend 2024.
    assert next_trading_day("2024-07-06") == pd.Timestamp("2024-07-08")


def test_prev_trading_day_accepts_holiday_input() -> None:
    assert prev_trading_day("2020-11-26") == pd.Timestamp("2020-11-25")


def test_prev_trading_day_accepts_weekend_input() -> None:
    assert prev_trading_day("2024-07-06") == pd.Timestamp("2024-07-05")


def test_next_prev_remain_strict_for_session_inputs() -> None:
    # For inputs that ARE sessions, next/prev must be strictly after/before.
    assert next_trading_day("2024-07-05") == pd.Timestamp("2024-07-08")
    assert prev_trading_day("2024-07-08") == pd.Timestamp("2024-07-05")
