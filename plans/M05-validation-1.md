# M05 — Validation I: metrics, walk-forward, sensitivity, regime robustness

Goal: The first half of the validation report card. Port the old repo's metrics and
walk-forward machinery verbatim onto `BacktestResult`, add parameter-sensitivity
("no-cliff") and regime/sub-period robustness, and expose everything through a single
`validate_basic(result, config) -> ValidationBasic` that M06 composes into the final
report card. Every ported number is golden-tested against the old repo.

## In scope (create these)
- src/quantlab/validation/__init__.py
- src/quantlab/validation/metrics.py — port `cagr`, `annualized_vol`, `sharpe_ratio`,
  `max_drawdown` VERBATIM from old src/evaluation/metrics.py (frozen numerics;
  `periods_per_year` stays an explicit argument — never inferred). Add `calmar`,
  `sortino` (downside deviation, annualised the same way), `hit_rate`, `turnover_mean`,
  `cost_drag_cagr` (gross CAGR − net CAGR), `tracking_error` and `information_ratio`
  vs benchmark, `beta` vs benchmark — each with a hand-computable unit test. A
  `summary(result: BacktestResult) -> MetricsSummary` that reads periods_per_year from
  the result's rebalance freq (month_end → 12, quarter_end → 4, weekly → 52).
- src/quantlab/validation/rolling.py — port `rolling_window_metrics` verbatim
  (ValueError on series shorter than one window preserved) + `subperiod_table(result,
  splits)` for fixed sub-periods (first half / second half, and named regimes from
  config: e.g. 2012–2019, 2020 covid, 2021–2022 rate shock, 2023+ — regimes are CONFIG,
  configs/validation.yaml, not code).
- src/quantlab/validation/walk_forward.py — port `walk_forward_blend` verbatim
  (Sharpe criterion, coarse grid, rolling train window, partial final test block kept,
  common-dates alignment) generalised to N child return series via a
  `weight_grid: list[tuple[float, ...]]`; the 2-sleeve grid reproduces the old result
  exactly. Input: the child `BacktestResult`s' net returns (compounded to the common
  frequency via a ported `compound_to_quarterly`, generalised to `compound_to(freq)`).
  Document in the module docstring, as the old repo did, that the blend-of-net-returns
  here is the OLD convention and differs from M04's netted-book costing (QUANT-NOTES M03
  item 2); the walk-forward asks a question about weight-choice stability, not about
  the netted cost, so the old convention is the right one for this test. State this.
- src/quantlab/validation/sensitivity.py — `sensitivity_grid(strategy_config, param_axes,
  backtest_config, runner) -> SensitivityResult`: reruns the backtest over a small grid
  of one or two parameters (e.g. lookback_months ∈ {9,12,15}, n_long ∈ {30,50,70}) and
  reports the metric surface plus a `no_cliff_score` = 1 − (max − min)/|median| of net
  Sharpe over the grid's immediate neighbours of the base point (document the exact
  definition; values near 1 mean flat, near 0 mean the base point sits on a cliff).
  The runner is injected so tests use a fake that returns canned results — NO real
  backtests in the offline suite. Every rerun uses the SAME `strategy_id` family but a
  distinct id per point; record every point as a trial (M06's registry will consume
  `SensitivityResult.trials`, so shape it as a list of (strategy_id, params, net Sharpe)
  now).
