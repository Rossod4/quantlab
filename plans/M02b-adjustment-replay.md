# M02b — As-of adjustment replay (gate-mandated, blocks M03)

Goal: Give PITDataContext a decision-safe adjusted price series: raw close × cumulative
adjustment factor computed ONLY from corporate-action events with ex-date <= asof,
applied backward. This is the binding condition from the M02 quant-gate verdict —
read plans/state/M02/VERDICT.md's "central question" section and implement exactly the
semantics it prescribes. After this milestone, strategies can compute cross-time price
signals with zero look-ahead AND zero split distortion.

## In scope
- src/quantlab/data/adjustment.py — pure function(s):
  `adjustment_factors(actions: DataFrame, asof) -> Series[date -> factor]` and
  `apply_asof_adjustment(raw_close: DataFrame, actions_by_ticker, asof) -> DataFrame`.
  Standard convention: factor for a split S effective ex-date d divides prices before
  d by S; dividend factor (1 - div/close_prev_ex) multiplicative — document the exact
  formula and its provenance (CRSP-style). Deterministic, offline, no provider access.
- src/quantlab/data/pit.py — wire it in: `prices()` returns as-of-adjusted close
  (plus raw close under an explicit raw_close column); docstring states the contract.
  `prices_for_returns()` unchanged (accounting only).
- tests/test_adjustment.py — hand-computed fixtures:
  - NVDA 10:1 split ex 2024-06-10: price 1210.0 on 2024-06-07 → adjusted 121.0 when
    asof >= ex-date; UNADJUSTED (1210.0) when asof = 2024-06-07 (the replay must not
    know the future split).
  - AAPL 4:1 split ex 2020-08-31 analogous.
  - A cash dividend case with hand-computed factor.
  - Split + dividend composition ordering test.
- tests/canaries/test_lookahead.py — extend: (f) an action with ex-date AFTER asof
  must have zero effect on prices() output (adversarial: hostile provider returns a
  future split; assert byte-identical panel with and without it); this closes the
  actions-canary gap named in the M02 verdict.

## Out of scope
Strategy code (M03), OHLC-column adjustment beyond close (document as limitation if
skipped), backtest engine.

## Context (read these, nothing else)
- This packet; plans/state/M02/VERDICT.md (the binding spec); plans/QUANT-NOTES.md;
  CLAUDE.md
- Existing quantlab: src/quantlab/data/pit.py, corporate_actions.py, requirements.py,
  core/errors.py, tests/canaries/test_lookahead.py

## Interfaces to honor
PITDataContext public API — extend semantics of prices() as specified but do not
break existing signatures/tests except where the VERDICT demands different behavior
(list every intentional test change in the handoff).

## Acceptance criteria
1. `uv run pytest` green; `uv run ruff check` clean.
2. All hand-computed parity fixtures above pass to 1e-12.
3. Canary (f) passes and fails if the ex-date gate is removed (mutation-check it
   yourself before handing off; state the result).
4. A 12-month momentum computation on prices() across the NVDA fixture split now
   yields ~0% for a flat-value stock (the M02 verdict's -90% scenario, inverted —
   include this exact regression test).
5. prices() for asof strictly before an ex-date returns the same values whether or
   not the future action exists in the provider.

## Verification commands
- `uv run pytest tests/ -q`; `uv run ruff check`
