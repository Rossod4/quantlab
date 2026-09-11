VERDICT: ACCEPT

# M05 quant gate — cycle 2

Scope: developer iteration 2 (`plans/state/M05/HANDOFF.2.md`), code review `REVIEW.2.md`,
re-verification of all four cycle-1 blocking findings and both non-blocking findings from
`plans/state/M05/VERDICT.md`, and the three orchestrator additions drawn from my carried
notes (trial-id fingerprinting, deterministic NaN handling, an explicit no-usable-benchmark
flag).

Tree at gate time: 416 tests collected and passing (`uv run pytest tests/ -q`, exit 0, up
from 398 at cycle 1), `uv run ruff check` clean, `uv run ruff format --check` reports 80
files already formatted. All 91 tracked `.py`/`.yaml` files are md5-identical to my
pre-gate baseline — no repo file was mutated by this gate; every probe below ran from the
session scratchpad. `data/` was not touched.

Every cycle-1 finding is fixed. I re-ran my original cycle-1 reproductions unchanged
against the current tree rather than reading the fixes or trusting the shipped regression
tests, and in each case the number that was wrong is now right and the counterfactual that
made it wrong is documented in the code.

---

## Cycle-1 findings, re-probed with the original fixtures

**Finding 1 — sub-period table blind to each sub-period's first return. FIXED.** My exact
cycle-1 fixture (13 years of monthly returns, shipped regime definitions, the rate-shock
regime's worst month planted as that regime's own first month) now reconciles to the last
digit in every row:

```
sub-period              CAGR shown  CAGR truth  MDD shown  MDD truth   MDD err
first_half                 +0.1133     +0.1133    -0.2001    -0.2001   +0.0000
second_half                +0.0724     +0.0724    -0.2351    -0.2351   +0.0000
precovid_2012_2019         +0.1217     +0.1217    -0.2001    -0.2001   +0.0000
covid_2020                 -0.0611     -0.0611    -0.1975    -0.1975   +0.0000
rate_shock_2021_2022       +0.0270     +0.0270    -0.1852    -0.1852   +0.0000
recent_2023_plus           +0.1292     +0.1292    -0.1142    -0.1142   +0.0000
```

`rate_shock_2021_2022` was the row that failed at cycle 1 (+11.93% CAGR against a truth of
+2.70%, −10.48% max drawdown against a truth of −18.52%); its error is now +0.0000 in both
columns. The degenerate window is likewise exact:

```
[-0.50, +0.10, +0.10, +0.10]
  Max Drawdown  -0.5000   (cycle 1: +0.0000)
  CAGR          -0.7075   (cycle 1: +2.1912)
  Growth      0.665500    truth 0.665500
```

`_rebased_subperiod_equity` rebases from the boundary point in `net_equity` immediately
preceding the sub-period's first return, which is the same convention
`engine.py:_equity_with_start` uses for the headline curve. I checked the boundary case the
helper depends on — a sub-period starting at the very first return of the whole run, where
the prior point is the run's synthetic 1.0 — and the whole-series sub-period reproduces both
the headline `cagr(net_equity)` and the total growth to better than 1e-12.

Acceptance criterion 4 is now discharged on the table itself. `subperiod_table` gained a
`Growth` column, and the product of the two halves' `Growth` cells against total growth
reads `abs diff = 0.000e+00`. That closes cycle-1 finding 1(c): the old test computed both
sides from the raw return series and would have passed on a garbage table.

**The frozen path was correctly left alone**, which is what I asked for rather than a
uniform "fix". I reran the old repo's `rolling_window_metrics` and `_window_metrics` against
the new ones across four shapes (60/12/3y, 48/12/1y, 40/4/5y, 156/12/5y), each with a −50%
first return planted to maximise any divergence:

```
max|diff| = 0.000e+00 in all four; columns and index identical
_window_metrics vs standard_metrics, cell by cell: 0.000e+00 on all four metrics
  (Max Drawdown +0.0000 on the -50%-opening window — blindness intact, as required)
```

