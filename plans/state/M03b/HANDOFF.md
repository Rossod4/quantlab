# M03b HANDOFF — per-share share-terms restatement + canonical blend id

## Files changed
- `src/quantlab/data/providers/edgar_fundamentals.py`: added
  `shares_outstanding_filed`/`ttm_eps_filed` to `PointInTimeFundamentals`
  (and `_EMPTY_FUNDAMENTALS`), via two new helpers
  (`_most_recent_instant_with_filed`, `_ttm_duration_with_latest_filed`)
  that mirror the frozen helpers step for step — same value, plus a filed
  date. Frozen helpers/`get_point_in_time_fundamentals`'s existing call
  sites for shares/ttm_eps swapped to the new helpers; no other field
  touched.
- `src/quantlab/data/pit.py`: `fundamentals()` restates `shares_outstanding`
  (`*= factor`) and `ttm_eps` (`/= factor`) using `_split_factor_since_filed`
  — Π split ratios with `filed < ex_date <= asof`, fed by
  `_gated_actions_by_ticker` (never a raw provider call). Adds
  `share_terms_split_factor`/`share_terms_asof` when either field is
  declared. Window uses `asof`, not the lagged `effective_asof`.
- `src/quantlab/strategies/value.py`: docstring only — notes fundamentals
  are now pre-restated; no numerical/declared-field change.
- `src/quantlab/strategies/blend.py`: `BlendStrategy.strategy_id` overridden
  to hash a sorted `(child.strategy_id, weight)` list plus non-`children`
  own params, instead of raw child config dicts.
- Tests: new `tests/test_share_terms.py` (gate fixture + no-split/before-
  filing/composing-splits/after-asof cases + declaration gating); new
  canary (h) in `tests/canaries/test_lookahead.py`; end-to-end split-rank
  test added to `tests/test_value_strategy.py`; 3 canonicalization tests
  added to `tests/test_blend.py` (order swap, omitted default, child-param
  change — required adding a default `multiplier` param to the test-only
  echo strategy). One pre-existing test,
  `tests/test_pit.py::test_fundamentals_returns_only_declared_fields`,
  updated: declaring `ttm_eps` now also yields the two provenance keys —
  this is the packet's intended additive contract change, not a regression.

## ASC 260 argument (packet requirement)
A filer retroactively restates EPS and share counts for any split that
occurs before the financial statements are issued, so a split between
period-end and the filing date is already reflected in the filed figure.
Only a split strictly *after* the filing date leaves the filed figure in
stale, pre-split share terms — hence the window is `(filed, asof]`, not
`(period_end, asof]`.

## Design decisions / deviations
- `share_terms_split_factor` is a single scalar even though each field is
  restated with its *own* filed date (shares_outstanding and ttm_eps can
  legitimately have different filed dates). Both fields are always
  restated correctly regardless; the one summary key prefers
  `shares_outstanding`'s factor when both were restated, else whichever
  was. Documented in `fundamentals()`'s docstring. In practice both facts
  normally come from the same filing, so this rarely matters.
- New EDGAR helpers duplicate (rather than refactor) the frozen
  selection logic to guarantee byte-identical values without touching
  anything covered by existing parity tests I was not permitted to read.

## Test commands + output
- `uv run pytest tests/ -q`: exit 0, 224 dots (up from M03's 213 — 11 new
  tests), no red.
- `uv run ruff check .`: all checks passed. `uv run ruff format --check .`:
  52 files already formatted.

## Mutation-check (canary h)
Temporarily widened `_gated_actions_by_ticker`'s hard-slice bound from
`raw.index <= self._asof` to `<= self._asof + 1 day`, re-ran
`tests/canaries/test_lookahead.py` + `tests/test_share_terms.py`: canary
(h) and `test_split_after_asof_has_zero_effect` both failed — the widened
window let the future split leak through and `_assert_no_future_dates`
raised `LookaheadError` (defense-in-depth catching it loudly rather than
silently). Reverted the one-line mutation; full suite re-confirmed green
(exit 0, 224 dots) and ruff clean.

## Open questions
None blocking. `share_terms_split_factor`'s single-scalar-for-two-fields
convention above is the one judgment call worth the gate's attention.
