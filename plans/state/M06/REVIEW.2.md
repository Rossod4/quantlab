REVIEW: APPROVE

## Findings

Both iteration-1 findings are fixed; no new findings.

1. **[resolved] Footing blocker.** `report_card.py` now computes
   `sr_per_period = raw_sharpe(net_returns)` (new `metrics.raw_sharpe`,
   `mean/std(ddof=1)`, no annualization) and passes it — consistently with
   `n = len(net_returns)` and per-period skew/kurt — into
   `probabilistic_sharpe_ratio`, `deflated_sharpe_ratio`, and
   `min_track_record_length`; `m.net_sharpe` (annualized) is now used only
   for gate-reason display text and the `net_sharpe_vs_benchmark`/
   `min_net_sharpe` gates, which legitimately want the annualized figure.
   Grepped every call site of the three formula functions across
   `report_card.py`, `registry.py`, and `cli.py` — the only calls are
   `report_card.py`'s three, all on `sr_per_period`/`benchmark_sr_per_period`;
   `cli.py` never calls them at all (display-only `m.net_sharpe` in the
   one-liner). Re-ran my own iteration-1 hand check
   (`np.random.default_rng(1).normal(0.006, 0.045, 48)`, `var_sr_trials=0.05`,
   `n_trials=10`) directly against `deflated_sharpe_ratio` in a standalone
   script: per-period DSR=0.028945..., annualized (buggy) DSR=0.255910... —
   matches the developer's cited 0.0289/0.2559 and my own original
   0.029/0.256 to the stated tolerance. The regression test
   (`test_dsr_footing_bug_regression_reviewers_exact_numbers`) and the
   annualization-invariance test (`test_psr_is_invariant_to_the_periods_per_
   year_label`) both pass. Cascaded correctly into `registry.py`:
   `TrialRecord.net_sharpe_per_period` is populated via `raw_sharpe` in
   `record_backtest`, via the exact algebraic inverse
   `trial.net_sharpe / sqrt(periods_per_year)` in `record_sensitivity` when a
   series isn't available (verified this is the exact inverse of
   `sharpe_ratio`'s own `mean*ppy / (std*sqrt(ppy))` construction — dividing
   by `sqrt(ppy)` exactly undoes it), and `var_sr_trials()` now reads
   `net_sharpe_per_period`, not the annualized field.

2. **[resolved] Moments convention.** skew/kurt now use
   `scipy.stats.skew(bias=True)` / `kurtosis(fisher=False, bias=True)` (plain
   method-of-moments), matching the DSR literature's own convention.
   Independently recomputed the 60-point alternating fixture from
   `test_report_card.py`: skew=0 (≈1.27e-16, i.e. exactly 0 to float
   precision) and non-excess kurtosis=0.9999999999999996 — exactly 1.0 to
   float precision, as the updated module docstring now correctly claims.

## Verified this iteration

- Hand-recomputation of the pinned regression numbers: exact match.
- Grep for any remaining annualized-Sharpe leakage into PSR/DSR/MinTRL
  across `report_card.py`/`registry.py`/`cli.py`: none found.
- `var_sr_trials` field source and `record_sensitivity`'s `√periods_per_year`
  inverse: both correct.
- Kurtosis-1 fixture: now exactly 1.0 under the new scipy convention.
- The three verdict fixtures (REJECTED / RESEARCH_ONLY / ELIGIBLE_FOR_PAPER)
  plus the new regression/invariance tests: `uv run pytest
  tests/test_report_card.py tests/test_deflated_sharpe.py
  tests/test_trials_registry.py -v` — 47/47 passed.
- Full suite: `uv run pytest tests/ -q` — exit 0, 508 dots (matches the
  handoff exactly), ~3-12s depending on run. `uv run ruff check` and
  `uv run ruff format --check` both clean.
- `git diff --stat -- src/` shows only `cli.py`/`basic.py` (unchanged from
  iteration 1) plus `metrics.py` (+24 lines, `raw_sharpe`) — consistent with
  the handoff's stated file list; `report_card.py`/`registry.py` are
  untracked new files, edited in place as expected.

No other part of iteration 1's review (PSR/DSR formula correctness, purged
CV, stationary bootstrap, Reality Check/SPA, capacity parity, registry
idempotence/dirty-flag, CLI `--full` network isolation) is touched by this
iteration's diff, and none of it was re-broken.
