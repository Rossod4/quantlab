# M05 Validation I — HANDOFF.2 (quant-gate cycle-1 REJECT fixes)

Addresses every finding in `plans/state/M05/VERDICT.md` plus the team lead's iteration-2 addendum (items 7–9).

## 1. Sub-period table blind to first return — FIXED
`subperiod_table` rebases each sub-period's equity from the true prior
boundary point in `net_equity`, not a bare `1+r0` start; gains a `Growth`
column. `metrics.standard_metrics` (frozen, shared by rolling/walk-forward)
untouched — confirmed byte-identical to the old repo, documented as frozen
parity. Regression: `[-0.50, 0.10, 0.10, 0.10]` now shows MDD −0.50;
growth-product check reads the table's own `Growth` column.

## 2. `no_cliff_score` edge truncation — FIXED
`SensitivityResult` gains `neighbourhood_size`/`neighbourhood_truncated`.
`base_point` now REQUIRED for any even-length axis. Flagged in
`validate_basic`. Regression reproduces the gate's 5-point probe exactly
(base=6→−0.6, base=12→0.85, base=18→0.971).

## 3. Unscored/dropped counts doubled — FIXED
Combined sentence states the relationship without repeating either count;
each appears exactly once. Test asserts occurrence COUNTS of the
number-bearing phrase, not substring membership.

## 4. One-liner missing extreme_returns_long/short — FIXED
Extracted `cli._validate_one_liner`; appends the breakdown when nonzero.
New `tests/test_cli_validate.py`; re-verified via a live subprocess.

## 5. Sortino convention undocumented — FIXED (non-blocking)
Docstring states target-0/full-sample-N/ddof=0, notes the ddof mismatch.

## 6. Benchmark overlap not recorded — FIXED (non-blocking)
`MetricsSummary.benchmark_overlap_periods`; `ValidationConfig.
benchmark_overlap_min_fraction` (0.9, in `configs/validation.yaml`) —
M05's first self-read threshold; flags a short overlap.

## 7. Trial id ignores backtest_config — FIXED
`_strategy_id_for_point` hashes `start`/`end`/`execution`/cost fields plus
`DATA_SEMANTICS_VERSION` alongside params. Regression: same grid over two
windows gives different ids; same window twice gives identical ids.

## 8. `no_cliff_score` NaN order-dependence — FIXED
Builtin `max`/`min` mishandle NaN inconsistently by position; `median()`
always skips it. NaN neighbours now filtered first; `nan_points` records
the count, flagged when nonzero. Regression: ascending vs. descending axis
order (same NaN, different accumulation order) now gives an identical
score.

## 9. Benchmark-beats-strategy flag abstains on NaN — FIXED
A NaN `benchmark_sharpe` now flags "no usable benchmark Sharpe (NaN)"
instead of the comparison silently reading False.
## Verification
`uv run pytest tests/ -q`: exit 0, 416 dots (398 at cycle 1), 0 fail.
`ruff check` / `ruff format --check`: clean, repo-wide. Manual end-to-end
CLI smoke test with nonzero extreme_returns: correct output.

## Files touched
`src/quantlab/validation/{metrics,rolling,sensitivity,basic}.py`,
`src/quantlab/cli.py`, `configs/validation.yaml`, five existing test
files, new `tests/test_cli_validate.py`.
