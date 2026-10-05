# M10 — Attribution: where do the three real return series come from?

Goal: Explain the committed momentum_12_1, value_composite and blend_50_50 results by
mechanism — market beta, factor loadings, alpha after beta, concentration — using ONLY the
return series the M09 runs already produced. No strategy changes, no new backtests, no new
trials: the trials registry must not be touched. The output is an `attribution.json` +
`attribution.md` per strategy (committed), a README "Attribution" section with one table,
and a handoff that answers in plain English: after controlling for beta and the standard
factors, is there any alpha here at conventional significance, and how much of the
~3 pp/yr CAGR excess over SPY is leverage on beta?

Motivation (orchestrator, 2026-10-02): all three strategies are REJECTED mainly on
"net Sharpe < SPY". With betas of 1.13–1.19 in a 2012–2026 bull market, a back-of-envelope
CAPM adjustment leaves roughly +1 pp (momentum), ~0 (value) and <+1 pp (blend) of excess
return — i.e. the outperformance may be mostly beta. The platform tests whether a rule made
money honestly; it does not yet say where the money came from. This milestone adds that.
It informs Alex's Norgate decision; it does NOT change any gate.

## In scope
- `src/quantlab/attribution/factors.py`: a `FactorProvider` interface + Ken French data
  library implementation (monthly US: Fama-French 5 factors `Mkt-RF, SMB, HML, RMW, CMA`,
  the momentum factor `Mom`/UMD, and `RF`), downloaded as the library's zipped CSVs,
  parsed, cached under `data/cache/factors/` with a `fetched_at` sidecar (factor data are
  revised by the library; record the vintage). Percent units in the files → decimal.
  Network only in the provider; everything else reads the cache. Offline fixture: a small
  hand-made monthly factor file under tests/fixtures/.
- `src/quantlab/attribution/regression.py`: OLS of monthly excess returns on (a) `Mkt-RF`
  (CAPM) and (b) FF5 + Mom, with Newey-West HAC standard errors (lag choice documented,
  default 6 for monthly data; state the rule). Report alpha (annualised, both as monthly
  intercept ×12 and geometric), t-stats, loadings, R², N, the sample window and the number
  of months dropped by alignment. Rolling 36-month CAPM beta series. Use statsmodels if it
  is already a dependency or can be added cheaply; otherwise closed-form OLS + HAC — either
  way a worked-example test against known coefficients.
- `src/quantlab/attribution/decompose.py`: active-return decomposition vs the embedded
  benchmark: strategy CAGR − SPY CAGR split into (beta − 1) × (SPY − RF) [leverage on
  beta], alpha, and residual/compounding; plus an INFORMATIONAL "beta-matched SPY" line —
  the Sharpe of SPY levered to the strategy's beta is the same as SPY's, so state the
  comparison in alpha / information-ratio terms and say explicitly that the existing
  `net_sharpe_vs_benchmark` gate penalises beta and concentration. Concentration:
  average and worst-month idiosyncratic share of variance (1 − R²) and the effective
  number of holdings from `holdings_history.json` (1/Σw²) — the latter only if the file is
  present; it is not committed.
- Sector exposure: ONLY if a free, point-in-time-safe sector mapping is already available
  through the constituents provider. It is not today — so state "sector exposure not
  available" in the output rather than pulling a new data source. Do not add a dependency
  for it.
- CLI `quantlab attribute --result <run dir> [--factors cached|refresh] --out <dir>`:
  writes `attribution.json` + `attribution.md`. Exit code 0 always (informational). Also
  run it on the embedded SPY series as a calibration (expect beta ≈ 1, alpha ≈ 0 against
  `Mkt-RF`; report the actual numbers and explain any gap — SPY vs the CRSP value-weighted
  market, expense ratio, RF).
- Reporting: `quantlab report` gains an "Attribution" section if `attribution.json` is
  present in the run dir (read-only; nothing in the card changes). README gets an
  "Attribution" section: one table (beta, FF5+Mom alpha with t-stat, Mkt/SMB/HML/RMW/CMA/Mom
  loadings, R², IR) for the three strategies + SPY calibration row, and three sentences of
  interpretation that make no claim the t-stats do not support.
- `reports/<strategy>/attribution.json|md` for the three real runs are committed (small);
  `.gitignore` whitelist updated. The factor cache is NOT committed (ignored) but its
  vintage (`fetched_at`, library file dates) is recorded in each attribution.json.
