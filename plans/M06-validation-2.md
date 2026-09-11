# M06 — Validation II: statistical gates and the report card verdict

Goal: The second half of the validation report card and the platform's decision
function. Add the multiple-testing-aware and resampling-based tests (PSR/DSR, purged
and embargoed CV, White's Reality Check / Hansen's SPA over the trials registry, block
bootstrap Monte Carlo, capacity), compose them with M05's `ValidationBasic` into a
`ReportCard`, and gate the verdict — REJECTED | RESEARCH_ONLY | ELIGIBLE_FOR_PAPER —
from thresholds in configs/validation.yaml. Every statistic has a closed-form or
synthetic-null test proving it is computed correctly, not just that it runs.

## In scope (create these)
- src/quantlab/validation/registry.py — `TrialsRegistry`: append-only JSONL under
  `reports_dir/trials/`, keyed on `(strategy_id, data_semantics_version)` (QUANT-NOTES
  M03b: the id alone does not encode data semantics). Records every backtest run and
  every sensitivity grid point (M05 `SensitivityResult.trials`) with net Sharpe, N
  periods, periods_per_year, and the config hash. `n_trials(family)` counts distinct
  keys in a strategy family (momentum / value / blend, from the registered strategy
  name) — this is the N that DSR and White RC consume. Re-running an identical key does
  NOT increment N (idempotent); a changed param does. Document that the registry is a
  lower bound on trials (it cannot see what a human tried in a notebook) and that the
  old repo's Phase 3 blend sweep (five weights) is pre-loaded as historical trials.
- src/quantlab/validation/deflated_sharpe.py — `probabilistic_sharpe_ratio(sr, sr_bench,
  n, skew, kurt)` and `deflated_sharpe_ratio(sr, n_trials, var_sr_trials, n, skew, kurt)`
  per Bailey & López de Prado (2012/2014): PSR = Φ[(SR − SR*)·√(n−1) / √(1 − γ3·SR +
  (γ4−1)/4·SR²)]; DSR uses SR* = √V[SR]·((1−γ)Φ⁻¹(1−1/N) + γΦ⁻¹(1−1/(N·e))), γ = Euler-
  Mascheroni. Closed-form worked-example tests: (a) the paper's own example values;
  (b) PSR = 0.5 when SR == SR*; (c) DSR decreases monotonically in N; (d) skew/kurt at
  Gaussian values reduce the denominator to 1. Also `min_track_record_length`.
- src/quantlab/validation/purged_cv.py — `purged_kfold_splits(index, n_splits, embargo)`
  (López de Prado ch. 7): contiguous test folds, training rows whose label window
  overlaps the test fold purged, plus an embargo of `embargo` periods after each test
  fold. `cv_sharpe(returns, splits)` reports per-fold out-of-fold Sharpe and the mean.
  Tests: no train index within the purge/embargo of any test index (assert on a
  constructed case); folds partition the index; with embargo=0 and label horizon 1 it
  reduces to plain contiguous K-fold.
- src/quantlab/validation/reality_check.py — White (2000) Reality Check and Hansen
  (2005) SPA over a matrix of trial return series (from the registry's stored net
  return series — the registry must store the series path, not just the Sharpe; add a
  parquet sidecar per trial), using the stationary bootstrap (Politis & Romano,
  expected block length from config) with B resamples, benchmark = SPY or zero.
  Reports p-values for "the best trial beats the benchmark". Tests: on a synthetic null
  (all trials are iid zero-mean noise) the p-value over many seeds is ~Uniform(0,1)
  (KS test p > 0.01, seeded, N=200 sims × B=200 — keep it under 30 s); on a synthetic
  alternative (one trial with a planted mean) the p-value is small; SPA p ≤ RC p on
  the same data (Hansen's studentised statistic is less conservative) — assert
  directionally.
- src/quantlab/validation/monte_carlo.py — `block_bootstrap_paths(returns, n_paths,
  block_len, seed)` (stationary bootstrap, same helper as above) → distribution of
  CAGR, max drawdown, Sharpe; reports the 5th/50th/95th percentiles and the
  probability of a drawdown worse than the observed one. Test: the mean of the
  bootstrapped mean return equals the sample mean to within 3 SE; block_len=1 reduces
  to iid resampling.
- src/quantlab/validation/capacity.py — port the capacity estimate from the old
  scripts/cost_realism_analysis.py (equal-weight slice vs ADV participation bound,
  Corwin-Schultz spread p50/p90) VERBATIM into a function of `BacktestResult` +
  price panel; output the AUM ceiling range and the spread percentiles. Golden test
  against the old repo's numbers on a fixture (reproduce the script on the same
  fixture inside the test).
