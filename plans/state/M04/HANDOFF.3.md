# M04 HANDOFF.3 — quant-gate cycle 1 (REJECT -> addressed)

**Files changed:** `src/quantlab/backtest/engine.py` (core accounting fixes + docstring
corrections), `src/quantlab/backtest/config.py` (`extreme_return_policy`, haircut comment
fix), `src/quantlab/backtest/result.py` (`QualityFlags`: per-book extreme counts,
degenerate-book dates); `tests/test_engine.py` (+13 regression tests, one per finding
plus A/B and caveat checks).

## Per-finding status

1. **Coverage bound over universe — fixed.** `all_universe_tickers` now accumulates the
   union of `ctx.universe()` across every rebalance (separate from `all_encountered_
   tickers`, held names, still used for provenance); `price_availability_from_cache` is
   built from their union. Regression: the gate's exact fixture (10-name fully-cached
   universe, top-3 strategy) now reads `overall_bound == 0.0`. Confirmed masked-
   truncation fires for a name the strategy never held.
2. **`delisting_haircut` reaches returns — fixed.** Forced-exit return is now
   `(exit_adj / entry_adj) * (1 - haircut) - 1`, applied in the additive return series,
   not only the ledger. Regression: haircut 0.0/0.5/1.0 on a 50%-weighted name gives
   `net_equity` 1.0/0.75/0.5 respectively, strictly monotonic.
3. **Forced-exit basis switched to adj_close — fixed.** Same formula as finding 2 uses
   `adj_close` (total-return, already split-adjusted) for both legs, raw `close` kept
   only for the ledger's cash proceeds. The guard now ALSO applies to forced exits
   (re-examined, not silently re-exempted, per the finding's own instruction) since both
   paths share one consistent basis. Regression: the gate's 1-for-10 reverse-split
   fixture plus its keeps-trading control both book ~0%, and `forced_exits`/`0` confirms
   which branch fired.
4. **Extreme guard on shorts — kept as inherited parity, orchestrator decision honored,
   not re-litigated.** Added `extreme_return_policy: "exclude_legacy" | "flag_only"`
   (default `exclude_legacy`, byte-identical trigger to before); per-book counts
   `extreme_returns_long`/`extreme_returns_short`; a `known_caveats` entry when
   `extreme_returns_short > 0` under the default policy; `degenerate_excluded_book_dates`
   for the "whole book excluded" edge case. Four new tests: a squeeze excluded under
   `exclude_legacy`, the same fixture keeping the loss under `flag_only`, an explicit A/B
   showing the two policies diverge, and the degenerate-book case.
5. **`next_open` return basis — fixed.** Total-return basis price is now
   `row[fill_column] * adj_close / close` (the adjusted OPEN in `next_open` mode,
   reducing to exactly `adj_close` in `close` mode - unchanged, still frozen parity).
   Regression: a rally on the fill day itself (flat open, big intraday close) no longer
   leaks into the outgoing book's return.
6. **`prices_for_returns()` made structurally unreachable from a decision context —
   fixed.** `PITDataContext.__init__` gains `accounting: bool = False`;
   `prices_for_returns()` raises `UndeclaredDataError` unless `True`. The engine's
   decision-path `context_factory` (used for the strategy and, via `set_context_factory`,
   every blend child) omits it, defaulting to `False`; only `_accounting_context` (fill/
   settlement/benchmark bookkeeping) passes `True`. Existing direct unit tests in
   `test_pit.py` that called `prices_for_returns()` now construct with `accounting=True`
   (`_context()` gained the same param, default `False`) - listed here as the intentional
   changes: `test_prices_for_returns_includes_adj_close`,
   `test_prices_for_returns_more_lookback_than_declared_raises`. New canary (j) in
   `tests/canaries/test_lookahead.py` asserts a strategy calling `prices_for_returns()` on
   the context the engine hands it raises on every rebalance; mutation-checked by flipping
   the default to `True` (canary failed as expected), then reverted. Also corrected
   engine.py's module docstring: it no longer claims the ledger and `net_equity` "agree to
   first order" (they do not - dividends are the dominant, uncredited gap on the ledger
   side) and now states plainly that M05+ must compute metrics from
   `net_returns`/`net_equity` only, never `snapshots`.

## Parity fixtures
**No changes needed.** Both `tests/parity/test_engine_parity.py` tests (baseline and the
iteration-2 single-period extreme-return spike) still pass unmodified — `exclude_legacy`
is byte-identical to the pre-existing trigger/exclusion logic, and `close` mode's
adjusted-basis formula reduces algebraically to plain `adj_close`.

## Verification
`uv run pytest tests/ -q` → exit 0, **329 dots** (was 315; +10 for findings 1-5, +4 for
finding 6: 3 in `test_pit.py`, 1 new canary). `uv run ruff check` → All checks passed.
`uv run ruff format --check` → 64 files already formatted.

## Non-blocking notes from VERDICT.md
Also corrected in passing (cheap, directly falsified by the gate's own evidence): the
"Two parallel tracks" docstring's claim that the ledger/return-series gap is a
`cost * gross` cross term (actually dominated by the ledger never crediting dividends);
`config.py`'s haircut comment, which had the conservative-direction claim inverted.
`missing_forward_prices` duplicating `forced_exits` and the dirty-tree git sha are left
as-is — informational, not part of the five numbered findings.
