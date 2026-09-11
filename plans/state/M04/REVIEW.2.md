REVIEW: APPROVE

## Verification commands (all pass)
- `uv run pytest tests/ -q` → exit 0, 315 dots (was 297; +18), no failures/skips.
- `uv run ruff check` → All checks passed.
- `uv run ruff format --check` → 64 files already formatted.
- `git diff --stat src/` after my own checks: unchanged from before I started (I made
  no file edits this iteration — all extra verification below was done with throwaway
  `python -c` snippets, not repo mutations).

## Iteration-1 blockers — all four closed, verified directly, not just read

1. **Extreme-return guard now excludes-and-renormalizes, not caps-at-0%.**
   `_weighted_return_excluding` (`src/quantlab/backtest/engine.py:433-478`) drops the
   flagged name and rescales the survivors' weights within their OWN sign-book
   (long/short handled by two independent passes keyed on `(w > 0) == is_long_book`).
   Confirmed three ways:
   - `tests/parity/test_engine_parity.py::test_new_engine_matches_reference_with_a_single_period_extreme_return_spike`
     plants a real ~400% spike on T6 (a genuine top-3 holding pre-switch, per `_GROWTH`)
     and asserts 1e-10 agreement against the OLD REPO's own
     `compute_holding_period_return`. The test first asserts
     `(spiked_level/prior_level - 1.0) > 3.0` before trusting the parity check, so it
     isn't a spike that happens to be too small to exercise the guard. I ran this test
     in isolation: 3 passed.
   - `tests/test_engine.py::test_extreme_return_guard_excludes_name_and_renormalizes_book`
     directly distinguishes the two policies numerically (10% expected, not the old
     buggy policy's 5%) and passes.
   - **Long-short renormalization (explicitly asked for by the team lead) has no test
     anywhere in the suite**, so I verified it myself by calling
     `_weighted_return_excluding` directly with a mixed long/short book (0.3/0.3 long,
     −0.2/−0.2 short, extreme name in the SHORT book only): the long book's contribution
     was untouched and only the short book's survivor was rescaled
     (`-0.2 * 2.0 * 0.10`), matching hand-computed expectations exactly. Correct, but
     genuinely untested — noting as a residual minor below, not a blocker (the
     structural code, `for is_long_book in (True, False)` with `survivors`/`book_total`
     scoped inside each pass, makes an accidental cross-book leak hard to introduce
     without also breaking the passing long-only tests).

2. **Actions memoisation implemented in `data/pit.py`, not just documented.**
   `self._actions_cache: dict[str, pd.DataFrame]` is a per-INSTANCE attribute
   (`pit.py:230`), populated only after a successful fetch, returning `.copy()` on both
   the cached and fresh paths (preserves existing mutation-safety, canary d). Three new
   call-count tests in `tests/test_pit.py` pass: one fetch shared across
   `prices()`+`fundamentals()`; independent caching per ticker; no leakage across a
   fresh context instance. I additionally verified the specific scenario the team lead
   asked about that none of those three tests covers directly — stale-cache-error
   surfacing on a NEW context after a prior context succeeded for the same ticker — with
   a throwaway script using a provider that succeeds once then raises
   `StaleActionsCacheError`: a second, fresh `PITDataContext` correctly re-hit the
   provider and raised, with no cross-instance masking.

3. **Per-child context factory now has real tests, including the bug-reproduction
   pair.** `tests/test_blend.py` adds: an overreaching child does NOT raise without the
   factory wired (reproduces the pre-fix bug, confirmed passing — this proves the
   "before" state the fix addresses); the SAME overreaching child DOES raise
   `UndeclaredDataError` once `set_context_factory` is wired; a spy factory proves each
   child gets its own declared `requires()` (3 and 7, never the union's 7 for both); a
   nested blend-of-blends propagates the factory to a grandchild and still raises,
   with a matching without-propagation mirror that doesn't. Ran all 5 directly: pass.

4. **Masked-truncation now tested end-to-end with a real cache dir.**
   `tests/test_survivorship.py::test_price_availability_from_cache_surfaces_a_real_masked_truncation_end_to_end`
   writes an actual parquet cache file plus a sidecar `requested_end` beyond the real
   last bar via `write_cache`/`write_price_cache_meta` into a real `tmp_path`, calls
   `price_availability_from_cache` (not a hand-built `PriceAvailability`), and asserts
   the ticker lands in `coverage_gap(...).masked_tickers[2020]` with `overall_bound`
   moved to 100%. Two companion tests cover the no-cache-file and
   metadata-matches-real-data (unmasked) cases. Four more `sample_dates` tests were
   added beyond what was asked, closing a pre-existing gap on that M04 param.

## Minor findings — reasoning accepted / addressed

5. **Accept the developer's reasoning for not merging `unscored_by_date` into
   `coverage_report`.** The argument (engine.py:119-141): `CoverageReport`/
   `PriceAvailability` model per-ticker, per-YEAR PRICE-data availability, while an
   "unscored at rebalance" event is a per-DATE event often caused by something with
   nothing to do with price data (a missing fundamentals field is the common case for
   the value leg). Forcing it into the yearly price-availability shape would mean
   marking a ticker `has_data=False` for the whole year over one bad rebalance, actively
   overstating the coverage gap for a name that was fine every other rebalance that
   year — a real correctness argument, not a convenience one. The packet's literal
   wording asked for the merge, but the underlying invariant (CLAUDE.md #2: "measured,
   not footnoted") is satisfied by `quality_flags.unscored_by_date` staying a visible,
   undiluted, non-silently-absorbed record, documented with a pointer telling consumers
   to read both fields together. I agree merging as literally specified would produce a
   worse number, not a more honest one. Accepted — no further action needed.
6. **Literal `ValueStrategy` hostile-actions test added**
   (`tests/test_engine.py:305-320`, docstring explicitly reasons about why
   `_EqualWeightStrategy` wasn't sufficient), confirmed present and passing.

## Residual (non-blocking) note for the record
Long-short renormalization (part of finding 1) is correct by direct execution but has
no test in the suite — worth a follow-up unit test in `test_engine.py` mirroring
`test_extreme_return_guard_excludes_name_and_renormalizes_book` but with a negative
weight in the excluded name's book, so a future refactor doesn't rely on my one-off
verification. Not required to hold up APPROVE at this severity.

## Conclusion
All four blockers from REVIEW.md are closed with real, executed proof (parity fixture
against the old repo's own function, call-count tests, factory bug-reproduction pairs,
and a real-cache-dir end-to-end test) — not merely re-documented. The two remaining
minors are resolved to my satisfaction (one fixed, one soundly argued and accepted).
APPROVE.