- src/quantlab/validation/report_card.py — `ReportCard` (frozen, JSON-serialisable):
  `basic: ValidationBasic`, psr, dsr, min_trl, n_trials, cv folds, rc/spa p-values,
  monte carlo percentiles, capacity, `coverage_bound` and `quality_flags` carried from
  the result, `known_caveats` from provenance, the gates evaluated (each: name, value,
  threshold, pass/fail), and `verdict`. `build_report_card(result, benchmark_result,
  registry, config) -> ReportCard`. Verdict logic (all from configs/validation.yaml,
  defaults below; make them config, not code):
  - REJECTED if any hard gate fails: DSR < 0.95, or RC p-value > 0.10, or net Sharpe
    < benchmark Sharpe, or coverage_bound > 15%, or min_trl > available n.
  - ELIGIBLE_FOR_PAPER if all hard gates pass AND all soft gates pass: PSR ≥ 0.95,
    purged-CV mean OOF Sharpe > 0, no_cliff_score ≥ 0.5, MC P(drawdown worse than
    observed) ≤ 0.5, capacity ceiling ≥ 100× intended capital, SPA p ≤ 0.10, walk-
    forward (if present) chosen-weight stability.
  - RESEARCH_ONLY otherwise.
  Every gate result carries a one-sentence plain-English reason for the report.
- configs/validation.yaml — add the M06 thresholds and bootstrap params (B, block
  length, seeds) alongside M05's entries.
- CLI: `quantlab validate --result <dir> --benchmark <dir> --out <dir> --full` runs
  basic + full and writes report_card.json + a markdown summary (M07 does HTML).
- tests/test_registry.py (validation), test_deflated_sharpe.py, test_purged_cv.py,
  test_reality_check.py, test_monte_carlo.py, test_capacity.py, test_report_card.py,
  and tests/parity/test_capacity_parity.py.

## Out of scope
HTML report and plots (M07). Paper trading (M08). Real-data run (M09).

## Context (read these, nothing else)
- This packet; CLAUDE.md; plans/QUANT-NOTES.md (items addressed to M06)
- Existing quantlab: src/quantlab/validation/{basic,metrics,sensitivity,walk_forward}.py
  (as merged from M05 — read the actual dataclasses), src/quantlab/backtest/result.py,
  src/quantlab/core/config.py, configs/validation.yaml, src/quantlab/cli.py
- Port sources (read-only): C:\Users\arwga\Developer\ClaudeProjects\Trading\
  MomentumValueStrategy\scripts\cost_realism_analysis.py (capacity + spread parts),
  REVIEW_PHASE5.md §5 (the numbers), src/evaluation/comparison.py (DEFAULT_SWEEP_WEIGHTS
  for the pre-loaded historical trials).
- References (cite in docstrings, no fetching needed): Bailey & López de Prado, "The
  Deflated Sharpe Ratio" (2014) and "The Sharpe Ratio Efficient Frontier" (2012);
  López de Prado, Advances in Financial Machine Learning ch. 7 & 12; White (2000)
  "A Reality Check for Data Snooping"; Hansen (2005) "A Test for Superior Predictive
  Ability"; Politis & Romano (1994) stationary bootstrap.

## Interfaces to honor
`BacktestResult`, `ValidationBasic`, `SensitivityResult` as merged — read-only. Gate
thresholds live in configs/validation.yaml only; the code reads them, never hard-codes.

## Acceptance criteria
1. `uv run pytest` green offline in under 90 s total; `ruff check` + `format --check` clean.
2. PSR/DSR closed-form tests (a)–(d) pass to 1e-9.
3. Purged CV leakage assertion passes; a deliberately unpurged split is detected by the
   same assertion (negative test).
4. Reality Check synthetic null → KS p > 0.01 against Uniform; planted alternative →
   p < 0.05; SPA ≤ RC directionally.
5. Monte Carlo sanity tests pass; results reproducible under a fixed seed.
6. Capacity parity with the old script on a fixture to 1e-9.
7. Registry idempotence: same key twice → N unchanged; changed param → N+1; semantics
   version change → new key.
8. Report card: three fixture results produce REJECTED, RESEARCH_ONLY and
   ELIGIBLE_FOR_PAPER respectively, with every gate's reason string populated; changing
   a YAML threshold flips a verdict without code change (test edits a temp config).
9. `quantlab validate --full` runs end-to-end on a fixture result directory.

## Verification commands
- `uv run pytest tests/ -q`; `uv run ruff check`; `uv run ruff format --check`
- `uv run quantlab validate --help`

## Carried from the M04 verdict (binding — see plans/QUANT-NOTES.md "From M04 verdict")
1. Registry keys include `quantlab_git_sha` AND a `dirty` flag (from provenance, which
   M04 records as the emptiness of `git status --porcelain`); a dirty-tree trial is
   recorded but flagged, and the report card's provenance section says so.
2. PSR/DSR inputs (skew, kurtosis) are computed on the same net_returns series whose
   right tail may have been truncated by the extreme guard; print the extreme counts
   beside PSR/DSR and, when nonzero, add a gate reason line stating the direction
   (conservative on long books, anti-conservative on short books).
3. The report card's "untrusted fraction" line combines `coverage_bound` with the
   unscored/dropped counts, labelled as two different selection effects.
