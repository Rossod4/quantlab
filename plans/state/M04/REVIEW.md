REVIEW: REVISE

## Verification commands (all pass)
- `uv run pytest tests/ -q` → exit 0, 297 dots, no failures/skips.
- `uv run ruff check` → All checks passed.
- `uv run ruff format --check` → 64 files already formatted.
- `uv run quantlab backtest --help` → works, `--config`/`--out`/`--platform` wired.

## Findings

1. **[BLOCKER] Extreme-return guard silently changes frozen numerics for any real run
   with an extreme return (CLAUDE.md invariant 4).** `src/quantlab/backtest/engine.py:557-561`
   caps a flagged name's contribution at 0% while keeping its full original weight in
   the weighted sum. The old repo (`MomentumValueStrategy/src/backtest/engine.py`'s
   `compute_holding_period_return`) instead **excludes** the name from the equal-weight
   average, shrinking the denominator from N to N−k. For an equal-weight book these are
   NOT the same number: old repo's period return is `sum(survivors)/(N−k)`; the new
   engine's is `sum(survivors)/N`. These diverge by a factor of `N/(N−k)` any time k≥1,
   which is not a rounding-level difference — it changes every subsequent equity-curve
   value for the rest of the run. The work packet's "In scope" section is explicit:
   "port the old `EXTREME_MONTHLY_RETURN_BOUND=3.0` guard, **same semantics: upside-only,
   count and exclude**" — "exclude" was a specific instruction, not a suggestion, and
   this developer substituted a different, more conservative policy without escalating.
   The parity fixture has no extreme returns (by design, per the packet's fixture spec),
   so `tests/parity/test_engine_parity.py` never catches this — but the shipped
   `configs/backtests/momentum_12_1_2012_2026.yaml` (14 years, small/mid-cap momentum,
   real yfinance data) is very likely to hit ≥300% single-period gains on individual
   momentum names in that window (2020-2021 alone), so this is not a theoretical
   concern for the actual production run this milestone exists to enable. Fix: either
   port the old exclude-and-shrink-denominator behavior verbatim as the default
   (documenting how it generalizes to unequal weights, e.g. renormalizing surviving
   weights to sum to 1), or escalate this as a genuine ambiguity requiring an
   orchestrator decision — do not ship a silent, undocumented-to-the-orchestrator
   change to frozen numerics. HANDOFF.md's "Escalations: none" is incorrect; this
   should have been one.

2. **[BLOCKER] M03b carried item 9 ("per-context actions memoisation") is not
   implemented at all.** The packet's carried-items list (binding) requires: "Within
   one `PITDataContext` the gated actions frame for a ticker is fetched once and reused
   by `prices()` and `fundamentals()` (today each call re-reads)... prove by a
   call-count test on a fake provider." `src/quantlab/data/pit.py` is untouched by this
   milestone (`git diff HEAD -- src/quantlab/data/pit.py` is empty) and
   `_gated_actions_by_ticker` (pit.py:254-266) still calls
   `self._corporate_actions_provider.get_actions(...)` fresh on every invocation, with
   no caching. Only the OTHER half of item 9 (blend child-construction caching via
   `_children_cache` in `src/quantlab/strategies/blend.py`) was done. This item is not
   mentioned in HANDOFF's "Escalations" or "Open items" sections as skipped or deferred
   — it reads as simply missed. This is a real perf/correctness gap the packet calls
   "required for the real run" (repeated actions fetches for the same ticker within one
   rebalance across `prices()`/`fundamentals()` calls, times the full 2012-2026
   universe, times ~170 monthly rebalances).

3. **[BLOCKER] Per-child context factory (carried item 6) has zero test coverage —
   including its core correctness property.** `grep -rl set_context_factory .` matches
   only `src/quantlab/backtest/engine.py` and `src/quantlab/strategies/blend.py` —
   nowhere in `tests/`. The packet's whole reason for requiring this mechanism was:
   "a child that over-reaches its own footprint raises `UndeclaredDataError` standalone
   but NOT inside a blend" (i.e., under-declaration by a child inside a blend must
   raise) — this exact property, the nested-blend propagation path
   (`blend.py:213-215`), and the basic engine↔blend wiring are all completely
   unexercised by any test. `tests/test_engine.py` never constructs a `BlendStrategy`
   at all, and `tests/test_blend.py` never calls `set_context_factory`. One of the four
   shipped production configs (`blend_50_50_2012_2026.yaml`) depends on this exact
   mechanism. I confirmed by reading the code that the closure correctly reads
   `asof_box["value"]` at call time (not capture time), so it likely works — but "likely
   works, confirmed only by the reviewer reading it" is not what a call-count/behavioral
   test is for. Add: (a) a test that a child declaring less than the blend's union
   requirements raises `UndeclaredDataError` when it tries to over-reach, with the
   factory wired, and doesn't raise without it (demonstrating the bug the mechanism
   fixes); (b) a nested blend-of-blends propagation test.

