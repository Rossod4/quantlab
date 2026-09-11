# M04 — Generic EOD backtest engine

Goal: One engine that runs ANY M03 `Strategy` on a date range by constructing a fresh
`PITDataContext` per rebalance date, books positions and returns with explicit
accounting, charges costs, forces delisting exits, and returns a `BacktestResult` that
embeds the survivorship coverage bound, quality-flag counts, and full provenance.
Equity-curve parity with the old repo is proven on a fixture via a reference
re-implementation of the old loop, not by eye.

## In scope (create these)
- src/quantlab/backtest/__init__.py
- src/quantlab/backtest/config.py — `BacktestConfig` (pydantic, from YAML in
  configs/backtests/): start, end, rebalance freq (reuse `core.calendar.RebalanceFreq`),
  initial_capital, execution mode (`close` | `next_open`), cost model params,
  delisting haircut (fraction of last price, default 0.0 = exit at last close; document
  that >0 is the conservative setting), `extreme_return_bound` (port the old
  EXTREME_MONTHLY_RETURN_BOUND=3.0 guard, same semantics: upside-only, count and
  exclude), benchmark ticker (from platform.yaml), strategy config path.
- src/quantlab/backtest/costs.py — port `compute_turnover` and
  `apply_transaction_costs` from the old repo VERBATIM (frozen numerics), generalised
  to weight vectors: turnover = 0.5 × Σ|w_new − w_old_drifted| for long-only reduces to
  the old set-based formula when weights are equal — prove that in a test. Add
  `corwin_schultz_spread(high, low)` ported from the old scripts/cost_realism_analysis.py
  as an OPTIONAL per-ticker one-way cost mode (`cost_model: flat_bps | corwin_schultz`),
  and `borrow_fee` for short exposure ported from old long_short_engine.monthly_borrow_fee.
- src/quantlab/backtest/accounting.py — `Ledger`: cash + positions (`PortfolioSnapshot`
  from core/types.py), `rebalance_to(target: TargetWeights, fill_prices, costs)`,
  `mark(date, prices)`, `force_exit(ticker, last_price, haircut, reason)`. Pure,
  deterministic, no I/O. Weights are applied as given; long-only sums to 1, long-short
  per M03 conventions; cash earns 0.
