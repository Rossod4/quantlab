# M04b HANDOFF

## Files changed
- `src/quantlab/core/calendar.py`: pinned XNYS bounds [1990-01-01, 2040-12-31]; `calendar_first_session()`.
- `src/quantlab/data/pit.py`: window clamp to `calendar_first_session()`; `PITDataContext` gains `panel_store`/`actions_store` kwargs (default None, additive).
- `src/quantlab/core/config.py`: `PlatformConfig.retry_after_days: int = 30`.
- `src/quantlab/data/cache.py`: negative price-cache sidecar (`no_data`, TTL-gated) in `has_sufficient_price_cache`; `write_price_cache_no_data_meta`; M09 force-clear documented, not implemented.
- `src/quantlab/data/providers/yfinance_prices.py`: writes the negative sidecar when a ticker's download comes back empty; `retry_after_days` ctor param.
- `src/quantlab/data/interfaces.py`: wires `PlatformConfig.retry_after_days` into `YFinancePriceProvider`.
- `src/quantlab/data/providers/edgar_fundamentals.py`: per-run per-ticker facts cache (additive; extraction unchanged).
- `src/quantlab/backtest/panel_store.py` (new): `PricePanelStore` — run-level in-memory price panel; date-range-first slicing on a sorted index (perf iteration 2).
- `src/quantlab/data/corporate_actions.py` (perf iteration 2): per-instance in-memory read cache in `get_actions`, self-healing on a stale hit (re-reads disk once, so an out-of-band `refresh_actions_cache()` is still honored — required to keep `test_refresh_actions_cache_clears_staleness` green).
- `src/quantlab/data/adjustment.py` (perf iteration 2): hoisted `Series.to_numpy()` conversions out of `apply_asof_adjustment`'s per-ticker loop — pure perf fix, identical numerics (see comment).
- `src/quantlab/backtest/engine.py`: run-level panel/actions store build+wiring; `_benchmark_returns` reads the store over an explicit `[fill_dates[0], fill_dates[-1]]` range instead of a whole-run lookback count; `provenance.run_seconds`; `provenance.dirty` (+`_git_dirty`, orchestrator item 7) with a `known_caveats` note when git is unavailable.
- Tests: `test_calendar.py`, `test_pit.py`, `test_cache.py`, `test_engine.py`, `tests/canaries/test_lookahead.py` (canaries a–h parametrized over `panel_store` None/built).

## Deviations
- Edited `data/interfaces.py` and `data/adjustment.py`/`data/corporate_actions.py` though not in the packet's original Context list — required to wire `retry_after_days` and to fix two perf regressions found only by profiling (see below); read in full first, changes are additive/perf-only.
- `PricePanelStore`'s warmup window is sized by **trading sessions**, not a calendar-day buffer — a calendar-day buffer landed outside the shared cache's actual prefetched range and triggered a mass re-fetch; session-count sizing verified to fit inside it (see `_panel_store_warmup_start`'s docstring).

## Performance iteration (findings 1–3 below required a second dev pass after the first hand-off attempt)
1. First full-run measurement: **31m56s** — over the 10-minute bound.
2. Profiled an 18-month config under cProfile: `apply_asof_adjustment` was re-converting full pandas columns to numpy **inside** its per-ticker loop (O(tickers × rows) instead of O(rows)); `YFinanceCorporateActionsProvider.get_actions` re-read the same ticker's parquet+JSON from disk on every call (no memoization) — driven mainly by `_FilteringConstituentsProvider.membership()`'s per-rebalance probe, which doesn't use the run-level actions store by design. Fixed both; also switched `PricePanelStore` to slice by date range first (binary search on a sorted index) instead of a full-panel boolean scan.
3. 18-month profile: **3m34s → 1m13s** (both under cProfile overhead).
4. Full 2012–2026 momentum run, warm cache: **9m19s** (`run_seconds=557.19`) — under the 10-minute bound, above the 3-minute target. Remaining cost is dominated by `apply_asof_adjustment`'s per-ticker loop itself (frozen, parity-tested numerics) — a candidate for a future perf packet, not touched further here.
5. One-liner: `net CAGR=17.84% Sharpe=0.99 maxDD=-23.26% coverage_bound=22.3% forced_exits=1 extreme_returns=0 unscoreable_dates=0` (vs. old repo's 15.7%/0.96; difference plausibly explained by universe coverage, delisting exits, the M02b adjustment replay, and the one-session lag).
6. Cold-cache negative-cache path verified live: `plans/state/M04b/timed_run.log` shows ~150 delisted names fetched exactly once (panel-store warmup), each writing a `no_data` sidecar.

## Tests
`uv run pytest tests/ -q`: exit 0, 444 dots. `uv run ruff check` / `format --check`: clean.

## Open questions / escalations
None blocking. M09 still needs: negative-cache force-clear CLI (documented in `cache.py`), `refresh_actions_cache()` operational caller (carried, unchanged).

Artifacts: `plans/state/M04b/{profile1,profile2}.prof`, `profile_run{1,2}.log`, `timed_run.log` (cold), `timed_run_out2/` (warm run result).
