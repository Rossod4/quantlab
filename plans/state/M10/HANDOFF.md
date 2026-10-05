# M10 HANDOFF (iteration 1) - developer

Not committed. Branch m10-attribution. No backtest/validate/run executed; trials registry untouched; the only files written into `reports/` are `attribution.json|md` (3 runs + new `reports/spy_calibration/`) and the re-rendered `report.md` (+ ignored `report.html`).

## Files
New: `src/quantlab/attribution/{__init__,factors,regression,decompose,build}.py`; tests `test_factors.py`, `test_regression.py`, `test_decompose.py`, `test_cli_attribute.py`; `tests/fixtures/factors/{ff5,mom}_sample.csv`, `tests/fixtures/gen_hac_reference.py` + `hac_reference.json` (statsmodels 0.15.0, run with `uv run --with`; not a dependency).
Changed: `cli.py` (`attribute`), `reporting/{context,render}.py` + both templates (Attribution section, only when `attribution.json` exists), `backtest/{context,engine}.py` + `validation/netted_grid.py` (C1), `paper/runner.py` (C4), README, docs/paper-trading.md (C2), `.gitignore` whitelist, tests/test_engine.py + test_runner.py (carried-item tests).

## Attribution table (monthly, 2012-02..2026-06, N=173, 0 months dropped; Ken French CRSP-202608 files, fetched 2026-10-05; cells loading (t, HAC 6 lags))
| | CAPM beta | FF5+Mom alpha %/yr (t) | Mkt-RF | SMB | HML | RMW | CMA | Mom | R-sq | IR vs SPY |
|---|---|---|---|---|---|---|---|---|---|---|
| Momentum | 1.10 | -1.19 (-0.62) | 1.20 (33.5) | 0.07 (0.9) | 0.11 (1.2) | -0.27 (-2.6) | -0.01 (-0.1) | 0.46 (6.2) | 0.85 | 0.33 |
| Value | 1.16 | +2.19 (+1.38) | 1.09 (24.5) | 0.16 (2.4) | 0.32 (4.1) | 0.28 (3.6) | -0.08 (-1.0) | -0.16 (-2.2) | 0.90 | 0.33 |
| Blend | 1.13 | +0.50 (+0.38) | 1.15 (48.8) | 0.11 (2.3) | 0.21 (3.2) | 0.00 (0.0) | -0.05 (-0.5) | 0.15 (2.7) | 0.92 | 0.48 |
| SPY calib. | 0.96 | -0.11 (-0.53) | 0.99 (126) | -0.11 (-11.9) | 0.02 (1.7) | 0.06 (3.1) | 0.02 (1.4) | 0.00 (0.4) | 1.00 | n/a |
CAPM alpha %/yr (t): momentum +1.84 (0.67), value +0.72 (0.32), blend +1.29 (0.70), SPY +0.50 (1.25).

