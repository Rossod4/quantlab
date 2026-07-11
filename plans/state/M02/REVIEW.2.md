VERDICT: APPROVE

# M02 code review (iteration 2 — re-review of the REVIEW.md revision)

## Verification performed
- `python -m uv run pytest tests/ -rA` → 141 passed, 3 deselected (network). Matches HANDOFF.2.
- `python -m uv run ruff check` → clean; `ruff format --check` → 35 files already formatted.
- Ported numerical logic untouched this iteration: byte-identical diff of
  providers/edgar_fundamentals.py against my iteration-1 snapshot (the module whose
  parity I independently reproduced against the old repo in REVIEW.md). survivorship.py
  also unchanged. The iteration-1 parity result therefore stands.
- Canary (c) guard-coupling verified by mutation: temporarily weakening the PRODUCTION
  as-of lookup (`_membership_from_table`, sp500_constituents.py — replaced
  `table.index.asof(date)` with `table.index.max()`) made
  test_canary_universe_between_membership_rows_returns_earlier_row_only fail. Mutation
  reverted; full suite re-verified green (141 passed).

## Finding-by-finding closure
1. **(blocker) failed download frozen into actions cache — FIXED.**
   corporate_actions.py:106-126: on download failure, `_empty_actions()` is returned
   WITHOUT `write_cache`, so the next call re-attempts (matches the edgar port
   precedent). The bare `except Exception` is narrowed to
   `(requests.RequestException, OSError)`; anything else propagates.
   `test_get_actions_download_failure_is_not_cached_and_is_retried` asserts the exact
   contract (fail → empty result, NO cache file; second call re-fetches, succeeds,
   caches) and `test_get_actions_unexpected_exception_propagates` asserts a TypeError
   surfaces loudly. Both pass. Note: `ConnectionError` used in the test is an OSError
   subclass, so the narrowed clause genuinely covers it. Closed.
2. **(minor) canary (c) not coupled to production guard — FIXED.**
   tests/canaries/test_lookahead.py:53-74: `_TwoRowConstituentsProvider.membership()`
   now delegates to `sp500_constituents._membership_from_table`. Verified by mutation
   (see above) — the canary now fails if the production as-of guard is weakened. Closed.
3. **(minor) spurious DelistingEvent for never-member tickers — FIXED** (tightening
   taken). corporate_actions.py:167-174: inference now requires membership as of
   `last_trade_date` AND non-membership as of `end`; ValueError from either lookup →
   None. New tests cover never-member and membership-data-starts-too-late; the
   acceptance-criterion-5 scenario still asserts the exact packet numbers
   (last bar 2020-06-12 → DelistingEvent at 2020-06-12, reason UNKNOWN). Closed.
4. **(minor) non-session rows pass the `<= asof` slice — FIXED.**
   pit.py:169-183: hard slice is now `<= last_session` and the keep-filter is
   `sliced.index.isin(sessions)` (the last N calendar sessions ending at
   `last_session`), so a non-session row can neither appear nor consume a lookback
   slot. Regression test (Saturday row, Sunday asof) asserts the returned index is
   exactly the three real sessions. The handoff correctly discloses the slight
   semantic strengthening (sparse tickers no longer back-fill slots from dates older
   than the N-session calendar window) — that reading matches criterion 6's wording
   and is the safer of the two interpretations. Closed.
5. **(recommendation) `needs_actions` gate — DONE.** requirements.py:43 adds
   `needs_actions: bool = False`; pit.py:223-226 gates `actions()` with
   UndeclaredDataError; positive and negative tests added. Every PITDataContext
   accessor is now declaration-gated before M03 freezes the surface. Closed.

## Residual notes (non-blocking, for the quant gate / M03 packet author)
- The central raw-vs-`prices_for_returns()` design decision is unchanged from
  iteration 1 and remains the quant gate's ACCEPT/REJECT; mechanically it is sound
  and canary (e) enforces it adversarially.
- Iteration-1 open question 1 stands as answered in REVIEW.md: as-of adjustment
  replay should arrive as its own parity-fixtured packet, with an explicit decision
  on `prices()` semantics before M03 freezes the Strategy ABC.
- yfinance-specific exception types that derive from neither requests.RequestException
  nor OSError will propagate rather than be swallowed — that is the documented,
  intended "fail loudly" behavior, worth remembering if a noisy vendor error shows up
  during a long M04 data pull.

All packet acceptance criteria remain met (criteria 1-6 re-verified this iteration
via the passing suite, including the criterion-5 test updated for the tightened
delisting rule). No new findings.
