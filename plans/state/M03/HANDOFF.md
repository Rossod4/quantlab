# M03 Handoff — strategy framework + momentum/value/blend plugins

## Files added
`src/quantlab/strategies/{__init__,base,registry,momentum,value,blend}.py`;
`configs/strategies/{momentum_12_1,momentum_ls,momentum_130_30,value_composite,
blend_50_50}.yaml`; `tests/{test_strategy_base,test_registry,
test_momentum_strategy,test_value_strategy,test_blend}.py`;
`tests/parity/{__init__,test_signal_parity}.py`;
`tests/canaries/test_momentum_canary.py`.

## Files modified (orchestrator-authorised interface extension)
`src/quantlab/data/pit.py`: added `_fundamentals_effective_asof()` and gave
`fundamentals()` a keyword-only `filing_lag_sessions: int = 0`. RESTRICT-ONLY
argument for the quant gate: default 0 reduces to `_last_session_on_or_before(asof)`
(identical to the pre-M03 gate for a session `asof`, strictly narrower -
never wider - for a non-session `asof`); a positive value steps the gate
BACK via `prev_trading_day` (strict-for-sessions, correct once snapped to a
session per QUANT-NOTES M00), only ever shrinking `filed <= effective_asof`
visibility, never growing it; negative values raise `ValueError` at the
point of use (not just via pydantic upstream), making look-ahead via this
param structurally impossible. No other accessor changed; `prices()`
untouched. `strategies/value.py` forwards its own `filing_lag_sessions`;
`strategies/base.py` notes this as the sole exception to "don't extend
PITDataContext." `DataRequirements` untouched — the lag is a per-call
restriction the context validates directly, not a declared data footprint.

## Design decisions / deviations
- **Momentum**: one `MomentumStrategy` class, `book` param picks
  long_only/long_short/130_30 (fixed net/gross per book). Daily
  `ctx.prices()` → month-end wide panel via new adapter `_month_end_prices`
  (groups by calendar month, last `close`); ported signal functions untouched.
  `price_lookback_days = 23 * (lookback_months+skip_months+3)`.
- **Value**: `compute_value_ratios` ported verbatim except its input type —
  a local `_PointInTimeFundamentals` dataclass built from `ctx.fundamentals()`.
  Market cap prices off `raw_close` on the single most-recent row
  (`ctx.prices(t,1)`) per M02b VERDICT.md carried item 1.
- **Blend**: N-way generalization of `combine_strategies`' `w`/`(1-w)`
  formula applied to weight dicts; weights validated to sum to 1.0.
  `requires()` unions children's `DataRequirements`.
- Parity tests use hard-coded golden numbers, not a sys.path import of the
  old repo — documented as the more robust choice in the test file.

## Tests / lint
`uv run pytest tests/ -q`: exit 0, 213 dots, no red. `ruff check .`: all
checks passed. `ruff format --check .`: 51 files already formatted.

## Mutation checks
1. Momentum canary: switched `_month_end_prices` to key off `raw_close`;
   failed with score -0.9 (the M02-verdict split hazard) instead of ~0.
   Reverted; green again.
2. Filing-lag canary (g, tests/canaries/test_lookahead.py): switched
   `_fundamentals_effective_asof`'s stepping from `prev_trading_day` to
   `next_trading_day`; failed — all four lags (0-3) kept returning the
   freshest (300.0) filing instead of narrowing 300→200→100→None. Reverted;
   green again.

## Open questions
None blocking. The filing-lag escalation from the prior iteration is
resolved (see above); no other PITDataContext gaps found.
