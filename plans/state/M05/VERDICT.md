VERDICT: REJECT

# M05 quant gate — cycle 1

Scope: work packet `plans/M05-validation-1.md` (in-scope files, acceptance criteria 1–7,
"Carried from the M04 verdict" items 1–5), `plans/state/M05/HANDOFF.md` (six documented
deviations), `plans/state/M05/REVIEW.md` (APPROVE, findings 1–10), every
`plans/QUANT-NOTES.md` item addressed to M05, and the port sources under
`..\MomentumValueStrategy\src\evaluation\`.

Tree at gate time: 398 tests pass (`uv run pytest tests/ -q`, exit 0), `uv run ruff check`
clean. All 90 tracked `.py`/`.yaml` files are md5-identical to my pre-gate baseline — no
repo file was mutated by this gate; every probe below ran from the session scratchpad.
`data/` was not touched.

The code review's APPROVE is sound on the things it examined by reading. The parity work
is genuine (both parity files import the old repo through `sys.path` and compare, so drift
in either tree is caught automatically), the frozen numerics really are byte-identical in
logic to the old repo, `periods_per_year` really is never inferred from data anywhere, the
snapshots sentinel really does have teeth, and the walk-forward generalisation really does
reproduce the old scalar implementation. I re-verified all of that and found nothing wrong
with it.

The findings below are in the presentation layer the review checked by reading docstrings
rather than by running adversarial fixtures. Three of them run in the flattering direction,
and the first one fires on a regime boundary that `configs/validation.yaml` ships today.

---

## Blocking findings

### 1. The sub-period / regime table cannot see each sub-period's FIRST return: its CAGR omits it and its Max Drawdown is blind to it. On the shipped `rate_shock_2021_2022` regime this overstates CAGR by 9.2pp and understates max drawdown by 8.0pp, undisclosed

**Risk.** This is "anything a referee would reject in how M05 summarises a result". A regime
table exists to answer "did this strategy survive the bad regime?", and regime boundaries are
drawn, by construction, immediately before the event the regime is named for — which is
exactly the position in which this defect is maximal. Direction: flattering in both columns.

**Evidence.** `src/quantlab/validation/metrics.py:standard_metrics` builds the window's
equity as `equity = (1 + returns).cumprod()`, so `equity.iloc[0]` is `1 + r_0`, not `1.0`.
There is no `1.0` point in the curve at all. Consequences: `cagr` divides
`equity.iloc[-1] / equity.iloc[0]`, which cancels `r_0` out of the numerator, and
`max_drawdown`'s `cummax` starts at `1 + r_0`, so a loss in the window's first period is
never measured from a peak that precedes it.

`src/quantlab/validation/rolling.py:subperiod_table` feeds every named regime and both
halves of `first_second_half_splits` through that helper.

Probe, on the four regimes exactly as `configs/validation.yaml` defines them, over a
monthly 2012–2024 series whose single worst month of the rate-shock regime is that regime's
first month (2021-01, −15.0%) — the shape the regime name is describing:

```
sub-period              CAGR shown  CAGR truth  MDD shown  MDD truth  MDD error
first_half                 +0.1131     +0.1133    -0.2001    -0.2001    +0.0000
second_half                +0.0692     +0.0724    -0.2351    -0.2351    +0.0000
precovid_2012_2019         +0.1216     +0.1217    -0.2001    -0.2001    +0.0000
covid_2020                 -0.0645     -0.0611    -0.1959    -0.1975    +0.0016
rate_shock_2021_2022       +0.1193     +0.0270    -0.1048    -0.1852    +0.0803
recent_2023_plus           +0.1140     +0.1292    -0.1142    -0.1142    +0.0000
```

("truth" = the same slice with the equity curve rebased to 1.0 *before* the first return is
applied, i.e. the way `engine.py:_equity_with_start` builds the headline `net_equity`.)

The degenerate case is total, not marginal:

```
window returns: [-0.50, 0.10, 0.10, 0.10]
  standard_metrics Max Drawdown = +0.0000     TRUTH = -0.5000
  standard_metrics CAGR         = +2.1912     TRUTH = -0.7075
