# M00 — Core scaffold: REVIEW (iteration 1)

VERDICT: REVISE

## Verification run (reviewer-executed)
- `python -m uv run pytest tests/ -q` → 26 passed, 0 skipped/error. Matches handoff.
- `python -m uv run ruff check` → All checks passed! (harmless warning that `PD901` is a
  removed rule — pre-existing in `pyproject.toml`, out of packet scope, not attributable
  to this change).
- `python -m uv run ruff format --check` → 11 files already formatted.
- `python -m uv run quantlab --help` → exit 0; lists `data backtest validate report paper`
  + `--version`.
- Acceptance criteria 2–5 spot-checked directly against the packet's numbers (Thanksgiving
  2020 non-session / day-after session, 252 trading days in 2024, 12 month-end dates for
  2023 incl. 2023-06-30/2023-12-29, 52 weekly dates, `TargetWeights` NaN/Inf rejection,
  immutability, config round-trip + bogus-key `ConfigError`) — all confirmed via the test
  suite, which asserts real values, not just "runs without error."

## Findings

1. **[blocker]** `src/quantlab/core/calendar.py:38-45` — `next_trading_day` and
   `prev_trading_day` raise an unhandled `exchange_calendars.errors.NotSessionError`
   whenever the (normalized) input date is not itself a trading session — i.e. any
   weekend or holiday. Reproduced directly:
   ```
   >>> from quantlab.core.calendar import next_trading_day
   >>> next_trading_day("2020-11-26")   # Thanksgiving 2020 — the exact date this
   ...                                   # same milestone's test_calendar.py asserts
   ...                                   # is_trading_day() == False for
   NotSessionError: ... Timestamp('2020-11-26 00:00:00') ...
   ```
   This contradicts the module's own docstring ("All public functions accept anything
   `pd.Timestamp` can parse... before querying the underlying calendar") and the
   asymmetry with `trading_days()`/`is_trading_day()`, which handle arbitrary dates
   fine. The packet's only acceptance-criterion test for these two functions happens to
   use inputs that are themselves trading days (Fri 2024-07-05, Mon 2024-07-08), so the
   bug doesn't trip the packet's test, but it is a foundational "every later milestone
   builds on this" module — "next/prev trading day after an arbitrary date" (holiday
   shifting, delisting-date alignment, corporate-action dates) is an expected call
   pattern and will crash.
   Concrete fix: `exchange_calendars` exposes `date_to_session(date, direction=...)`,
   which resolves non-session dates to the nearest matching session instead of raising
   (verified: `cal.date_to_session(pd.Timestamp("2024-07-06"), direction="next")` →
   `2024-07-08`). Note it is *not* a drop-in replacement for `next_session`/
   `previous_session` on dates that already are sessions — `date_to_session(fri,
   direction="next")` returns `fri` itself (inclusive), whereas the packet's spec and
   existing test require *strictly* next/previous. The fix needs to special-case:
   if `_normalize(date)` is itself a session, keep using `next_session`/
   `previous_session` (strict); otherwise fall back to `date_to_session(..., direction=
   "next"/"previous")`. Add a regression test exercising a weekend/holiday input (e.g.
   `next_trading_day("2020-11-26") == pd.Timestamp("2020-11-27")`) so this doesn't
   regress silently.

## Minor (non-blocking)

2. `src/quantlab/core/types.py:10-15` (`_normalize_timestamp`) and
   `src/quantlab/core/calendar.py:21-25` (`_normalize`) are identical logic duplicated
   across two modules. Worth collapsing into one shared helper when finding 1 is fixed
   (same function needs touching anyway), but not required to unblock this milestone.

## Not reviewed (out of scope per packet / role)
- Quant methodology — deferred to quant-gate.
- `pyproject.toml` — untouched by the developer, consistent with the packet's
  restriction.

## Summary
Types, config loader, CLI stub, and the bulk of the calendar wrapper are solid: tests
assert concrete values (not just "runs"), are offline/deterministic, immutability and
NaN/Inf validation are correctly enforced, config error messages name the offending key
including nested keys, and conventions (typed, pydantic v2, no hardcoded paths, `from
__future__ import annotations`) are followed throughout. The one blocker is narrow and
localized to `next_trading_day`/`prev_trading_day` in `core/calendar.py` — fix those two
functions (plus a regression test for the non-session-input case) and this should
approve.