- Carried from the M09 verdict (plans/QUANT-NOTES.md "M09 gate cycle 2 — ACCEPT"), fold in:
  - **C1 (medium):** record the fundamentals cache vintage per run (fetched-at min/max over
    the tickers touched) in backtest provenance and add it to `netted_grid._VINTAGE_KEYS`.
    This touches `backtest/` provenance only — additive field, no numerics; test it.
  - **C3 (low):** README wording "the only window in which the 36 contaminated series could
    matter" → "the only window where removing them changed the series".
  - **C2 (low):** docs/paper-trading.md: an ex-dividend date between the decision close and
    the fill-session open lands in `timing_gap_bps`.
  - **C4 (medium, pre-promotion):** `paper run_once` re-checks the CURRENT cache's scan
    coverage (unscanned cached tickers must be 0 now, not only when the card was validated)
    before placing orders; refuse otherwise; test with a planted unscanned ticker.
- tests: test_factors.py (offline parse + cache + fetched_at; `@pytest.mark.network` for one
  real download), test_regression.py (worked example with planted loadings and HAC vs a
  reference; alignment drops counted), test_decompose.py (identity: the three components
  sum to the excess CAGR within tolerance; beta-matched line), test_cli_attribute.py
  (fixture run dir end-to-end), carried-item tests.

## Out of scope
Any change to strategies, backtest numerics, validation gates or thresholds; any new
backtest or sensitivity run; sector data acquisition; a beta-adjusted promotion gate (that is
Alex's call after seeing these numbers — put the recommendation and its evidence in the
handoff, not in configs/validation.yaml); Norgate; re-centring momentum's grid.

## Context (read these, nothing else)
- This packet; CLAUDE.md; plans/QUANT-NOTES.md ("M09 gate cycle 2 — ACCEPT" block);
  plans/state/M09/HANDOFF.3.md (what the real runs are and where their series live)
- src/quantlab/validation/metrics.py (sharpe_ratio, beta, information_ratio, tracking_error,
  cagr — reuse, do not re-implement); src/quantlab/validation/report_card.py (card
  provenance fields, for C1); src/quantlab/validation/netted_grid.py (`_VINTAGE_KEYS`);
  src/quantlab/backtest/engine.py (provenance assembly only, for C1);
  src/quantlab/reporting/{context.py,render.py} + templates (for the new section);
  src/quantlab/paper/runner.py (`run_once`, for C4); src/quantlab/data/cache.py (sidecar
  conventions, scan manifest readers); src/quantlab/cli.py; configs/platform.yaml
- The run dirs: reports/momentum_12_1, reports/value_composite, reports/blend_50_50
  (`net_returns.parquet`, `benchmark_returns.parquet` — monthly, 173 periods 2012–2026;
  `holdings_history.json` where present). READ ONLY. Never run backtest/validate/run
  against them.

## Interfaces to honor
- Monthly periodicity, `MONTHS_PER_YEAR` from metrics.py; `sharpe_ratio(rf=0, ppy)` as the
  platform convention — the regressions use excess returns over the library's RF and must
  say so beside any Sharpe they quote.
- Provenance is additive: no existing key renamed or removed.
- `quantlab attribute` must refuse a run dir whose `provenance.json` is missing (it is
  git-ignored but present locally for the three real runs).

## Acceptance criteria
1. `uv run pytest` green offline (default tier under the 90 s budget on AC); ruff clean;
   `-m network` factor download passes once (record the library file dates).
2. `quantlab attribute` run on the three real dirs + the SPY calibration; the four
   `attribution.json|md` committed; every README table number traceable to them.
3. Worked-example tests: planted loadings recovered to 1e-10 (no HAC) and HAC SEs match a
   reference implementation to 1e-8; decomposition identity holds; alignment drop counts
   exact.
4. SPY calibration: CAPM beta within 0.05 of 1 and |alpha| < 1 pp/yr, or the gap explained.
5. C1–C4 closed with tests (C2/C3 are doc edits).
6. Handoff: the attribution table; a plain-English answer to "is there alpha after beta,
   at what t-stat"; how many pp of each strategy's CAGR excess over SPY is beta leverage;
   what the numbers imply for the Norgate decision (does better data plausibly change the
   answer, and which number would move); a recommendation on whether a beta-adjusted or
   IR-based gate should be proposed to Alex — with its risks (lowering the bar after
   seeing the results is exactly the kind of post-hoc change the platform exists to stop,
   so any such gate must be argued from first principles and applied prospectively).

## Verification commands
- `uv run pytest tests/ -q`; `uv run ruff check`; `uv run ruff format --check`
- `uv run pytest -m network tests/test_factors.py -q`
- `uv run quantlab attribute --result reports/momentum_12_1 --out reports/momentum_12_1`
  (and value_composite, blend_50_50); `uv run quantlab report --result reports/momentum_12_1
  --out reports/momentum_12_1` renders the new section with `git diff` showing only that
  section changed.

## Parity fixtures
None ported. Reference values for the HAC test may be generated once with statsmodels and
pinned in the fixture with the generating script committed under tests/fixtures/.
