REVIEW: APPROVE

# M05 Validation I — Code Review, iteration 2 (post quant-gate REJECT)

## Verification (run myself)
- `uv run pytest tests/ -q`: exit 0, 416 dots (was 398), 0 failures.
- `uv run ruff check`: all checks passed.
- `uv run ruff format --check`: 80 files already formatted.
- `git diff --stat -- src/ tests/`: only `src/quantlab/cli.py` is a tracked
  modification (the `validate` one-liner fix); every `validation/*.py` and
  test file is the developer's own new/edited content. No reverts were
  needed — I made no mutations during review (all probes below ran from a
  scratchpad script, never against the tree).
- Independently reproduced every gate probe named in VERDICT.md (not just
  re-read the fix or the regression test) — details below.

## Independent verification of each blocking/carried fix

**1. Sub-period first-return blindness (VERDICT.md finding 1).**
Reproduced the gate's rate-shock scenario myself (a 13-year monthly series
with a single −15% month at 2021-01, the rest flat +1%) and its degenerate
`[-0.50, 0.10, 0.10, 0.10]` window, both through the current
`subperiod_table`, and compared against the equity path correctly rebased
to 1.0 at the boundary immediately preceding each sub-period's first
return (the same convention `backtest/engine.py` uses for the headline
`net_equity`):
- Degenerate window: Max Drawdown = −0.5000 exactly (was +0.0000 pre-fix).
- Rate-shock regime: Max Drawdown = −0.150000... in both the code's output
  and my independently-computed truth; Growth = 1.0685885... in both.
Also confirmed `rolling_window_metrics` is still byte-identical to the old
repo's `_window_metrics` (I reran the old repo's own fixture through both
and diffed every cell to machine precision — 0 diffs) — the frozen path
was correctly left alone. `standard_metrics`'s docstring now states the
blindness explicitly and says not to reuse the helper for a new surface
where the first return matters; `rolling.py`'s own module docstring
repeats it. `test_subperiod_table_growth_product_matches_full_period` now
asserts on `table.loc[..., "Growth"]` (the table's own column), not on
values recomputed from the raw returns — closes finding 1(c)'s tautology
complaint.

**2. `no_cliff_score` edge truncation (VERDICT.md finding 2).**
Rebuilt the gate's exact fixed-Sharpe surface
(`{6:0.10, 9:0.90, 12:1.00, 15:1.05, 18:1.02}`) and reran
`sensitivity_grid` at each of the gate's three base points myself:
`base=6 → neighbourhood_size=2, truncated=True, score=−0.6000`;
`base=12 → size=3, truncated=False, score=0.8500`;
`base=18 → size=2, truncated=True, score=0.9710` — matches VERDICT.md's
probe to 4+ decimal places in every case. Confirmed an even-length axis
with no explicit `base_point` now raises `ValueError` (message names the
offending axis and explains why `values[len//2]` would silently land on
an edge) rather than silently defaulting to one.

**3. Doubled unscored/dropped counts (VERDICT.md finding 3).**
Read `_coverage_and_selection_flag`/`_quality_flags`: the combined
sentence now states the relationship ("this bound and the ... counts
reported separately below are SEPARATE selection effects") without
repeating either number, and each standalone flag is the only place its
number appears.
`test_validate_basic_reports_each_quality_counter_exactly_once` was
rewritten to assert exact occurrence counts of the number-bearing phrase
across all flags (an `_occurrences` helper), not substring membership —
this is exactly the class of test the gate said would have caught the
original defect; I confirmed the assertion would fail if either count
were re-inserted into the combined sentence (checked by reading, not by
reintroducing the bug into the tree).

**4. `validate` one-liner missing extreme counts (VERDICT.md finding 4).**
Built a fixture `BacktestResult` with `extreme_returns_long=2`,
`extreme_returns_short=1` and ran the actual `quantlab validate` command
end-to-end via `typer.testing.CliRunner` (not just read the diff). Output:
```
net CAGR=9.58%  Sharpe=1.42  Sortino=2.60  Calmar=4.79  maxDD=-2.00%  hit_rate=75.0%  extreme_returns_long=2 extreme_returns_short=1
```
The breakdown is on the one-liner itself, exactly as the ruling required.
The same run also exercised finding 9's fix live: with a zero-variance
embedded benchmark (NaN Sharpe), the flags included
`no usable benchmark Sharpe (NaN) - cannot compare to strategy Sharpe`
rather than silently omitting any comparison.

**5. Non-blocking findings 5/6 and carried items 7/8/9 — all present and correct.**
- Finding 5 (Sortino convention): docstring now states target-0,
  full-sample N, ddof=0, and flags the ddof mismatch against
  `annualized_vol`'s ddof=1. Matches the formula (unchanged).
- Finding 6 (benchmark overlap): `MetricsSummary.benchmark_overlap_periods`
  added; `validate_basic` flags when overlap/total < the new
  `benchmark_overlap_min_fraction` config (0.9, and correctly documented
  as an M05-read threshold, unlike the `thresholds` block).
- Carried item 7 (trial id ignores backtest_config): `_strategy_id_for_point`
  now fingerprints `start`/`end`/`execution`/cost-model fields plus the
  existing `DATA_SEMANTICS_VERSION` constant (confirmed this is the
  pre-existing M04 module `core/semantics.py`, correctly reused rather
  than reimplemented). I independently reran the same 3-point grid over
  two different backtest windows and confirmed all three ids differ
  pairwise, and reran the same window twice and confirmed identical ids.
- Carried item 8 (NaN order-dependence): filtering NaN neighbours before
  `max`/`min`/`median` removes the order-dependence. I independently built
  the gate's asymmetric-NaN-position fixture (grid orders `[9,12,15]` vs
  `[15,12,9]`, one NaN-Sharpe neighbour) and got identical scores
  (0.333333... both ways, `nan_points=1` both ways).
- Carried item 9 (silent NaN fall-through on the benchmark comparison):
  confirmed live in the CLI run above — the flag fires explicitly instead
  of the comparison being silently False.

## Findings
None. All four blocking findings and the two non-blocking findings from
`plans/state/M05/VERDICT.md`, plus the team lead's three added items
(trial-id fingerprinting, NaN-order independence, explicit no-usable-
benchmark flag), are fixed, each with a regression test that reproduces
the gate's own probe or a materially equivalent one, and I reproduced the
gate's numeric probes independently rather than trusting the shipped
tests alone. Test count rose from 398 to 416 (18 new tests: 4 sub-period
regressions, 5 sensitivity edge/NaN/id regressions, 1 benchmark-NaN
regression, 1 benchmark-overlap regression, 2 sensitivity-flag
validate_basic regressions, 4 one-liner CLI tests, 1 config field test).
No new production-code paths were left unexercised by a test in this
diff.

## Verdict
APPROVE. Ready for quant-gate re-review.
