# M04 HANDOFF.2 — review iteration 2 (REVISE -> addressed)

**Files changed:** `src/quantlab/backtest/engine.py` (guard rewrite + docstrings),
`src/quantlab/data/pit.py` (actions memoisation); tests: `test_engine.py`,
`test_blend.py`, `test_pit.py`, `test_survivorship.py`, `parity/test_engine_parity.py`.

## Blockers
1. **Extreme-return guard — fixed, not escalated.** Replaced cap-at-0%-keep-weight with
   `_weighted_return_excluding`: drops the flagged name and renormalizes its own
   sign-book (long/short separately, mirroring the old repo), reducing exactly to
   `sum(survivors)/(N-k)` for equal weights (algebra in the docstring). Forced exits
   stay exempt from this guard (unchanged; authorised per acceptance criterion 4).
   Proof: a new parity fixture plants a real >300% spike and matches the old repo's own
   `compute_holding_period_return` to 1e-10; a unit test with divergent expected values
   (5% vs 10%) shows the two policies are not interchangeable. Iteration 1's
   "Escalations: none" was wrong here — corrected by fixing the bug, not escalating,
   since the packet's instruction was explicit.
2. **Actions memoisation — implemented in `pit.py`.** `PITDataContext` now caches each
   ticker's gated actions frame per-instance in `_gated_actions_by_ticker`, returning
   `.copy()` to preserve existing mutation-safety. Three call-count tests: `prices()`
   then `fundamentals()` on one ticker → 1 provider call; a second ticker fetches
   separately; a fresh context never reuses another's cache.
3. **Per-child context factory — tested.** New `test_blend.py` cases: an overreaching
   child does NOT raise without the factory (reproduces the pre-M04 bug) and DOES raise
   `UndeclaredDataError` with it wired; a spy factory proves each child gets its own
   `requires()` (3 and 7, never the union's 7-for-both); nested blend-of-blends
   propagation plus its own bug-reproduction mirror.
4. **Masked-truncation — tested with a real cache dir.** Three `price_availability_
   from_cache` tests against a real `tmp_path` (parquet + sidecar), plus an end-to-end
   `run_backtest` test asserting `coverage_report.masked_tickers`/`overall_bound`.
   Also added 4 tests for the previously-untested `sample_dates` param itself.

## Minors
5. **Not merged into `coverage_report` — documented, per the review's own offered
   alternative.** `CoverageReport` models per-ticker, per-YEAR price availability;
   `unscored_by_date` is a per-rebalance, often non-price event (frequently a missing
   fundamentals field). Folding it in would overstate the gap for a ticker that scored
   fine on every other rebalance that year. Doc note added to engine.py explaining this
   and pointing consumers at both `coverage_report` and `quality_flags` together.
6. **Literal `ValueStrategy` hostile-actions test added**, alongside the existing proxy.

## Verification
`uv run pytest tests/ -q` → exit 0, 315 dots (was 297; +18), no failures/skips.
`uv run ruff check` → All checks passed. `uv run ruff format --check` → 64 files
already formatted.

## Open questions
None new — the two iteration-1 open items (turnover "drift" wording; `next_open`
needing one extra session past `end`) stand as previously stated.
