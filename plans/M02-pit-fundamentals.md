# M02 — PIT context, EDGAR fundamentals, survivorship measurement, corporate actions

Goal: Build the anti-look-ahead core: `PITDataContext` (the ONLY object strategies will
ever see), the ported SEC EDGAR filed-date-gated fundamentals provider, the survivorship
coverage-gap measurement, and corporate-actions/delisting inference.

## In scope (create these)
- src/quantlab/data/pit.py — `PITDataContext`:
  - Constructed with `asof: Timestamp`, the providers/caches, and a `DataRequirements`
    declaration (define the dataclass here or in a small requirements.py; M03's
    Strategy ABC will re-export it): price lookback days, fundamental fields needed,
    whether universe membership is needed.
  - Methods: `prices(tickers, lookback_days) -> DataFrame` (rows hard-sliced to
    `<= asof`), `fundamentals(ticker) -> dict`. Error semantics: temporal violations
    raise `LookaheadError`; access beyond the declared DataRequirements (undeclared
    fields, more lookback than declared) raises `UndeclaredDataError` (add to
    core/errors.py).
    (only figures with SEC `filed <= asof`), `universe() -> list[str]` (constituents
    as-of), `actions(ticker) -> DataFrame` (events with effective date `<= asof`).
  - Any internal frame handed out must be a copy or read-only view — callers must not
    be able to mutate the cache (M00 gate note: shallow-frozen models; defensively copy).
  - Per plans/QUANT-NOTES.md: adj_close must NOT be exposed for decisions. Expose
    as-of-consistent prices: raw close plus split/dividend adjustment computed only
    from actions with ex-date <= asof. If the ported price cache only stores yfinance
    auto-adjusted series, document the limitation precisely in the handoff and expose
    it as `prices_for_returns()` vs `prices()` — do not silently feed contaminated
    adjustment into signals. THIS IS THE CENTRAL DESIGN DECISION OF THE MILESTONE —
    reason it through explicitly in the handoff.
- src/quantlab/data/providers/edgar_fundamentals.py — port the old fundamentals module
  wholesale (CIK map, companyfacts caching, filed-date gating, TTM/growth/total-debt
  extraction, freshest-tag-wins) behind `FundamentalsProvider`. Do not change its
  numerical/gating logic.
- src/quantlab/data/survivorship.py — port scripts/coverage_gap_analysis.py as a
  library: `coverage_gap(universe_history, price_availability, start, end) ->
  CoverageReport` (per-year % of point-in-time constituents lacking price data +
  overall bound). Pure function of inputs, offline-testable.
- src/quantlab/data/corporate_actions.py — `CorporateActionsProvider` implementation:
  dividends/splits from the cached yfinance actions; delisting inference (ticker's last
  cached bar precedes requested end AND ticker left the constituents set ⇒
  `DelistingEvent(last_trade_date, reason=UNKNOWN)`; ACQUISITION/BANKRUPTCY left for a
  richer source later — document).
- tests/test_pit.py, tests/test_edgar_fundamentals.py (adapt old test_fundamentals.py),
  tests/test_survivorship.py, tests/test_corporate_actions.py
- tests/canaries/__init__.py + tests/canaries/test_lookahead.py — standing adversarial
  tests: (a) fixture panel containing a future-dated price row → context.prices() must
  exclude it; (b) fundamentals fixture with a filing filed AFTER asof but period BEFORE
  asof → must be excluded; (c) universe() on a date between membership rows → earlier
  row only; (d) mutating a returned frame does not alter what a fresh call returns;
  (e) per QUANT-NOTES M01: signal-visible price access must not carry adj_close (the
  canary asserts the column is absent/inaccessible from the decision-path API).
- Per QUANT-NOTES M01: survivorship.py must also surface cache-metadata-masked ranges
  (ticker has a "known empty range" but the constituents say it was still a member) in
  the CoverageReport, so frozen truncations show up as coverage loss, not silence.

## Out of scope
Strategy ABC (M03), backtest engine (M04). No changes to M01 provider logic beyond
what interfaces require (justify any touch in handoff).

## Context (read these, nothing else)
- This packet; CLAUDE.md; plans/QUANT-NOTES.md
- Existing quantlab files: src/quantlab/core/{types,errors,config,calendar}.py,
  src/quantlab/data/interfaces.py, cache.py, quality.py, providers/*.py (as merged
  from M01), tests/fixtures/*
- Port sources (read-only):
  - ...\MomentumValueStrategy\src\data_layer\fundamentals.py
  - ...\MomentumValueStrategy\tests\test_fundamentals.py
  - ...\MomentumValueStrategy\scripts\coverage_gap_analysis.py
  (root: C:\Users\arwga\Developer\ClaudeProjects\Trading\MomentumValueStrategy)
- pandas 3.x / numpy 2.x environment — mechanical API updates allowed, list each in
  handoff.

## Acceptance criteria
1. `uv run pytest` green offline; `uv run ruff check` clean.
2. All four canary tests trip their guards (they FAIL if the guard is removed — verify
   by asserting on the guard behavior, not on absence of data).
3. Fundamentals parity: ported extraction on the old repo's cached companyfacts fixture
   (commit one real ticker's JSON, e.g. a small filer) matches the old module's output
   for the same asof — same fields, same values.
4. Survivorship: coverage_gap on a synthetic fixture (10 tickers, 3 without prices)
   reports 30% for that year; empty gap reports 0.
5. Delisting inference fixture: ticker with last bar 2020-06-12 in a request through
   2020-12-31 that also left the index → DelistingEvent with last_trade_date
   2020-06-12.
6. PITDataContext refuses undeclared data (UndeclaredDataError) and future data
   (LookaheadError), and prices(...) with lookback N returns at most N sessions ending
   at the last session <= asof.

## Verification commands
- `uv run pytest tests/ -q`; `uv run ruff check`

## Parity fixtures
One real companyfacts JSON snapshot (small) in tests/fixtures/edgar/; expected
extraction values computed by the OLD module offline and hard-coded into the test with
a comment stating provenance.