4. **[BLOCKER] Acceptance criterion 7 (masked-truncation counted in coverage report) is
   untested for the actual M04 code path.** `price_availability_from_cache` (new,
   `src/quantlab/data/survivorship.py:164-196`) is the function that is supposed to
   populate `masked_end` from cache-sidecar metadata so `coverage_gap` can surface a
   masked truncation — but every call site in `tests/test_engine.py` passes
   `cache_dir=Path("__no_such_quantlab_test_cache__")` (a directory that never exists),
   so `price_availability_from_cache` returns `has_data=False` for every ticker and
   `masked_end` is never populated or exercised end-to-end. `tests/test_survivorship.py`
   tests `coverage_gap` with a hand-built `PriceAvailability(masked_end=...)` object
   directly, which is a fine unit test of `coverage_gap` itself (pre-existing, M02) but
   proves nothing about the NEW `price_availability_from_cache` bridge function this
   milestone adds. Add a test with a real temp cache dir + sidecar meta file
   (`requested_end` beyond the last cached bar) feeding `price_availability_from_cache`
   directly, and ideally one feeding it through `run_backtest` end-to-end.

5. **[Minor] Carried item 5 ("unscored names counted into the coverage report") is only
   partially closed.** The packet says unscored/unpriceable names must be "counted into
   the coverage report as 'unpriceable/unscored at rebalance.'" The engine correctly
   records them in `quality_flags.unscored_by_date` (`engine.py:600-602`, well tested),
   but `coverage_gap(...)` (`engine.py:674-676`) is called with only
   `universe_history`/`price_availability` — `unscored_by_date` is never passed in or
   merged into `CoverageReport`. The information is visible (not silently absorbed,
   satisfying CLAUDE.md invariant 2's spirit) but the single "coverage bound" the
   platform is built around does not reflect selection effects from unscoreable names,
   which is what the packet asked for literally. Low severity because the data is
   surfaced somewhere and this is more a documentation/interpretation question than a
   correctness bug — worth a one-line doc note in the engine docstring if the decision
   is to keep it as a separate flag rather than merging.

6. **[Minor] Carried item 8 (M03b: hostile actions provider tested "during a
   value-strategy rebalance") uses a proxy strategy, not the value strategy.**
   `tests/test_engine.py::test_per_ticker_data_failure_is_dropped_and_recorded` uses
   `_EqualWeightStrategy`, not `ValueStrategy`. I confirmed this is architecturally
   sound regardless — `_FilteringConstituentsProvider` probes the shared
   corporate-actions fetch at context-construction time, before any strategy's
   `generate_targets` runs, gated only on `needs_universe and (price_lookback_days > 0
   or fundamental_fields)`, so the same one policy/one counter is exercised for any
   strategy including a value strategy — but the packet asked for the literal scenario
   and a reviewer/quant-gate shouldn't have to re-derive that equivalence from the
   source to trust it. Not a blocker; add a value-strategy variant of this test for
   documentation/confidence.

## Items verified clean (no findings)

- **Frozen numerics — everything except the extreme-return guard (finding 1):**
  `apply_transaction_costs`, `corwin_schultz_spread`, `monthly_borrow_fee` are verbatim
  ports, confirmed by line-by-line diff against the old repo. `compute_turnover`'s
  empty-old-book (→1.0) and empty-new-book (→0.0) special cases are NOT a change to old
  behavior — I traced the old repo's set-based formula (`1 - overlap/top_n`) on an empty
  old portfolio and confirmed it also produces 1.0; this generalization is faithful.
- **Parity test** (`tests/parity/test_engine_parity.py`) genuinely imports and executes
  the old repo's own `compute_momentum_signal`/`select_top_n`/
  `compute_holding_period_return`/`compute_turnover`/`apply_transaction_costs` via
  `sys.path`, replicates the old loop faithfully, and passes. The two documented bridged
  conventions (NYSE-session vs calendar-month-end date labeling; first-rebalance
  turnover empty-book case) are legitimate mechanical bridges, not tolerance-widening.
- **Mutation-tested canary (i) myself, twice**, reverting each time (confirmed
  `git diff --stat src/` unchanged after, full suite green): (a) changed the decision
  context's `asof` to the next rebalance date → canary failed as expected; (b) handed
  the strategy an accounting-path context (`_accounting_context`, the same kind
  `prices_for_returns()`'s internal helpers use) instead of the decision-path context →
  canary failed (raises `UndeclaredDataError` on `ctx.universe()`, since the accounting
  context is built with `needs_universe=False`). The canary has real power against
  exactly the regression acceptance criterion 9 names.
- **Forced exits:** the fixture in `test_forced_exit_books_at_last_close_with_haircut_and_counts_it`
  confirms a mid-period-ending name books an exit and increments `forced_exits`. I
  confirmed in the engine code (`engine.py:552,562,564`) that the forced-exited ticker's
  realized return is computed (`last_price/entry_fill - 1`) and included at its FULL
  original weight in the period's weighted return — it is not dropped and the
  denominator/other names' weights are not implicitly inflated, correctly diverging
  from the old repo's "drop from average" convention as CLAUDE.md invariant 3 and
  packet acceptance criterion 4 require (no `legacy_drop` needed, correctly stated as
  not needed since the parity fixture excludes delistings).
- **Carried item 1 (netted-book blend costing):** real test with a magnitude assertion
  (`test_netted_book_turnover_is_lower_than_sum_of_per_sleeve_turnovers`, 0.30 per-sleeve
  vs ~0.0 netted).
- **Carried item 2 (month contiguity):** `_month_end_prices` reindexes to the full
  contiguous month range; `test_deleting_one_month_produces_an_all_nan_row_not_a_silent_13_month_lookback`
  tests it directly.
- **Carried item 3 (formation-month policy):** documented (not enforced by raising) in
  `momentum.py`'s module docstring, an acceptable resolution per the packet's
  "developer's call, stated in the handoff" language.
- **Carried item 4 (unscoreable date + abort flag):** both
  `test_unscoreable_date_aborts_by_default` and
  `test_unscoreable_date_records_and_holds_prior_when_configured` exist and pass;
  record-and-hold-prior correctly drops a forced-exited name's weight to cash rather
  than redistributing (`engine.py:594`).
- **Carried item 7 (stale share terms caveat):** M03b already merged; not applicable.
- **Carried item 10/11 (`known_caveats`, `data_semantics_version`):** both present in
  `BacktestResult.provenance` (`engine.py:687-692,710-711`), `DATA_SEMANTICS_VERSION =
  "m03b"` defined in the new `core/semantics.py`.
- **pyproject.toml change:** narrowly scoped to
  `[tool.ruff.lint.flake8-bugbear].extend-immutable-calls`, adding
  `typer.Option`/`typer.Argument`/`pathlib.Path` to the B008 false-positive allowlist —
  does not suppress any rule repo-wide.
- **`BacktestResult.save`/`load`:** round-trips series to 1e-12, provenance exactly,
  holdings/snapshots, quality flags, and coverage report
  (`tests/test_result.py`, `test_save_load_round_trip_on_a_real_run` in
  `tests/test_engine.py`). Uses JSON + parquet, no pickle — fully JSON-serialisable
  provenance confirmed by direct equality test.
- **`next_open` vs `close` fills:** `test_next_open_execution_produces_a_different_result_than_close`
  hand-computes the overnight gap and asserts the fill difference equals it exactly.
- **Benchmark alignment, terminal partial period, coverage-at-rebalance-dates:** all
  have direct, real-number tests (`test_benchmark_first_return_date_matches_strategy_first_return_date`,
  `test_drop_terminal_partial_period_removes_a_spurious_non_boundary_final_date`,
  `test_coverage_report_is_sampled_at_rebalance_dates`).

## What's needed to move to APPROVE
Findings 1-4 are blockers. 1 requires either reverting to the old repo's exclude
semantics (with a documented, sound generalization to unequal weights) or an explicit
escalation to the orchestrator if the developer believes the packet's own instruction is
wrong. 2 requires actually implementing the pit.py-level actions memoisation with a
call-count test. 3 requires at minimum one test proving the per-child factory's
under-declaration-raises property, plus a nested-blend test. 4 requires a real-cache-dir
test of `price_availability_from_cache`. Findings 5-6 are minor and do not block.
