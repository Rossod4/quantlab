# M06 handoff, iteration 2 (code review REVISE -> fixed)

## Per-item status

**Blocker (footing mismatch) - FIXED.** `build_report_card` was feeding
`MetricsSummary.net_sharpe` (ANNUALIZED) into PSR/DSR/`min_track_record_
length` alongside a raw period `n` and per-period skew/kurt. Now computes
`sr_per_period` via a new `metrics.raw_sharpe(returns)` (mean/std(ddof=1),
no annualization) and passes THAT into all three formulas; `m.net_sharpe`
is kept only for gate-reason display, printed side by side with the
per-period value in every DSR/PSR/MinTRL gate reason. MinTRL's benchmark
side uses a matching per-period benchmark Sharpe. Cascaded into
`registry.py`: `TrialRecord` gained `net_sharpe_per_period`
(`record_backtest` via `raw_sharpe`; `record_sensitivity` via the supplied
return series when available, else the EXACT algebraic inverse
`trial.net_sharpe / sqrt(periods_per_year)` when a caller passes
`periods_per_year`, else NaN); `var_sr_trials()` now reads that field, not
the annualized one. The five historical entries get `net_sharpe_per_period
= net_sharpe / sqrt(4)` (still NaN today - no real number exists - but
documents the quarterly Phase-3-sweep conversion for if one ever is added).

**Minor (moments convention) - FIXED.** skew/kurt now use
`scipy.stats.skew(bias=True)` / `kurtosis(fisher=False, bias=True)` (plain
method-of-moments), not pandas' bias-corrected G1/G2. `test_report_card.py`'s
module docstring updated: an exactly-alternating equal-count series now has
skew=0, kurt=1 EXACTLY at any n (previously ~0.93 under pandas' correction,
as the review found) - this also removes the "Sharpe must stay below ~7.5
or variance_factor goes negative" constraint entirely, since kurt=1 exactly
makes `variance_factor` exactly 1 regardless of Sharpe magnitude.

## Regression tests added
- `test_dsr_footing_bug_regression_reviewers_exact_numbers`
  (test_deflated_sharpe.py): `np.random.default_rng(1).normal(0.006, 0.045,
  48)` reproduces the reviewer's own hand check almost exactly - correct
  (per-period) DSR=0.0289, buggy (annualized, same n) DSR=0.2559 - pinned to
  1e-3 against their stated 0.029/0.256 (found by search over seeds; matches
  both figures simultaneously).
- `test_psr_is_invariant_to_the_periods_per_year_label` (test_report_card.py):
  the SAME return series labelled `month_end` vs `quarter_end` gives
  IDENTICAL `report_card.psr` (PSR takes no periods_per_year argument at
  all) while the two annualized `net_sharpe` values differ - proving the
  check isn't vacuous and that PSR no longer secretly depends on the
  frequency label the old bug introduced.

## Files touched this iteration
`validation/metrics.py` (+`raw_sharpe`), `validation/report_card.py`
(per-period sr/skew/kurt wiring, gate reasons, module docstring),
`validation/registry.py` (`net_sharpe_per_period`, `var_sr_trials`, historical
quarterly-conversion note), `tests/test_deflated_sharpe.py`,
`tests/test_report_card.py`, `tests/test_trials_registry.py` (one test fixed
to check the per-period field `var_sr_trials()` now actually reads).

## Tests
`uv run pytest tests/ -q`: **exit 0, 508 dots, ~12s** (well under 90s).
`uv run ruff check`: clean. `uv run ruff format --check`: clean (97 files).

## Open questions
None new. Iteration 1's still-open items stand unchanged (base-point double
counting, RC/SPA/capacity hard-fail-on-missing, walk-forward NaN check).
