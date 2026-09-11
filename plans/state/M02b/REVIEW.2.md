REVIEW: APPROVE

# M02b review, iteration 2 — re-review after quant-gate REJECT

Scope per plans/state/M02b/VERDICT.md: findings 1-5 only. Design (formula,
ex-date gate, defense-in-depth re-gate, composition order, staleness
policy) was accepted at cycle 1 and not reopened here.

## Verification performed (independent)
- `uv run pytest tests/ -q` → 163 passed, 3 deselected in ~2.2-3.0s (stable
  across repeated runs).
- `uv run ruff check` → All checks passed.
- `uv run ruff format --check` → 37 files already formatted.
- Mutation test: weakened the new pre-window action drop in
  `apply_asof_adjustment` (`ticker_actions = ticker_actions.loc[...]` →
  no-op). Both new regression tests
  (`test_apply_asof_adjustment_ignores_dividends_predating_the_panel_without_raising`
  and `test_prices_does_not_raise_for_dividend_payer_with_history_predating_lookback_window`)
  fail with the pre-existing `DataQualityError` ("no raw close available
  strictly before ex-date ... to compute close_prev_ex"), confirming the
  drop is load-bearing. Reverted; `git diff --stat
  src/quantlab/data/adjustment.py` matches the pre-mutation content
  (verified by re-reading the file); full suite green again (163 passed).

## Findings 1-5, verified individually

1. **Fixed, output-preserving.** `apply_asof_adjustment` now drops any
   action with ex-date `<=` the ticker's first panel date before calling
   `adjustment_factors` (`adjustment.py:302-305`). Traced the logic: an
   action at or before the panel's first row can never satisfy "price
   date strictly before ex-date" for any row in the panel, so dropping it
   changes no output — confirmed by
   `test_apply_asof_adjustment_ignores_dividends_predating_the_panel_without_raising`
   (three ancient dividends, flat close series, asserts unchanged).
   `test_prices_does_not_raise_for_dividend_payer_with_history_predating_lookback_window`
   is the required end-to-end regression: KO-style quarterly dividends
   from 2015 through a 60-session lookback with `asof=2024-12-10`, run
   through `PITDataContext.prices()` — no longer raises, and the one
   genuinely in-window dividend (factor `1 - 1/100 = 0.99`) still applies
   correctly to rows before it and not after. `adjustment_factors` itself
   is untouched and stays strict (confirmed by reading it), as the gate
   required.
2. **Fixed.** The download-failure branch in
   `corporate_actions.py:189-215` now raises `ActionsFetchError` (new
   `DataQualityError` subclass) naming the ticker and the underlying
   exception via `raise ... from exc`, instead of returning
   `_empty_actions()`; nothing is written to the cache (confirmed:
   `test_get_actions_download_failure_raises_is_not_cached_and_is_retried`
   asserts the cache file doesn't exist after the raise, and that a
   second call retries and succeeds). The mandatory end-to-end test,
   `test_prices_propagates_actions_provider_errors_end_to_end`,
   parametrizes over both `StaleActionsCacheError` and `ActionsFetchError`
   from a fake provider and asserts `PITDataContext.prices()` raises
   uncaught — I independently confirmed by inspection that `pit.py` has
   no `try`/`except` around either `get_actions` call site, so this holds
   in production code, not just in the test double.
3. **Fixed, preferred remedy (adjust OHL, not just document).**
   `apply_asof_adjustment` now applies the identical per-date factor
   array to every column in `_ADJUSTABLE_PRICE_COLUMNS = ("open", "high",
   "low", "close")` present in the panel (`adjustment.py:280-281,
   326-327`); `volume` is excluded by construction (not in that tuple).
   Hand-verified: NVDA row open=1200/10=120.0, high=1215/10=121.5,
   low=1195/10=119.5, close=1210/10=121.0 — `low <= close <= high` holds
   (119.5 <= 121.0 <= 121.5), matching
   `test_apply_asof_adjustment_applies_same_factor_to_open_high_low_as_close`,
   which asserts this explicitly and also asserts volume is unchanged.
   `pit.py` and `adjustment.py` docstrings both now state volume is
   unadjusted and warn against combining it with adjusted price columns.
4. **Fixed, at both the individual and composed level.** `_event_factor`
   (`adjustment.py:140-148`) raises `DataQualityError` naming
   ticker/ex-date/amount/close_prev_ex when a dividend's own factor
   `<= 0`; `adjustment_factors` (`adjustment.py:216-230`) adds a
   defense-in-depth check on the fully composed cumulative factor too.
   Verified both the oversized-dividend case (45.0 against
   close_prev_ex=40.0 → factor -0.125) and the exact-zero boundary (40.0
   against 40.0 → factor 0.0) raise `DataQualityError` via
   `test_dividend_exceeding_close_prev_ex_raises_data_quality_error` and
   `test_dividend_equal_to_close_prev_ex_raises_data_quality_error`.
5. **All four reviewer minors folded in and verified:**
   (i) `TOL` in `tests/test_adjustment.py` is `1e-12` (confirmed by
   reading the file); full suite still passes at this tolerance.
   (ii) `adjustment.py`'s module docstring now states the canary
   (f)-vs-parity-test mutation asymmetry explicitly, citing
   `plans/state/M02b/REVIEW.md`'s mutation test B.
   (iii) `CorporateActionsProvider` (`interfaces.py:82-95`) now carries a
   non-abstract "Staleness contract" docstring section naming
   `YFinanceCorporateActionsProvider`'s mechanism as the pattern a future
   implementer must follow — enforcement correctly stays out of the ABC
   itself, per the gate's own reasoning.
   (iv) covered by finding 2's mandatory end-to-end test.

## No new issues found

No blockers. The fixes are scoped exactly to findings 1-5 as instructed —
`git diff` shows no changes to the formula, the ex-date gate, the
defense-in-depth re-gate, the same-day composition logic, or the staleness
policy's semantics. `src/quantlab/data/cache.py` is untouched in this
iteration (already reviewed at cycle 1). `plans/QUANT-NOTES.md`'s new
carried notes for M03/M04/M09 accurately reflect this cycle's fixes and
the gate's "not blocking, carried" item (`refresh_actions_cache()` has no
operational caller) — documentation only, no code implication.

`plans/state/M02/VERDICT.md` carried item 1 can close on this cycle.