`standard_metrics`'s docstring now states the blindness explicitly, names it as frozen under
CLAUDE.md invariant #4, cites the old repo's identical construction, notes that
`tests/test_rolling.py` deliberately pins the 11-of-12 behaviour, and closes with a direct
instruction not to reuse the helper for a new surface where the first return matters.
`rolling.py`'s module docstring repeats it and says why `subperiod_table` does not share it.
That is the documented-beside-it disposition the cycle-1 remedy called for.

**Finding 2 — `no_cliff_score` edge truncation. FIXED.** My cycle-1 five-point probe, rerun
verbatim on the same fixed Sharpe surface:

```
base= 6  score=-0.6000  neighbourhood_size=2  truncated=True   nan_points=0
base=12  score=+0.8500  neighbourhood_size=3  truncated=False  nan_points=0
base=18  score=+0.9710  neighbourhood_size=2  truncated=True   nan_points=0
```

The scores are unchanged, which is correct — the formula was never the problem. What changed
is that the two-point cases now announce themselves, and both fields serialise
(`neighbourhood_size`, `neighbourhood_truncated`, `nan_points` all appear in `to_json()`),
so M06 cannot gate `min_no_cliff_score` on a one-sided score without seeing that it is
one-sided. `validate_basic` also flags it.

The even-length-axis default, which at cycle 1 silently landed on the last element, now
refuses rather than guessing:

```
ValueError: base_point must be given explicitly for even-length axis/axes ['n_long'] -
there is no unambiguous middle value to default to (values[len//2] would silently pick a
grid edge)
```

