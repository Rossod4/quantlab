# M03b — Per-share fundamentals in as-of share terms + canonical blend id (gate-mandated)

Goal: Close the M03 verdict's MATERIAL finding: per-share SEC figures (shares
outstanding, TTM EPS) filed BEFORE a split are paired with a post-split price at asof,
so P/E and market cap are off by the full split ratio and the value book is biased
toward buying recent winners. Restate per-share figures into asof share terms using
only splits with `filed < ex_date <= asof`. Also canonicalise the blend `strategy_id`
so the M06 trials registry can recognise a repeat blend.

## Why (filed, asof] and not (period_end, asof]
Under ASC 260 a filer retroactively restates EPS and share counts for splits that
occur before the financial statements are issued, so a split between period end and
filing date is already reflected in the filed figure. Only splits AFTER the filing
date leave the figure in stale share terms. Document this provenance in code.

## In scope
- src/quantlab/data/providers/edgar_fundamentals.py — ADDITIVE provenance only:
  `PointInTimeFundamentals` gains `shares_outstanding_filed: Timestamp | None` and
  `ttm_eps_filed: Timestamp | None` (the `filed` date of the instant fact used for
  shares; for TTM EPS the LATEST `filed` among the component quarters/annual figure
  actually summed — restated comparatives in later filings already win the dedup, so
  the latest component filing is the date after which no component has been restated).
  The extraction helpers may return the filed date alongside the value, but every
  numerical result must stay byte-identical (M02 parity fixtures untouched; the NATH
  parity test must still pass). `get_pit_fundamentals()` dict gains the two keys.
- src/quantlab/data/pit.py — `fundamentals()` restates to asof share terms: for each
  per-share field with a filed date, factor = Π split ratios for actions with
  `filed < ex_date <= asof` (from the same gated actions path `prices()` uses — reuse
  `_gated_actions_by_ticker`, never a raw provider call); `shares_outstanding *= factor`,
  `ttm_eps /= factor`. Return two extra keys: `share_terms_split_factor` (1.0 when no
  split) and `share_terms_asof` (= asof). Fields not declared in DataRequirements are
  still filtered out; the two provenance keys are returned only if
  `shares_outstanding` or `ttm_eps` is declared. Non-per-share totals (equity, debt,
  cash, EBITDA) are untouched; `annual_eps_growth` is a ratio and untouched — say so.
  The split window uses asof, NOT the lagged effective_asof (the lag governs filing
  visibility; the split is a market event known on its ex-date).
- src/quantlab/strategies/value.py — no numerical change; declare nothing new. Update
  the docstring's price-level rule to say the context now delivers as-of share terms.
- src/quantlab/strategies/blend.py — `strategy_id` becomes an order-insensitive hash of
  `sorted((child.strategy_id, weight))` pairs plus the blend's own params; document.
- tests/test_pit.py (or a new tests/test_share_terms.py): the gate's fixture — a 4:1
  split 30 sessions after the filing, asof after the split: P/E must read 25.0 (not
  6.25) and P/B 1.667 (not 0.417) through `compute_value_ratios` on the context's
  output; no split → identical to current output; split BEFORE the filing → factor
  1.0; two splits after filing compose; a split ex-dated after asof has zero effect
  (also add as canary (h) in tests/canaries/test_lookahead.py with a hostile actions
  provider returning it, byte-identical fundamentals with and without it; mutation-
  check by widening the window to `<= asof + 1 session`).
- tests/test_value_strategy.py: end-to-end `generate_targets` on the gate's
  split-spanning fixture — the split name must land at its TRUE composite rank, not the
  best rank. tests/test_blend.py: child-order swap and omitted-default-param cases give
  the SAME id; changing a weight or a child param changes it.
- tests/parity/: existing M02 fundamentals parity and M03 signal parity must pass
  unchanged (fixtures have no post-filing splits — state this explicitly).

## Out of scope
Engine (M04). Dividends do not change share terms — no dividend handling here.

## Context (read these, nothing else)
- This packet; plans/state/M03/VERDICT.md (the MATERIAL finding and the M06 blend-id
  item); plans/QUANT-NOTES.md "From M03 verdict"; CLAUDE.md
- Existing quantlab: src/quantlab/data/pit.py, src/quantlab/data/adjustment.py (for the
  gated actions frame shape), src/quantlab/data/providers/edgar_fundamentals.py,
  src/quantlab/data/requirements.py, src/quantlab/strategies/{value,blend,base}.py,
  tests/test_value_strategy.py, tests/test_blend.py, tests/canaries/test_lookahead.py

## Interfaces to honor
`PITDataContext.fundamentals(ticker, *, filing_lag_sessions=0)` signature unchanged;
return dict is additive only. `Strategy` ABC unchanged. Ported EDGAR numerics frozen.

## Acceptance criteria
1. `uv run pytest` green offline; `ruff check` and `ruff format --check` clean.
2. Gate fixture: P/E 25.0 and P/B 1.667 to 1e-9 after a 4:1 split filed-then-split.
3. No-split output byte-identical to pre-M03b (parity fixtures unchanged).
4. Canary (h) passes and fails under the widened-window mutation (state result).
5. Blend id order-insensitive and default-insensitive; weight/param-sensitive.
6. Handoff states the filed-date convention argument (ASC 260) in two sentences.

## Verification commands
- `uv run pytest tests/ -q`; `uv run ruff check`; `uv run ruff format --check`
