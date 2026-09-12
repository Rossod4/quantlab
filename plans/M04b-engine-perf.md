# M04b — Real-data run fixes: calendar bounds, negative price cache, run-level panel store

Goal: Make the real-data run correct and fast. The first real 2012–2026 momentum run
(2026-09-11, prefetched cache) took 45 minutes and then crashed. Profile of an 18-month
run (463 s): 395 s inside `PITDataContext.prices()` → `YFinancePriceProvider.get_prices`
→ 34 live yfinance downloads + 262 s of throttle `time.sleep` — the ~150 delisted names
Yahoo no longer serves are re-fetched at EVERY rebalance because failed downloads are
deliberately not cached (M01 gate: a transient failure must never be frozen as
"complete"). The crash: the benchmark computation asks for the whole span as one
lookback, `prices()` doubles it as a calendar-day buffer (→ 2006), and
`exchange_calendars.get_calendar("XNYS")` defaults to a MOVING twenty-year window
(today − 20y), so the request is out of bounds — and any backtest's calendar would
silently change bounds day by day. Both defects are fixed here, without weakening any
bias guard.

## In scope
1. **core/calendar.py — pinned bounds.** `get_calendar("XNYS", start="1990-01-01",
   end="2040-12-31")`. Test: `trading_days("2000-01-03", "2000-01-10")` works; a test
   asserting the calendar's first session is fixed and independent of today (monkeypatch
   nothing; compare to the literal). Document why (reproducibility).
2. **data/pit.py — window clamp.** `window_start` is clamped to the calendar's first
   session; never raises DateOutOfBounds. Test with a lookback that would reach before
   1990.
3. **Negative price cache with TTL (data/cache.py + providers/yfinance_prices.py).** When a
   ticker download returns no rows, write the price sidecar with `no_data: true`,
   `fetched_at`, `requested_start/end`. `has_sufficient_price_cache` returns True for a
   `no_data` sidecar whose `fetched_at` is within `retry_after_days` (PlatformConfig, new
   field, default 30) AND whose requested range covers the request; after the TTL it is
   treated as insufficient and re-fetched (this is the M01 hazard guard: transient
   failures are retried, just not every call). `PriceAvailability` built from the cache
   dir reports `has_data=False` for such tickers (survivorship still counts them). M09's
   data-refresh must be able to force-clear these (document; do not implement M09).
   Tests: (a) second `get_prices` within TTL makes zero provider calls (call-count on a
   fake downloader); (b) after TTL expiry it re-downloads; (c) a later successful
   download replaces the no_data sidecar; (d) survivorship counts the ticker as lacking
   data; (e) the M01 masked-truncation test still passes unchanged.
4. **Run-level `PricePanelStore` (backtest/panel_store.py).** At `run_backtest` start,
   load the FULL universe (every point-in-time constituent over the window, plus the
   benchmark) for `[warmup_start, end]` ONCE via the provider (cache-backed, so this is
   parquet reads plus at most one download per never-seen ticker) into an in-memory
   long-format panel. `PITDataContext` gains an optional `panel_store` (constructor
   kwarg, default None → current provider path). When present, `_sliced_price_panel`
   slices from the store instead of calling the provider — the hard `<= asof` slice,
   `_assert_no_future_dates`, the as-of adjustment replay, and the accounting gate all
   run UNCHANGED on the sliced frame. Missing tickers fall back to the provider. The
   engine builds every decision AND accounting context with the store. Same pattern for
   corporate actions (a run-level actions store feeding the existing per-context
   memoisation) and for EDGAR facts frames (per-run per-ticker cache in the fundamentals
   provider — additive; the point-in-time extraction is unchanged).
   Tests: (a) store-backed vs provider-backed contexts produce byte-identical `prices()`,
   `prices_for_returns()`, `actions()`, `fundamentals()` output on the M02/M02b fixtures
   (parametrise the existing tests over both paths where cheap, else a dedicated parity
   test); (b) EVERY canary in tests/canaries/test_lookahead.py is run a second time with a
   store-backed context (parametrise `_minimal_context` over `panel_store` None / built);
   (c) a hostile store containing post-asof rows: `prices()` output is byte-identical
   with and without them (the store is untrusted like a provider); (d) the engine's
   provider call count over a 3-rebalance fixture is one `get_prices` per ticker set, not
   one per rebalance.
5. **Benchmark computation** reads from the store (accounting path), no giant context.
6. **Run timing in provenance:** `provenance.run_seconds`.

## Out of scope
M09 `quantlab data` command and refresh/invalidation CLI (document the need). Any change
to strategy plugins, validation, or the adjustment formula.

## Context (read these, nothing else)
- This packet; CLAUDE.md; plans/QUANT-NOTES.md (M01 item on frozen transient failures;
  M02b item on actions-cache staleness; M04 verdict items)
- src/quantlab/core/{calendar,config}.py; src/quantlab/data/{cache,pit,corporate_actions,
  survivorship}.py; src/quantlab/data/providers/{yfinance_prices,edgar_fundamentals}.py;
  src/quantlab/backtest/engine.py; tests/canaries/test_lookahead.py; tests/test_cache.py;
  tests/test_pit.py; tests/test_engine.py; configs/platform.yaml

## Interfaces to honor
`PITDataContext` public accessors unchanged (constructor gains the optional
`panel_store` kwarg only). `Strategy` ABC untouched. `BacktestResult` gains only
`provenance.run_seconds`. No bias guard may be weakened: canaries (a)–(j) must pass on
both context paths.

## Acceptance criteria
1. `uv run pytest` green offline; `ruff check` + `format --check` clean.
2. Calendar bounds pinned and tested; the 2006 request no longer raises.
3. Negative-cache tests (a)–(e) pass; the M01 frozen-failure hazard is explicitly
   addressed by the TTL and documented in cache.py.
4. Store/provider parity byte-identical; all canaries pass on both paths; hostile-store
   canary passes; provider call-count test passes.
5. **Timing, measured on the prefetched data/cache on this machine and stated in the
   handoff:** `quantlab backtest --config configs/backtests/momentum_12_1_2012_2026.yaml`
   completes, produces a result directory, and prints its one-liner in under 10 minutes
   (target: under 3). Record the one-liner in the handoff — it is the first real number
   the platform has produced, and it will be compared to the old repo's 15.7% net CAGR /
   0.96 Sharpe (differences must be explained: universe coverage, delisting exits,
   adjustment replay, one-session lag are all legitimate; anything else is a finding).
6. The store is untrusted: a post-asof row planted in it never reaches a strategy.

## Verification commands
- `uv run pytest tests/ -q`; `uv run ruff check`; `uv run ruff format --check`
- `time uv run quantlab backtest --config configs/backtests/momentum_12_1_2012_2026.yaml --out <tmp>`