```

A sub-period that lost half its capital in its opening period is reported as having had no
drawdown at all.

Three things make this a finding rather than an inherited quirk to be waved through:

(a) **The docstring asserts the behaviour that would make the numbers right, and the code
does something else.** `standard_metrics`'s docstring says "with the equity curve rebased to
1.0 at the window's start". It is not. Nothing in `rolling.py`, `metrics.py`,
`configs/validation.yaml` or `ValidationBasic.flags` tells a reader the first period is
missing.

(b) **`subperiod_table` is new M05 code under no parity obligation.** I confirmed
`tests/parity/` contains `test_engine_parity.py`, `test_metrics_parity.py`,
`test_signal_parity.py`, `test_walk_forward_parity.py`, and that none of them reference
`subperiod_table` or `standard_metrics`. The old repo never had a sub-period table; it used
`_window_metrics` only for rolling windows and the walk-forward comparison. M05 chose to
extend the helper to a new surface, and that choice is what puts a flattering number in
front of a reader.

(c) **Acceptance criterion 4's growth clause is discharged by a test that never reads the
table.** `tests/test_rolling.py:70` computes `first_growth`, `second_growth` and
`total_growth` from the raw `returns` series and asserts
`first_growth * second_growth == approx(total_growth)`. That is a tautology about `.prod()`
over a partition; it would pass unchanged if `subperiod_table` returned garbage. The only
assertions in that test that touch `table` are `list(table.index)` and
`not table["CAGR"].isna().any()`. The partition itself is sound — I verified the growth
product to 0.0e+00 absolute — but the table has no growth column, and its CAGR column does
not reconcile: recompounding the two half-CAGRs over their own spans gives 1.175443 against
a total growth of 1.204012.

**Remedy.** Leave `standard_metrics` and `rolling_window_metrics` alone — they are frozen
ports and `tests/test_rolling.py:30`'s `expected_growth = 1.01**11` deliberately pins the
11-of-12 behaviour. Instead:

1. Give `subperiod_table` its own window helper that prepends a `1.0` base before the first
   return (mirroring `engine.py:_equity_with_start`), so a sub-period's CAGR and Max
   Drawdown describe all of the returns in that sub-period. Add a test on the
   `[-0.50, 0.10, 0.10, 0.10]` shape asserting Max Drawdown is −0.50, not 0.0.
2. Add a `Growth` column to the table and re-assert criterion 4 **on the table**:
   `table.loc["first_half","Growth"] * table.loc["second_half","Growth"] ==
   approx(total_growth, abs=1e-10)`. That is the check the criterion asked for.
3. Fix `standard_metrics`'s docstring to state what it actually does, and say plainly that
   the rolling table and the walk-forward comparison table omit each window's first return
   because they are frozen ports. That statement is then a carried item for M07's report
   text.

### 2. `no_cliff_score` silently narrows its neighbourhood at a grid edge, which flatters the score — and for an even-length axis the DEFAULT base point IS an edge

**Risk.** The packet's own framing is "values near 1 mean flat, near 0 mean the base point
sits on a cliff", and `configs/validation.yaml` already carries `min_no_cliff_score: 0.5`
for M06 to gate on. A score that rises because fewer points were examined is a robustness
gate that can be passed by moving the base point to the end of the axis.

**Evidence.** `sensitivity.py:_neighbourhood_mask` takes a Chebyshev ball of radius 1 in
grid-index space. At an axis edge the ball is one-sided, so the neighbourhood holds 2 points
instead of 3, the spread `max − min` is drawn from a smaller set, and the score rises.
Nothing in `SensitivityResult` records it — the serialised fields are exactly
`param_axes`, `base_point`, `trials`, `surface`, `no_cliff_score`.

Probe, one fixed Sharpe surface `{6: 0.10, 9: 0.90, 12: 1.00, 15: 1.05, 18: 1.02}` on
`lookback_months ∈ [6, 9, 12, 15, 18]`, varying only where the base point sits:

```
base= 6  neighbourhood=[6, 9]      (n=2)  no_cliff_score=-0.6000
base=12  neighbourhood=[9, 12, 15] (n=3)  no_cliff_score=+0.8500
base=18  neighbourhood=[15, 18]    (n=2)  no_cliff_score=+0.9710
```

The edge point scores 0.971 — the best score on the surface — on a two-point sample, and the
result object gives a reader no way to tell it apart from a genuinely flat interior point.

The default is not safe either. `base_point` defaults to `values[len(values) // 2]`, which
for an even-length axis is the **last** element:

```
axes {'n_long': [30, 50]}  default base_point={'n_long': 50}  (= the edge)
no_cliff_score=-0.3333
```

`configs/validation.yaml` ships only odd-length axes today, so this is latent rather than
live — but it is one edited config line away, and nothing raises or warns.

**Remedy.** Record the neighbourhood explicitly on `SensitivityResult` — at minimum
`neighbourhood_size: int` and `neighbourhood_truncated: bool` (true when any axis clipped
the ball) — serialise both, and surface the truncation in `ValidationBasic.flags` so M06
cannot gate on a one-sided score without seeing that it is one-sided. Either warn or raise
when the default `base_point` lands on an edge (an even-length axis always does). Add a test
on the probe above asserting the edge base point is marked truncated.

### 3. Carried M04 item 3 ("report each once") is violated: `unscored_by_date` and `dropped_tickers_by_date` each appear twice in `ValidationBasic.flags`, and the test that claims to check this does not

**Risk.** This is the precise hazard the M04 verdict named — a reader double-counting a
"how much of this book can't be trusted" number because it is stated twice in two different
sentences. The packet lists this item as binding.

**Evidence.** `basic.py:_quality_flags` seeds the list with
`_coverage_and_selection_flag(result)`, which already states both counts, and then appends
each of them again as its own flag. Actual output for a result with 2 unscored dates and 1
dropped date:

```
- coverage bound 12.5% (...); 2 rebalance date(s) had unscored tickers and 1 had
  data-failure-dropped tickers - these are SEPARATE selection effects ...
- 2 forced exit(s) booked at last available price (delisting)
- 2 long-book extreme-return exclusion(s) (upside-only vendor-glitch guard)
- 1 short-book extreme-return exclusion(s) (upside-only guard - hides adverse moves ...)
- 2 rebalance date(s) had declared-universe tickers left unscored (unpriceable) ...
- 1 rebalance date(s) had ticker(s) dropped by a data-availability failure

flags mentioning the unscored count: 2
flags mentioning the dropped count : 3
```

`tests/test_validation_basic.py:62`, named
`test_validate_basic_reports_each_quality_counter_once`, asserts only that each substring is
*present* in `" | ".join(flags)` — it never counts occurrences, so it passes under the
duplication its own name forbids. REVIEW.md finding 6's "exactly once each" is incorrect on
these two counters; it is correct on `forced_exits`,
`extreme_returns_long`/`_short`, and on `missing_forward_prices` never appearing (all three
of which I re-verified).

Note the genuine tension: carried item 4 *requires* the combined coverage-plus-selection
sentence, and carried item 3 requires each counter once. Both are satisfiable.

**Remedy.** Keep the combined sentence — it carries the mandated "SEPARATE selection
effects" wording — and drop the two standalone restatements, or invert it: keep the
standalone counters and have the combined sentence refer to them without repeating the
numbers. Then make the test assert occurrence counts, not membership, so it fails under the
duplication it is named for.

### 4. Ruling on REVIEW.md finding 9: upheld. The `validate` one-liner must carry nonzero extreme-return counts

The carried M04 item reads "any nonzero count must appear in the one-line summary **and** in
`ValidationBasic.flags`", and the packet marks the carried items binding. The developer's
reasoning in HANDOFF deviation 6 — that M04's `backtest` CLI already prints a combined
`extreme_returns` on its own one-liner (`cli.py:104`) — is true but does not discharge it:
that line shows only the combined count, never the `long`/`short` breakdown the item names
in its parenthetical, and it is printed by a different command in what may be a different
session from whoever later runs `validate` on a saved result.

The review is right that the information is not lost — `_quality_flags` always emits it and
the CLI echoes every flag directly beneath the metrics line — which is why this is the
smallest of the four blocking items and a one-line change. I am ruling it required rather
than deferred because it is cheap, it is binding packet text, and the same one-liner is what
M06 will print beside PSR and DSR.

**Remedy.** In `cli.py`'s `validate`, append `extreme_returns_long=N extreme_returns_short=M`
to the `net CAGR=... Sharpe=...` line when either is nonzero. Test it.

---

## Non-blocking findings (fix if convenient; otherwise carried)

### 5. Sortino's downside-deviation convention is correct but unstated

Answering the question directly: `metrics.py:sortino` uses target 0 and **full-sample N**
(`(returns.clip(upper=0)**2).mean()`, i.e. sum of squared negatives divided by the count of
**all** periods, ddof=0). Verified on a 6-period series with 2 negatives — the shipped value
matches `annualised_mean / 0.082462` (full-sample N) and not `/ 0.142829` (downside-only N).

That is the standard lower-partial-moment convention and the right choice; downside-only N
would make Sortino incomparable across series with different numbers of losing periods. But
the docstring states only "target return 0" and never says which N, and the two differ by
73% on that fixture. Separately, the Sharpe denominator is pandas `.std()` with ddof=1 while
Sortino's is ddof=0, so the two ratios are not on the same denominator footing and a reader
comparing them directly will be slightly misled.

**Remedy.** One docstring sentence naming full-sample N and ddof=0, and one noting the ddof
difference from `annualized_vol`. Repeat it in `MetricsSummary`'s field documentation, since
that is what M06 and M07 will read.

### 6. `beta`, `information_ratio` and `tracking_error` align to common dates correctly, but the overlap count is recorded nowhere

`_align` does `a.index.intersection(b.index)`, which is the right convention and matches the
old repo's `blend_returns`. The gap is disclosure: a benchmark covering a fraction of the
strategy's window produces a fully-formed number with no indication of the sample it came
from.

```
strategy 60 months, benchmark 60 months -> beta=-0.1602  IR=+0.1820  TE=0.2149
strategy 60 months, benchmark  6 months -> beta=-0.4855  IR=-0.1506  TE=0.2880
```

Beta triples and the information ratio flips sign, silently, on 6 of 60 months. Zero overlap
returns NaN for all three with no flag. `MetricsSummary` has no overlap field.

**Remedy.** Add `benchmark_overlap_periods: int` to `MetricsSummary`, and a flag when the
overlap is shorter than `net_returns` ("benchmark covers 6 of 60 periods; beta / IR /
tracking error are computed on that overlap only").

---

## Verified clean (probed, not read)

- **Walk-forward has no self-influence.** I built the fixture the packet's premise demands:
  sleeve A steady at +2%/quarter, sleeve B mediocre everywhere except the first test block
  where it returns +50% per quarter. A leaky implementation would have picked B for that
  block — the counterfactual training-on-test Sharpes are 46.9 for pure A rising to 3521.6
  at 25/75. The implementation picked `A=1.0, B=0.0` at every step, and the first four OOS
  returns are elementwise equal to pure A. I also audited every train/test index pair:
  `train[0:20] test[20:24]`, `train[4:24] test[24:28]`, … overlap 0 in all five steps. The
  training window is rolling and does absorb *prior* test blocks, which is correct
  walk-forward, not leakage.
- **Walk-forward conventions are all present and faithful.** Sharpe criterion, the coarse
  5-point grid, rolling (not expanding) training window, partial final block kept,
  `reduce`-based common-dates alignment across N children. The four shipped parity tests
  compare `oos_returns` and the momentum-weight column against the old repo's own scalar
  implementation, including the dominance-flip and partial-final-block shapes.
- **The blend-of-net-returns convention is documented as the packet requires, and the
  justification is sound.** `walk_forward.py`'s module docstring states the convention, names
  M04's netted-book costing as the different one, cites QUANT-NOTES M03 item 2, says the two
  disagree whenever turnover/borrow are nonlinear in weights, gives the reason the old
  convention is right for *this* question (it asks about weight-choice stability, not about
  netted cost), and closes with an explicit "do not use this module's `oos_returns` as a
  substitute for a real M04 blend backtest's `net_returns`". That is the full disclosure the
  packet asked for. One residual, carried below rather than blocked on: the conclusion
  transfers to the netted book only if the Sharpe *ranking* across grid points is the same
  under both conventions, which nothing tests.
- **Annualisation is right, and `periods_per_year` is never inferred from data.** The same
  underlying series read monthly at 12 and quarterly at 4 gives consistent annualised vol
  (0.1571 vs 0.1058, within sampling noise for 60 vs 20 observations); reading the quarterly
  series at 12 inflates vol by the expected √3 = 1.73x. Every metric function takes
  `periods_per_year` explicitly; `summary()` and `sensitivity_grid()` both read it from the
  rebalance frequency in provenance / `BacktestConfig`, never from an index.
- **The first/second-half partition is exact.** `first_second_half_splits` splits by position,
  so every return falls in exactly one half; growth product versus total growth differs by
  0.0e+00 on a 120-month series. The defect in finding 1 is in the table's columns, not in
  the partition.
- **Calmar sign conventions are right.** Positive CAGR with a drawdown gives a positive
  Calmar (+1.9112), negative CAGR gives a negative Calmar (−2.2421), and a curve with no
  drawdown gives NaN rather than a silent infinity.
- **New-metric identities hold.** `IR(r, r) = 0.0` exactly, `TE(r, r) = 0.0`,
  `beta(r, r) = 1.000000` — acceptance criterion 7.
- **Trials are shaped for M06's DSR N.** A 3×3 grid produces 9 grid points, 9 trials and 9
  distinct `strategy_id`s; `_strategy_id_for_point` hashes the sorted-key JSON of the full
  per-point param dict. N is not undercounted. (It is over-counted by one against the
  headline run, since the base point appears both as a sensitivity trial and — under a
  different id scheme — as the headline strategy; over-counting is conservative for DSR, so
  I am not blocking on it. See the carried item on id reconciliation.)
- **The injected runner is the only backtest path.** `sensitivity.py` imports nothing from
  `quantlab.strategies` or `quantlab.backtest.engine`; the only backtest-shaped call is
  `runner(...)`.
- **Carried M04 item 1 holds.** `summary()` reads only `net_returns`, `gross_returns`,
  `net_equity`, `gross_equity`, `turnover` and the benchmark series. The `Exploding()`
  sentinel test, which raises on any attribute or item access to `snapshots`, passes.
- **Carried M04 item 3, the `missing_forward_prices` half, holds.** The string appears
  nowhere in the flags; `forced_exits`, `extreme_returns_long` and `extreme_returns_short`
  are each reported once, and the long/short split is preserved rather than collapsed.
- **Carried M04 item 4 holds.** `_coverage_and_selection_flag` is emitted unconditionally,
  combines the bound with the unscored and dropped counts, and carries the mandated wording:
  "these are SEPARATE selection effects from the coverage bound and from each other, not
  additive into one headline number".
- **The flags text is accurate and non-flattering.** "benchmark Sharpe exceeds strategy
  Sharpe" is stated plainly, with no softening; the short-book extreme-return flag
  volunteers "hides adverse moves for a short book" rather than reporting a bare count; the
  negative-rolling-window flag names its own basis ("by CAGR"). I found no flag whose wording
  reads better than the number behind it.
- **The AST canary has mutation power.** `tests/canaries/test_no_prices_for_returns_in_
  strategies.py` contains its own `test_canary_detects_a_planted_violation`, so it proves the
  scan fires rather than only that it currently finds nothing. Closes the M04 carried
  canary item (already marked superseded-but-optional by VERDICT.2).
- **HANDOFF deviations.** I agree with the review on all six. None weakens a frozen numeric,
  none touches `BacktestResult`, and each is justified either by information a single
  positional argument cannot carry (child sleeve series; an injected runner) or by a scope
  line the packet itself draws (ported versus new functions). Deviation 6 is the one I am
  ruling against, as finding 4 above — on the binding carried text, not on the reasoning.

---

## What is needed to move to ACCEPT

Findings 1–4, each with a named remedy and each needing a test that fails before the fix.
Findings 5 and 6 are one docstring sentence and one summary field respectively; fold them in
if convenient, otherwise they carry to M06.

No requirement in the packet is itself methodologically wrong, so this is another loop
iteration, not an ESCALATE-TO-HUMAN. Finding 1 is the one that matters: everything else is
disclosure, but a regime table that reports −10.5% max drawdown for a regime that actually
drew down 18.5%, under a heading naming the shock it is supposed to measure, is the single
number in this milestone a referee would refuse.
