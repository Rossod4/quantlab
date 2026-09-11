# M04 HANDOFF — generic EOD backtest engine

**Files created:** `src/quantlab/backtest/{__init__,costs,accounting,result,config,engine}.py`;
`src/quantlab/core/semantics.py`; `configs/backtests/{momentum_12_1_2012_2026,
momentum_12_1_2012_2026_next_open,value_composite_2012_2026,blend_50_50_2012_2026}.yaml`;
`tests/{test_costs,test_accounting,test_result,test_engine}.py`,
`tests/parity/test_engine_parity.py`.
**Files edited:** `src/quantlab/data/survivorship.py` (additive `sample_dates` param +
`price_availability_from_cache`); `src/quantlab/strategies/blend.py` (additive
`set_context_factory` + child caching — intentional M03 extension per packet item 6);
`src/quantlab/strategies/momentum.py` (`_month_end_prices` reindexed to full contiguous
month range — packet item 2, new test in `tests/test_momentum_strategy.py`);
`src/quantlab/cli.py` (`backtest` command); `pyproject.toml` (ruff
`extend-immutable-calls` for `typer.Option`/`Argument`/`Path` — false-positive B008 fix).

**Key decisions (see engine.py/costs.py module docstrings for full reasoning):**
1. `compute_turnover`/`transaction_cost_fraction` special-case an empty old/new book
   (1.0/0.0, matching old repo's hardcoded convention) — the general 0.5·Σ|Δw| formula
   does NOT reduce to this for an empty book; needed for period-1 parity.
2. Two parallel tracks: `gross_returns`/`net_returns` use the old repo's ADDITIVE
   `gross − cost` convention (required for 1e-10 parity); `accounting.Ledger` compounds
   multiplicatively for `snapshots`. They agree to first order, not bit-for-bit.
3. Extreme-return guard caps a name's contribution at 0% for one period (not the old
   repo's exclude-and-implicitly-redistribute, ambiguous for non-equal weights).
4. Forced exit triggers on "price series ends before period end" only (a strict
   superset of `infer_delisting()`); `infer_delisting` not called in the hot path.
5. Ledger uses the mode-dependent RAW column (close/open) for fills; the return series
   always uses `adj_close` at the same two fill dates — conflating these was a real bug
   caught by the `next_open` divergence test during development, now fixed and tested.
6. Blend costing is netted-book by construction (engine diffs consecutive, already-
   blended `TargetWeights`) — no blend-specific code needed; magnitude test in
   `test_costs.py` (fixture: 0.30 per-sleeve vs 0.0 netted turnover).
7. `_FilteringConstituentsProvider` probes only the corporate-actions fetch (the shared
   dependency of `prices()`/`fundamentals()`) — one policy, one counter, per M03b item.
8. Any `ValueError` from `generate_targets` is treated as unscoreable (no dedicated
   exception type added to `base.py`); record-and-hold-prior drops a forced-exited
   name's weight to cash rather than redistributing it.

**Canary:** packet calls its new canary "(g)"; (g)/(h) are already taken by M03/M03b,
so it's `(i)` in `tests/canaries/test_lookahead.py`. Mutation-check performed: changed
the decision context's `asof` to the next rebalance date — canary failed (asserting
`2020-02-28 != 2020-01-31`); reverted; canary passes again.

**Verification:** `uv run pytest tests/ -q` → exit 0, 297 dots, no failures/skips.
`uv run ruff check` → All checks passed. `uv run ruff format --check` → 64 files
already formatted. `uv run quantlab backtest --help` → works.

**Escalations:** none. No frozen interface needed extending beyond the packet's
explicit allowances (context-factory on Blend, `coverage_gap(sample_dates=)`,
`price_availability_from_cache`).

**Open items for the reviewer:** (a) turnover's "drift" wording in the packet vs the
undrifted convention actually implemented — deliberate, argued in costs.py/engine.py
docstrings, flagging since it reads differently from a literal reading of the packet.
(b) `next_open` mode requires price data one session past the configured `end` date
(the final period's fill date) — undocumented elsewhere; real yfinance data through
"today" satisfies this but a fixed historical `end` near the data's edge would not.