- src/quantlab/backtest/engine.py — `run_backtest(strategy, config, providers) ->
  BacktestResult`:
  - Rebalance dates from `core.calendar.rebalance_dates`. QUANT-NOTES (M00): the
    function emits a spurious rebalance on a range-terminal non-boundary day — the
    engine must drop the terminal partial period explicitly and test it.
  - For each rebalance date t: build `PITDataContext(asof=t, requirements=
    strategy.requires())` → `strategy.generate_targets(ctx, t)`. The strategy never sees
    anything else. Universe = constituents as-of t.
  - Execution: `close` mode fills at t's close (parity mode, matches old repo);
    `next_open` mode fills at the next session's open. Fill and mark prices come from
    the ACCOUNTING path `prices_for_returns()` (raw OHLC + adj_close; per M02 verdict the
    adj ratio over an elapsed period is PIT-clean). Never from `prices()`.
  - Period return = Σ w_i × r_i over the holding period using adj_close ratios (this is
    what the old repo did with auto-adjusted closes → parity). Names with a missing
    end-of-period price are NOT dropped: see delisting rule.
  - Delisting / forced exit (CLAUDE.md invariant #3). Trigger on EITHER an inferred
    `DelistingEvent` OR "the ticker's price series ends before the period end"
    (QUANT-NOTES M02: inference under-detects). Book an exit at last available close ×
    (1 − haircut) on the last bar date; count in `quality_flags.forced_exits`.
  - Extreme-return guard: port the old upside-only guard verbatim; count in
    `quality_flags.extreme_returns`.
  - Per-ticker data failure at a rebalance (`StaleActionsCacheError`/`ActionsFetchError`
    /missing prices): the engine may drop the ticker from that rebalance's eligible set
    ONLY IF it records the drop — these drops feed `coverage_report` (QUANT-NOTES M02b:
    a selection effect must be measured, not swallowed). A failure of the benchmark or
    >X% of the universe (config, default 5%) aborts the run with a clear error.
  - Benchmark: buy-and-hold of `benchmark` over the SAME realised-return window (old
    repo Fix 2: first benchmark return aligns with the strategy's first realised
    return). Regression test.
  - Survivorship: call `data.survivorship.coverage_gap` with membership sampled AT THE
    REBALANCE DATES (QUANT-NOTES M02 item 3(i)) — this may require a small additive
    parameter on `coverage_gap` (`sample_dates: DatetimeIndex | None`, default keeps
    year-end behaviour; existing tests unchanged). Populate `PriceAvailability.masked_end`
    from the price-cache sidecar metadata (QUANT-NOTES M02 item 3(ii)) — add a helper in
    data/survivorship.py or data/cache.py that builds `price_availability` from the
    cache dir.
- src/quantlab/backtest/result.py — `BacktestResult` (frozen pydantic or dataclass):
  gross/net period returns, gross/net equity (start 1.0), benchmark returns/equity,
  holdings history (date → TargetWeights), snapshots (date → PortfolioSnapshot),
  turnover series, cost drag series, `quality_flags` (forced_exits, extreme_returns,
  missing_forward_prices, dropped_tickers_by_date), `coverage_report: CoverageReport`,
  `provenance` (strategy_id, strategy params, BacktestConfig dump, provider names from
  platform.yaml, actions-cache fetched_at min/max over the universe, quantlab git sha,
  run timestamp). Must be serialisable to JSON + parquet (`save(dir)` / `load(dir)`)
  because M05–M07 consume it.
- configs/backtests/momentum_12_1_2012_2026.yaml, value_composite_2012_2026.yaml,
  blend_50_50_2012_2026.yaml (start 2012-01-01, end 2026-06-30, flat 10 bps, `close`
  execution for old-repo comparability; a sibling `*_next_open.yaml` for momentum).
- CLI: `quantlab backtest --config <yaml> --out <dir>` wired in src/quantlab/cli.py
  (currently a stub) — runs, saves result, prints the one-line summary (net CAGR, Sharpe,
  maxDD, coverage bound, quality-flag totals).
- tests/test_costs.py, test_accounting.py, test_engine.py, test_result.py,
  tests/parity/test_engine_parity.py, and extend tests/canaries/test_lookahead.py with
  (g): the engine never constructs a context with asof later than the rebalance date it
  is deciding for, and the strategy is never handed prices_for_returns() (assert via a
  spy strategy that records what it received).

## Out of scope
Metrics beyond the one-line summary (M05 ports metrics.py), walk-forward, validation
gates, reporting, paper trading.

## Context (read these, nothing else)
- This packet; CLAUDE.md; plans/QUANT-NOTES.md (every item addressed to M04)
- Existing quantlab: src/quantlab/core/{types,calendar,config,errors}.py,
  src/quantlab/data/{pit,survivorship,cache,corporate_actions,interfaces}.py,
  src/quantlab/strategies/base.py and one strategy (momentum.py) as merged from M03,
  src/quantlab/cli.py, tests/canaries/test_lookahead.py
- Port sources (read-only, root C:\Users\arwga\Developer\ClaudeProjects\Trading\
  MomentumValueStrategy): src/backtest/engine.py (loop + compute_holding_period_return +
  BacktestResult fields), src/backtest/long_short_engine.py (monthly_borrow_fee,
  compute_long_short_period_return), src/costs/transaction_costs.py,
  scripts/cost_realism_analysis.py (corwin_schultz_spread only), tests/test_engine.py,
  tests/test_costs.py, tests/test_long_short.py.

## Interfaces to honor
`Strategy`, `TargetWeights`, `DataRequirements`, `PITDataContext` exactly as merged from
M03 — do not extend. Note M03 added `fundamentals(ticker, *, filing_lag_sessions=0)`
(restrict-only); the engine passes nothing extra — the strategy owns its lag param. `PortfolioSnapshot`/`Position` from core/types.py (frozen, shallow —
copy dicts on every hand-out). `coverage_gap` may gain the additive `sample_dates`
parameter only. `prev_trading_day` is strict — do not use it for inclusive as-of
alignment (QUANT-NOTES M00).

## Acceptance criteria
1. `uv run pytest` green offline; `uv run ruff check` and `ruff format --check` clean.
2. **Engine parity.** tests/parity/test_engine_parity.py builds a synthetic monthly
   price panel + constituents fixture (no delistings, no extreme returns), runs the OLD
   loop as a reference implementation inside the test (import the old repo's
   compute_momentum_signal/select_top_n/compute_holding_period_return/compute_turnover/
   apply_transaction_costs via sys.path, replicate run_backtest's loop over the fixture)
   and asserts the new engine in `close` mode with the M03 momentum plugin reproduces
   net_returns and net_equity to 1e-10. Document any convention difference that had to
   be bridged (e.g. return-date indexing).
3. Turnover generalisation: weight-vector turnover equals the old set-based formula on
   equal weights (test on 3 hand cases).
4. Forced exit: a fixture where a held name's series ends mid-period books an exit at
   last close × (1 − haircut) and increments `forced_exits`; with the old repo's
   "drop from average" convention as a documented, non-default `legacy_drop` policy
   ONLY if needed for parity (state whether it was needed).
5. Terminal partial period is dropped, with a test at a non-boundary end date.
6. Benchmark alignment regression test (first benchmark return date == first strategy
   return date).
7. `coverage_report.overall_bound` in the result is computed at rebalance dates and a
   masked-truncation fixture is counted (reuse the M02 masked-metadata fixture shape).
8. Per-ticker data failure at a rebalance is recorded in `dropped_tickers_by_date` and
   reflected in the coverage report; the >5% abort path is tested.
9. Canary (g) passes and fails under mutation (hand the strategy prices_for_returns()
   → must fail).
10. `BacktestResult.save/load` round-trips (equality on all series to 1e-12, provenance
    dict equal).
11. `next_open` mode produces different fills from `close` mode on a fixture with an
    overnight gap, and the difference equals the gap (hand-computed).

## Verification commands
- `uv run pytest tests/ -q`; `uv run ruff check`; `uv run ruff format --check`
- `uv run quantlab backtest --help`

## Parity fixtures
Synthetic 24-month panel, 8 tickers, constituents table with one join and one leave,
flat 10 bps; golden numbers produced by the in-test reference implementation (not
hard-coded), so the test is a true cross-implementation check.

## Carried from the M03 verdict (binding — see plans/QUANT-NOTES.md "From M03 verdict")
1. **Blend costs — DECIDED by the orchestrator:** the engine costs the NETTED book
   (that is the book that actually trades; netting is a real cost saving), and this is
   documented as a deliberate divergence from the old repo, which blended each sleeve's
   net returns and therefore overstated costs on offsetting positions. Add a test on the
   gate's fixture (a name long in one sleeve, short in the other) showing the netted
   turnover is lower and state the magnitude in the handoff. Blend parity with the old
   repo is therefore NOT an acceptance criterion; momentum parity is.
2. **Month contiguity:** before handing a strategy its context, or inside the momentum
   plugin's month-end pivot (whichever the developer judges the right seam — document),
   assert the month index is contiguous or reindex to the full month range so a missing
   calendar month yields an all-NaN row (old-repo semantics) rather than a silent
   13-month lookback. Test by deleting one month from the fixture.
3. **Formation-month semantics:** rebalance dates for the momentum configs are
   `month_end`; the engine passes the rebalance date as asof so the formation month is
   always a complete month-end. Document that mid-month asof is unsupported for the
   momentum plugin (raise if `freq` is not month_end for a strategy that declares
   month-end sampling, or document) — developer's call, stated in the handoff.
4. **Unscoreable date policy:** when a strategy raises because the scored universe is
   too thin (momentum's disjoint-books guard) or a rebalance drops names for data
   reasons, the engine records the date in `quality_flags` and counts it in the
   coverage report; it NEVER silently shrinks a book. An `abort_on_unscoreable: bool`
   config (default True for research runs) chooses abort vs record-and-hold-prior.
5. **Value-leg silent drops:** names skipped by the value plugin for missing price or
   shares (`_asof_raw_price` None / `not shares_outstanding`) must be surfaced: the
   engine compares the strategy's declared universe with the names it actually scored
   (TargetWeights carries the weights; add an optional `unscored: list[str]` field ONLY
   if additive and default-empty — otherwise infer from universe minus weights keys) and
   counts them into the coverage report as "unpriceable/unscored at rebalance".
6. **Per-child context for blends:** the engine must NOT rely on the blend building one
   union context. Provide a context factory to the blend so each child gets a context
   built from its own `requires()`, preserving acceptance criterion 3 under composition.
   If this needs a small additive change to the blend plugin (a factory callable), make
   it and list it as an intentional M03 change.
7. **Stale share terms (M03b):** the per-share fundamentals split-staleness fix lands in
   M03b before M04's value/blend configs are run for real; M04 does not need to address
   it but must not quote a value or blend result without the M03b caveat if M03b has
   not merged.

## Carried from the M03b verdict (binding — see plans/QUANT-NOTES.md "From M03b verdict")
8. **One data-failure policy for both paths.** `fundamentals()` now depends on the
   corporate-actions path, so `StaleActionsCacheError`/`ActionsFetchError` can surface
   from the value leg as well as `prices()`. The engine's per-ticker failure handling
   (item "Per-ticker data failure" above) must cover BOTH accessors with one policy and
   one counter feeding the coverage report. Test with a hostile actions provider that
   fails for one ticker during a value-strategy rebalance.
9. **Per-context actions memoisation (perf, required for the real run).** Within one
   `PITDataContext` the gated actions frame for a ticker is fetched once and reused by
   `prices()` and `fundamentals()` (today each call re-reads). Also cache the blend's
   child construction so `strategy_id` access is not O(children) reconstruction. Both
   are additive; no semantic change; prove by a call-count test on a fake provider.
10. **Caveat to carry into every value/blend result:** TTM EPS can be a mixed-share-terms
    sum when a split falls between component filings and restated comparatives are not
    yet filed (bounded to the P/E leg; adverse direction, measured 2.5x on a contrived
    fixture). `BacktestResult.provenance` must carry a `known_caveats: list[str]` and the
    engine appends this text for any strategy that declares `ttm_eps`. The proper fix is
    a data-layer follow-on (per-component share terms) scheduled after M06.
11. **Semantics version (for M06):** `BacktestResult.provenance` must record a
    `data_semantics_version` string (start at "m03b") so the M06 trials registry can key
    on strategy_id + semantics version. Define the constant in core/ and bump it whenever
    a merged milestone changes what a strategy sees.