- src/quantlab/validation/basic.py — `validate_basic(result, benchmark_result | None,
  config) -> ValidationBasic` dataclass: metrics summary, rolling table, sub-period
  table, optional walk-forward and sensitivity results, and a `flags: list[str]` of
  plain-English observations (e.g. "SPY Sharpe exceeds strategy Sharpe", "58% of
  rolling 3y windows negative"). No verdict here — M06 owns the verdict.
- configs/validation.yaml — rolling window years, regime splits, walk-forward
  train/test years and weight grid, sensitivity axes per strategy family, and the
  thresholds M06 will gate on (put them here now, unused until M06, so gates are config
  not code).
- CLI: `quantlab validate --result <dir> [--benchmark <dir>] --out <dir>` (basic tier).
- tests/test_metrics.py, test_rolling.py, test_walk_forward.py, test_sensitivity.py,
  test_validation_basic.py, tests/parity/test_metrics_parity.py.

## Out of scope
Purged CV, PSR/DSR, White RC/SPA, Monte Carlo, capacity, the verdict (all M06).
Plots (M07).

## Context (read these, nothing else)
- This packet; CLAUDE.md; plans/QUANT-NOTES.md (items addressed to M05)
- Existing quantlab: src/quantlab/backtest/result.py (as merged from M04 — read its
  actual fields), src/quantlab/backtest/config.py, src/quantlab/core/calendar.py
  (RebalanceFreq), src/quantlab/cli.py, src/quantlab/strategies/blend.py (weights
  convention only)
- Port sources (read-only, root C:\Users\arwga\Developer\ClaudeProjects\Trading\
  MomentumValueStrategy): src/evaluation/metrics.py, src/evaluation/walk_forward.py,
  src/evaluation/comparison.py (compound_to_quarterly, blend_returns, DEFAULT_SWEEP_WEIGHTS,
  QUARTERS_PER_YEAR), tests/test_metrics.py, tests/test_walk_forward.py,
  tests/test_comparison.py, REVIEW_PHASE5.md §6 (the walk-forward numbers).

## Interfaces to honor
`BacktestResult` as merged from M04 — read-only consumer; do not extend it. Ported
functions keep the old signatures (ported numerics frozen).

## Acceptance criteria
1. `uv run pytest` green offline; `ruff check` and `ruff format --check` clean.
2. Metrics parity: the old repo's five metrics tests reproduced on the same synthetic
   series to 1e-12 via the new module (import old functions by sys.path inside the
   parity test and compare, or hard-code with provenance comments — choose, document).
3. Walk-forward parity: on a synthetic two-sleeve fixture, the new N-sleeve
   implementation with the 5-point grid reproduces the old `walk_forward_blend`'s
   chosen-weight sequence and out-of-sample series exactly (1e-12), including the
   partial final block and the common-dates alignment.
4. Rolling: the old three rolling tests pass against the port; sub-period table sums
   are consistent with full-period equity (product of sub-period growth = total growth,
   1e-10).
5. Sensitivity: on a fake runner with a planted cliff, `no_cliff_score` is low; on a
   flat surface it is ~1; the trials list has one entry per grid point with distinct
   strategy_ids.
6. `validate_basic` on a fixture result produces the flags listed above deterministically
   and serialises to JSON round-trip.
7. New metrics each have a hand-computed test (sortino on a series with known downside
   deviation; beta = 1 for a series equal to the benchmark; IR = 0 when identical).

## Verification commands
- `uv run pytest tests/ -q`; `uv run ruff check`; `uv run ruff format --check`
- `uv run quantlab validate --help`

## Parity fixtures
Synthetic monthly and quarterly return series with hand-computable answers (constant
returns, a single 50% drawdown, a sleeve that dominates then flips) — the old repo's
own test fixtures are the model; reuse their shapes.

## Carried from the M04 verdict (binding — see plans/QUANT-NOTES.md "From M04 verdict")
1. Metrics are computed ONLY from `net_returns` / `net_equity` / `gross_*` and the
   benchmark series — never from `snapshots` (the ledger never credits dividends and
   diverges from net_equity by roughly the cumulative dividend yield). Add a test that
   `summary()` does not touch snapshots (pass a result with snapshots deleted).
2. `quality_flags.extreme_returns` (and the per-book counts) is a right-tail-only
   truncation and feeds skew/kurtosis; any nonzero count must appear in the one-line
   summary and in `ValidationBasic.flags` so M06 prints it beside PSR/DSR.
3. `quality_flags.missing_forward_prices` duplicates `forced_exits`; do not report it as
   a second number. Report `forced_exits`, `extreme_returns_long/short`,
   `unscored_by_date`, `dropped_tickers_by_date` once each.
4. Any headline "how much of this book can't be trusted" figure combines the coverage
   bound AND the unscored/dropped counts; the flags text must say they are separate
   selection effects.
5. Add a static canary in tests/canaries/: no registered strategy's source calls
   `prices_for_returns` (AST scan of src/quantlab/strategies/); complements the M04
   structural guard.
