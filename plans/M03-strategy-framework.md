# M03 — Strategy framework + momentum/value plugins

Goal: The plugin framework strategies are written against, plus the two ported
strategies. A strategy is a pure function from `PITDataContext` to `TargetWeights`,
declares its data needs upfront, and is instantiated from YAML config.

## In scope (create these)
- src/quantlab/strategies/__init__.py
- src/quantlab/strategies/base.py — `Strategy` ABC:
  - `strategy_id: str` property (name + short param hash, stable across runs — the
    multiple-testing trials registry in M06 keys on this)
  - `requires() -> DataRequirements` (re-export the M02 dataclass)
  - `generate_targets(ctx: PITDataContext, date: Timestamp) -> TargetWeights` — pure;
    no I/O, no provider access, no state mutation between calls.
  - `params: dict` (from YAML; validated by a per-strategy pydantic model)
- src/quantlab/strategies/registry.py — `@register_strategy("name")` decorator +
  `load_strategy(config_path | dict) -> Strategy`; unknown name raises
  UnknownStrategyError listing known names.
- src/quantlab/strategies/momentum.py — port 12-1 momentum from the old repo:
  `compute_momentum_signal` (12-month return skipping most recent month) and
  top-N selection, exposed as three registered configs of ONE class or subclasses
  (long_only, long_short dollar-neutral, one_thirty_thirty) — weights only; borrow
  fees/constraints are the engine's job (M04). Equal weight within books, as old repo.
- src/quantlab/strategies/value.py — port composite value (P/B + P/E + EV/EBITDA +
  growth-adjusted, percentile-rank combination, loss-makers least-attractive) using
  ctx.fundamentals(); quarterly signal.
- src/quantlab/strategies/blend.py — meta-strategy: weighted combination of child
  strategies' TargetWeights (port blend math from old evaluation/comparison.py's
  combine_strategies weight logic only — not the sweep).
- configs/strategies/momentum_12_1.yaml, momentum_ls.yaml, momentum_130_30.yaml,
  value_composite.yaml, blend_50_50.yaml
- tests/test_strategy_base.py, test_registry.py, test_momentum_strategy.py,
  test_value_strategy.py, test_blend.py
- tests/parity/__init__.py + tests/parity/test_signal_parity.py — golden tests: run
  the OLD repo's signal functions on a fixture (import them by inserting the old
  repo's src on sys.path inside the test, or precompute and hard-code the numbers
  with provenance comments — choose the more robust, document choice) and assert the
  new plugins produce identical scores/selections to 1e-10 on the same fixture data.

## Out of scope
Backtest engine, costs, portfolio accounting (M04). Walk-forward/comparison sweeps
(M05/M06).

## Context (read these, nothing else)
- This packet; CLAUDE.md; plans/QUANT-NOTES.md
- Existing quantlab: src/quantlab/core/*.py, src/quantlab/data/pit.py (as merged from
  M02 — read its actual API), src/quantlab/data/interfaces.py
- Port sources (read-only):
  - ...\MomentumValueStrategy\src\strategy\momentum.py
  - ...\MomentumValueStrategy\src\strategy\value.py
  - ...\MomentumValueStrategy\src\evaluation\comparison.py (combine_strategies only)
  - Old tests: ...\MomentumValueStrategy\tests\test_momentum.py, test_value.py
  (root: C:\Users\arwga\Developer\ClaudeProjects\Trading\MomentumValueStrategy)

## Interfaces to honor
PITDataContext API exactly as merged in M02/M02b (do not extend it; if a strategy
needs something the context lacks, STOP and flag in handoff — that is an escalation,
not a workaround). TargetWeights from core/types.py. DataRequirements from M02.
Price signals MUST be computed on the as-of-adjusted `prices()` from M02b (never
`prices_for_returns()`, never raw close across time).

Per plans/QUANT-NOTES.md (M02 gate): day-granular `filed <= asof` hands same-day
after-hours SEC filings to a same-day decision. The value strategy must apply a
one-session lag on fundamentals availability (use filings with
filed <= prev_trading_day(asof)) OR defend the same-day convention explicitly in the
handoff with the quant gate as the audience. Note the old repo's convention when
porting and preserve parity-test comparability (the parity fixture may pin asof dates
where the lag is immaterial — document).

## Acceptance criteria
1. `uv run pytest` green offline; `uv run ruff check` clean.
2. Signal parity to 1e-10 on fixture data for momentum score, top-N selection order,
   and value composite score (including the loss-maker rule).
3. A strategy accessing data beyond its DataRequirements raises UndeclaredDataError
   (test with a deliberately under-declared strategy).
4. generate_targets never mutates the context or its own params (call twice on the
   same context → identical TargetWeights).
5. TargetWeights sanity: long_only sums to ~1.0, dollar-neutral sums to ~0.0 with
   gross ~2.0, 130/30 nets to ~1.0 with gross ~1.6 (tolerances documented).
6. load_strategy round-trips every YAML in configs/strategies/; unknown strategy name
   raises UnknownStrategyError.
7. strategy_id stable: same YAML → same id; changed param → different id.

## Verification commands
- `uv run pytest tests/ -q`; `uv run ruff check`

## Parity fixtures
Fixture price panel + fundamentals dict sized so expected momentum/value scores are
hand-verifiable; golden numbers with provenance comments.
