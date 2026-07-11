# M02 handoff (iteration 2 — revision per REVIEW.md)
## Findings addressed

**1 (blocker) — failed download frozen into actions cache: FIXED.**
`src/quantlab/data/corporate_actions.py` `get_actions()`: on download failure it now
returns `_empty_actions()` WITHOUT writing the cache, so the next call re-attempts the
fetch (matching the port precedent: `edgar_fundamentals.get_company_facts` returns None
uncached on RequestException). The bare `except Exception` is narrowed to
`(requests.RequestException, OSError)` — RequestException covers yfinance's
requests-based transport, OSError covers raw socket/curl-level errors (and builtin
ConnectionError). Anything else (e.g. a yfinance API/parsing change) now propagates
loudly. New tests: `test_get_actions_download_failure_is_not_cached_and_is_retried`
(fail once → empty result, NO cache file; second call re-fetches, succeeds, caches) and
`test_get_actions_unexpected_exception_propagates` (TypeError raises through).

**2 (minor) — canary (c) not coupled to the production guard: FIXED.**
`tests/canaries/test_lookahead.py` `_TwoRowConstituentsProvider.membership()` now
delegates to the production `sp500_constituents._membership_from_table` (exact code the
real provider runs) instead of a test-local reimplementation — deleting/weakening the
production as-of lookup now fails the canary. Tickers are dot-free so the production
`normalize_ticker` pass is a no-op, as the review anticipated.

**3 (minor) — spurious DelistingEvent for never-member tickers: FIXED** (took the
tightening, not the justify-option). `infer_delisting()` now requires membership as of
`last_trade_date` AND non-membership as of `end` — "left the set" literally. ValueError
from either lookup (membership data doesn't reach back far enough) → None. New tests:
`test_infer_delisting_none_when_ticker_was_never_a_member`,
`test_infer_delisting_none_when_membership_data_starts_too_late`. The fake constituents
provider was upgraded to a real point-in-time (date-keyed) fake since two dates are now
consulted; the acceptance-criterion-5 test still asserts the exact packet scenario
(last bar 2020-06-12, left the index, request through 2020-12-31 → event at 06-12).

**4 (minor) — non-session rows pass the `<= asof` slice: FIXED.** `pit.py`
`_sliced_price_panel` now slices to `<= last_session` (not calendar `asof`) and the
final keep-filter intersects with the `sessions` calendar index (the last N sessions
ending at `last_session`), so a non-session row can neither appear in the result nor
consume a lookback slot. Note this also slightly strengthens semantics: returned rows
are now always within the last-N-sessions calendar window (a sparse ticker no longer
back-fills its N slots from older dates) — matches criterion 6's wording "at most N
sessions ending at the last session <= asof". New regression test:
`test_prices_excludes_non_session_rows_and_they_do_not_consume_lookback_slots`
(Saturday row between last session and a Sunday asof).

**Reviewer recommendation (open question 2) — `needs_actions`: DONE.** Added
`needs_actions: bool = False` to `DataRequirements`; `PITDataContext.actions()` raises
`UndeclaredDataError` when False — every accessor now declaration-gated before M03
freezes the surface. Tests updated (existing actions test declares it) and added
(`test_actions_undeclared_raises_undeclared_data_error`).

## Files changed this iteration
`src/quantlab/data/{corporate_actions,pit,requirements}.py`; `tests/{test_corporate_
actions,test_pit,canaries/test_lookahead}.py`. No ported numerical logic touched.

## Verification
`uv run pytest tests/` → 141 passed, 3 deselected (network); ruff check/format clean.

## Open questions
None new; iteration-1 question 1 (as-of adjustment replay as its own parity-tested
packet, before M03 freezes `prices()` semantics) stands per REVIEW.md's answer.
