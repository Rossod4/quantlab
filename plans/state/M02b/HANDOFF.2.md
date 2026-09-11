# M02b HANDOFF.2 — re-review fixes (cycle 1 VERDICT: REJECT)

Addresses every numbered finding in plans/state/M02b/VERDICT.md; REVIEW.md's
four minors folded in per the gate's instruction. Design (formula, ex-date
gate, defense-in-depth re-gate, composition order, staleness policy)
unchanged, per the gate's re-review scope.

## Findings — status
1. FIXED. `apply_asof_adjustment` drops actions at/before a ticker's first
   panel date before computing factors — output-preserving no-op (see
   adjustment.py's new "Truncated panels" docstring section). Added a
   direct unit test and an end-to-end `prices()` regression with a
   multi-year quarterly-dividend history against a 60-session lookback.
2. FIXED. The fetch-failure branch in `corporate_actions.py` now raises a
   new `ActionsFetchError(DataQualityError)` naming the ticker and
   underlying exception, instead of returning empty; nothing is cached.
   Added an end-to-end test asserting `prices()` propagates both
   `ActionsFetchError` and `StaleActionsCacheError` uncaught (also 5(iv)).
3. FIXED, preferred remedy taken. `apply_asof_adjustment` applies the
   identical per-date factor to open/high/low as close; volume stays
   unadjusted (documented in `adjustment.py` and `pit.py`). Added a test
   pinning `low <= close <= high` across a split.
4. FIXED. `_event_factor` raises `DataQualityError` (names ticker/ex-date/
   amount/close_prev_ex) when a dividend factor is `<= 0`;
   `adjustment_factors` adds a defense-in-depth check on the composed
   factor too. Added fixtures for the oversized-dividend and exact-zero
   boundary cases.
5. Reviewer minors, folded in: (i) `TOL` tightened 1e-9→1e-12, all tests
   still pass. (ii) one-line note added on the canary(f)-vs-parity-test
   mutation asymmetry. (iii) staleness contract note added to
   `CorporateActionsProvider` (non-abstract, per the gate's own reasoning
   for keeping enforcement off the ABC). (iv) now mandatory, see finding 2.

## Files changed
- `src/quantlab/data/adjustment.py` — findings 1/3/4 + docstring rewrite.
- `src/quantlab/data/corporate_actions.py` — finding 2 + docstring note.
- `src/quantlab/data/interfaces.py` — finding 5(iii).
- `src/quantlab/data/pit.py` — docstrings updated for OHL adjustment,
  staleness propagation, and the "close is a level, not a traded price"
  caveat the gate asked for.
- `src/quantlab/core/errors.py` — new `ActionsFetchError(DataQualityError)`.
- `tests/test_adjustment.py` — `TOL` to 1e-12; new tests for findings 1-4.
- `tests/test_corporate_actions.py` — *intentional test change*:
  `test_get_actions_download_failure_is_not_cached_and_is_retried` renamed
  to `..._raises_is_not_cached_and_is_retried` and now asserts
  `ActionsFetchError` is raised on the failing call instead of asserting
  an empty return — required by finding 2's behavior change.

## Deviations
None from the re-review scope. Formula, gate, enforcement point and
staleness policy were not reopened.

## Verification
- `uv run pytest tests/ -q` → **163 passed, 3 deselected in 2.44s**
- `uv run ruff check` → **All checks passed**
- `uv run ruff format --check` → all files formatted

## Not addressed here (explicitly out of re-review scope)
`refresh_actions_cache()` has no operational caller (VERDICT.md "Not
blocking, carried") — recorded in QUANT-NOTES.md for M09.