## Excess CAGR over SPY (pp/yr; SPY premium over RF 13.29%/yr; beta here is vs SPY)
| | beta vs SPY | excess | beta leverage | alpha | compounding | vs beta-matched SPY CAGR | appraisal ratio |
|---|---|---|---|---|---|---|---|
| Momentum | 1.130 | 2.85 | 1.72 | 1.45 | -0.33 | +1.19 | 0.155 |
| Value | 1.192 | 2.38 | 2.55 | 0.32 | -0.49 | -0.07 | 0.038 |
| Blend | 1.161 | 2.86 | 2.14 | 0.89 | -0.16 | +0.81 | 0.150 |
Identity holds to 1e-16. Excess Sharpe over RF: strategies 0.89/0.86/0.94 vs SPY 0.946 (levered SPY has SPY's Sharpe exactly).

## Plain-English answers (criterion 6)
1. Alpha after beta and factors? No strategy shows one at any conventional level: FF5+Mom t = -0.62 / +1.38 / +0.38; CAPM t = 0.67 / 0.32 / 0.70; 95% intervals (FF5+Mom, %/yr) -5.0..+2.6, -0.9..+5.3, -2.1..+3.1. Lag choice (0/4/6/12) never moves an alpha t-stat above 1.6. The data cannot distinguish skill from zero; alpha SE is ~2.5%/yr (idio vol ~9% over 14 y), so only a >5 pp alpha is detectable. For momentum, controlling for Mom removes the strategy's own premium by construction: its relevant number is the CAPM +1.84% (t 0.67).
2. Beta leverage in the ~3 pp: momentum 1.7 of 2.85 pp, value 2.6 of 2.4 (all of it, plus), blend 2.1 of 2.9. Against SPY levered to the same beta: +1.2, -0.1, +0.8 pp, none significant.
3. Norgate: better data cannot fix the power problem (alpha SE is set by sample length and idio vol, not data quality), so it will not turn these into significant alpha. It can move the POINT estimates: the 168 no-data + 36 quarantined names are mostly delisted/corrupt, so correcting them more likely lowers returns/alpha than raises it, and it is the only route to the failing 28.4% coverage-bound gate. Numbers that would move: coverage bound, net CAGR, alpha. The t-stats would not.
4. Gate recommendation: do NOT lower the Sharpe-vs-SPY bar; every beta-adjusted variant here would be a post-hoc softening after seeing +1/0/+0.8 pp. If Alex wants one, argue it prospectively from first principles: an FF5(+Mom where the rule is not momentum) alpha gate needs t >= 2 on the alpha, which all three FAIL, so it is stricter, not looser, and applies only to trials registered after this decision with thresholds fixed now. Risks: low power (most honest candidates fail or read "cannot tell"), factor-choice degrees of freedom, and the momentum-vs-Mom circularity above. Keep attribution informational on the card until then.

## Carried items
C1: `provenance.fundamentals_cache_fetched_at {min,max,basis}` (file-mtime date over the run's coverage tickers, only when the run called the fundamentals provider; no sidecar exists); added to `_VINTAGE_KEYS`. Committed runs lack it (None on both sides compares equal; old-vs-new would be disclosed, not refused). C2, C3: doc edits. C4: `run_once` refuses (journaled, `PromotionGateError`) when any cached price parquet is absent from the CURRENT scan manifest; skipped under `--force-research`; tests with a planted unscanned ticker.

## Deviations / decisions
- Exit code: 0 on success; refusals (no provenance.json, non-month_end run, factors not cached) exit 1 (packet's "0 always" read as "never encodes a verdict").
- SPY calibration via extra `--series benchmark` option, output `reports/spy_calibration/` (whitelisted). Result: beta 0.96 (within 0.05 of 1), alpha +0.50%/yr (<1 pp), t 1.25; gap = S&P 500 vs CRSP all-market (SMB -0.11), 0.09% expense ratio, RF/dividend conventions; SPY minus library market -0.03%/yr, correlation 0.994.
- No statsmodels dependency: closed-form OLS + Bartlett HAC; matches statsmodels to 1e-8 (lags 0/4/6/12) and a loop implementation to 1e-12; planted loadings to 1e-10. Lag rule documented in regression.py (6 fixed; NW plug-in would be 4).
- "Worst-month idiosyncratic share" implemented as worst trailing-36-month window (1-R2) plus the single largest residual month and its share of squared residuals.
- Factor download made twice (CLI `--factors refresh` filled `data/cache/factors/`; the `-m network` test downloads into a tmp dir so a test never alters the cache the committed vintage refers to). Both returned Last-Modified 2026-09-25, "created using the 202608 CRSP database".
- `quantlab report` on the three real dirs: `git diff` shows only the +37-line Attribution section in each `report.md`; PNGs byte-identical.
- Sector exposure: stated "not available" in every output; no dependency added.

## Verification
`uv run pytest` (default tier): 981 passed, 102 deselected, 138-154 s on BATTERY (BatteryStatus 1, 75%, 1.4 GHz) with other agents running concurrently: over the 90 s AC budget and NOT an AC-quiet figure; M10's 63 new tests take 10 s total, slowest existing test 2.9 s. `-m slow` attribution render test passed. `uv run pytest -m network tests/test_factors.py`: 1 passed. ruff check + format --check clean.
Open: none blocking. Suggest Alex sees item 4 above before any gate discussion.