**Finding 3 — unscored and dropped counts stated twice. FIXED.** The combined sentence now
states the relationship without carrying either number ("this bound and the unscored-ticker /
dropped-ticker counts reported separately below are SEPARATE selection effects, not additive
into one headline number"), so the mandated carried-item-4 wording survives while each count
moves to exactly one place. I verified this by planting six mutually distinct counts
(forced=7, long=5, short=6, unscored dates=8, dropped dates=3, bound=12.5) and counting
occurrences of each number across all flags: every one appears exactly once.
`missing_forward_prices` still appears nowhere.

**Finding 4 — `validate` one-liner missing the per-book extreme counts. FIXED.** Run
end-to-end through the actual CLI on a saved result:

```
net CAGR=13.06%  Sharpe=...  Sortino=...  Calmar=...  maxDD=0.00%  hit_rate=100.0%  extreme_returns_long=2 extreme_returns_short=1
```

The breakdown is on the metrics line itself, not only in the flags beneath it. I also checked
the control the fix could easily have got wrong: with both counts zero, the one-liner omits
them rather than printing two noisy zeros.

**Non-blocking finding 5 — Sortino convention. FIXED.** The formula is unchanged (correctly
— it was right). The docstring now states target 0, full-sample N via `(downside**2).mean()`
at ddof=0, explains why full-sample N is the right lower-partial-moment choice, and warns
that this puts Sortino's denominator on a different ddof footing from
`annualized_vol`/`sharpe_ratio`'s ddof=1.

**Non-blocking finding 6 — benchmark overlap unrecorded. FIXED.** `MetricsSummary` gained
`benchmark_overlap_periods`, and `validate_basic` flags a short overlap against a new
`benchmark_overlap_min_fraction` (0.9, in `configs/validation.yaml`). On my cycle-1 fixture:

```
benchmark_overlap_periods = 6 of 36
flag: "benchmark covers 6 of 36 periods (17%) - beta / information ratio / tracking error
       are computed on that overlap only"
```

Note this is M05's first self-read threshold, correctly kept out of the `thresholds` block
reserved for M06.

---

## Orchestrator-added items, independently verified

**Item 7 — trial ids ignore `backtest_config`. FIXED.** `_strategy_id_for_point` now
fingerprints the window, execution mode, the four cost-model fields and
`DATA_SEMANTICS_VERSION` alongside the params. My cycle-1 collision no longer occurs:

```
9 grid points, 9 distinct ids within a run
different WINDOW       -> ids shared with the base run: False   (cycle 1: all 9 identical)
different COST (25bps) -> ids shared with the base run: False
same config rerun      -> ids reproducible: True
```

Reusing the existing `core/semantics.py` constant rather than inventing a second version
string is the right call, and it partly discharges the standing M03b/M04 note about
`strategy_id` not encoding data semantics — for sensitivity trials specifically.

**Item 8 — NaN order-dependence. FIXED, and I confirmed the defect was real before
accepting the fix.** The cycle-1 hazard needed a genuine NaN Sharpe, which a nominally
constant return series does not produce (floating-point noise leaves a tiny nonzero std). I
used a one-observation series, where `std(ddof=1)` is NaN, and confirmed the underlying
asymmetry directly:

```
builtin max/min over [1.0, nan, 2.0] -> spread 1.0
builtin max/min over [nan, 1.0, 2.0] -> spread nan
```

With the fix, the same NaN neighbour under opposite axis enumeration orders now gives
identical results — 0.3333333333 both ways with the NaN at the base point, 0.7142857143 both
ways with it at a non-base neighbour, `nan_points=1` in every case. An all-NaN neighbourhood
returns a NaN score rather than a spurious 1.0 "perfectly flat", which is the failure mode
that would have mattered most.

**Item 9 — benchmark comparison silently abstaining on NaN. FIXED.** A degenerate benchmark
now produces `no usable benchmark Sharpe (NaN) - cannot compare to strategy Sharpe` instead
of a comparison that quietly evaluates False and emits nothing. Verified live through the CLI.

---

## Other checks

- **Walk-forward, re-probed against the current tree.** My cycle-1 planted fixture — a
  sleeve returning +50% per quarter in exactly the first test block and nowhere else — still
  gets weight 0.0 in that block, and the OOS block is elementwise equal to the other sleeve.
  No self-influence. The iteration-2 diff did not touch `walk_forward.py`.
- **Parity.** `tests/parity/` is untouched and all parity tests pass. My own
  cross-implementation reruns against the old repo (above) confirm the frozen path
  independently of the shipped parity tests.
- **`subperiod_table`'s new two-series signature is safely used.** The only caller in `src/`
  is `basic.py:229`, which passes `result.net_returns` and `result.net_equity`; the engine
  guarantees the leading synthetic 1.0 on the latter via `_equity_with_start`, and
  `BacktestResult.load` round-trips it. The helper's dependence on that point is documented.
- **Carried M04 items.** Item 1 (never read `snapshots`) still holds — the `Exploding()`
  sentinel test passes. Items 2, 3 and 4 are now fully closed by findings 4, 3 and 3
  respectively.

## One non-blocking note, carried rather than blocked

`_rebased_subperiod_equity` computes `net_equity.index.get_loc(first_return_date) - 1`. If a
caller passes a `net_equity` that lacks the synthetic leading 1.0, that index is −1, the
slice wraps, and the row degrades silently (I measured `Growth=1.000000`, `CAGR=nan`,
`Max Drawdown=0.000000` against a true growth of 3.163726). This is unreachable from any
in-product path, the requirement is documented in the helper's docstring, and the degraded
output is conspicuously degenerate rather than plausibly wrong — so it is a defensive-coding
note for M06/M07, not a finding. A one-line guard raising when `first_pos == 0` would close
it.

---

M05 is accepted. The four blocking findings are fixed with the original probes reproducing
clean numbers, the two non-blocking ones are fixed, the three orchestrator additions are
fixed and independently verified, and — the part I weighted most heavily — the frozen ported
path was left byte-identical and documented rather than quietly "improved", while the new
surface that had no parity obligation was corrected. The milestone now makes it harder to
fool ourselves than it did at cycle 1: a regime table that reconciles to the headline curve,
a robustness score that declares when its own sample was truncated, and quality counters
that are each stated once.
