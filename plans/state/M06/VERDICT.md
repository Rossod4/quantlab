VERDICT: REJECT

M06 cycle 1. The closed-form statistics are right — I re-derived PSR, DSR's
`SR*`, MinTRL and the purged-split construction independently and they match the
module to 0.0 absolute (evidence in finding 0 below). The footing fix from
REVIEW.md landed correctly. What fails is the plumbing between those formulas
and the verdict: four of the report card's gates can be made easier to pass, or
are measuring something other than what they are named, and the milestone's own
decision function cannot reach two of its three verdicts through the shipped
CLI.

Findings 1–6 are blocking. Finding 4 carries an ESCALATE-TO-HUMAN
recommendation on the design question underneath it; the disclosure half of that
remedy is in-loop.

---

## 0. Verified correct (no finding) — recorded so cycle 2 does not redo it

- **PSR / DSR / MinTRL closed forms.** Recomputed outside the module in
  `numpy`/`scipy`: `PSR(0.25, 0.05, 60, -0.5, 4.0)` hand = module =
  `0.9220661904217928`, difference exactly `0.0`. `PSR(SR==SR*) = 0.5` exactly.
  `SR*` with the Euler-Mascheroni constant and both `Φ⁻¹` arguments
  (`1 − 1/N`, `1 − 1/(N·e)`) reproduces to `0.0` at `N=25, V=0.04`
  (`SR* = 0.39943`). MinTRL round-trips exactly: evaluating PSR at
  `n = MinTRL(confidence=c)` returns `c` to 10 decimal places for
  `c ∈ {0.90, 0.95, 0.99}`. `EULER_MASCHERONI` is correct to double precision.
- **DSR responds correctly to its own arguments.** On a 144-month book at
  annualised Sharpe 1.0 (per-period 0.2887): `N=10, V=0.02 → 0.7803`;
  `N=50, V=0.02 → 0.3485`; `N=200, V=0.05 → 0.0001`. The packet's "many trials,
  modest SR must fail" case fails as it should, and monotonicity in `N` holds
  at every fixed `V` I tried.
- **Purged K-fold construction.** Brute-forced over five parameter sets
  (`(n,k,embargo,horizon)` = `(100,5,3,2)`, `(144,5,1,1)`, `(60,4,0,1)`,
  `(200,6,5,4)`, `(37,3,2,3)`): **0** training positions whose label window
  `[j, j+h)` intersects the test fold, **0** inside the embargo, and the test
  folds partition the index exactly in every case.
- **RC/SPA statistic construction.** White's full recentring
  (`sqrt(T)·(resampled_mean − sample_mean).max()`) and Hansen's consistent
  recentring at `−sqrt(2 ln ln T)` both match the papers. On 40 independently
  generated planted-alternative datasets, SPA's p-value exceeded RC's in
  **0/40**; median planted-alternative RC p-value `0.0000`.
- **Stationary bootstrap.** Continuation probability is `1 − 1/L`, i.e. the
  geometric parameter is `1/L`, per Politis & Romano; `block_len=1` degenerates
  to i.i.d. resampling exactly.
- **Capacity port.** The Corwin-Schultz algebra and the
  `participation × ADV / position_frac` ceiling are a faithful transcription of
  `..\MomentumValueStrategy\scripts\cost_realism_analysis.py`.
- **Suite hygiene.** `uv run pytest tests/ -q` exit 0, 508 tests, ~12 s;
  `ruff check` and `ruff format --check` clean (97 files).

---

## 1. [BLOCKER] Recording more trials RAISES the deflated Sharpe ratio, so the platform's only multiple-testing hard gate can be talked into passing

**Risk.** `registry.py`'s module docstring, and the `_REGISTRY_BASE_POINT_NOTE`
that `build_report_card` copies verbatim into every report card's
`known_caveats`, both assert that over-counting `N` is "the CONSERVATIVE
direction for DSR (a larger N makes the deflation harsher, not more lenient)".
That is only true holding `V[SR]` fixed. This registry estimates `V[SR]` from
the same trial set it counts `N` over (`registry.py:452-465`,
`var_sr_trials`), so every additional trial whose Sharpe sits near the existing
mean simultaneously raises `N` and *shrinks* `V̂`. `SR*` scales as `√V̂`, and the
shrinkage beats the `Φ⁻¹` growth comfortably. The reassurance printed on the
report card is therefore backwards, and the direction of the error is
permissive on the single hard gate that exists to punish search.

**Evidence (end-to-end, through the real `TrialsRegistry` and
`build_report_card`, not a re-implementation).** Nine genuinely dispersed
sibling runs plus one headline run, `configs/validation.yaml` unmodified
(`min_dsr: 0.95`). I then recorded additional backtests that are *cosmetic*
re-parameterisations of the headline — byte-identical `net_returns`, differing
only in `initial_capital`, which is enough to change `_canonical_hash(backtest_
config)` and mint a new registry key (`registry.py:288`):

| headline mean monthly return | cosmetic reruns | N | DSR | `min_dsr` gate |
|---|---|---|---|---|
| 0.0070 | 0 | 10 | 0.8650 | FAIL |
| 0.0070 | 15 | 25 | 0.9522 | **PASS** |
| 0.0075 | 0 | 10 | 0.9024 | FAIL |
| 0.0075 | 15 | 25 | 0.9647 | **PASS** |
| 0.0080 | 0 | 10 | 0.9310 | FAIL |
| 0.0080 | 15 | 25 | 0.9734 | **PASS** |

The strategy is unchanged in every row. Only the registry contents differ. With
40 reruns the same book reads DSR `0.9872`. The degenerate end is worse: when
every recorded trial shares one Sharpe, `var_sr_trials` is exactly `0`,
`deflated_sharpe_ratio` takes the `var_sr_trials == 0 → SR* = 0` branch
(`deflated_sharpe.py:105-106`) **at any N**, and DSR collapses to `PSR(sr, 0)`:
measured `0.999641` identically at `N = 2, 10, 100, 100000`. Two runs that
differ only in `benchmark:` or `initial_capital` produce exactly that state.

**Required remedy.**
(a) Delete the "over-counting N is conservative" claim from `registry.py`'s
docstring and from `_REGISTRY_BASE_POINT_NOTE`; it is false as implemented and
it is currently printed to the reader as reassurance.
(b) `n_trials` must not count trials that cannot have been an independent
search. At minimum, deduplicate on the *return series* (or its hash), not on
the config hash, before both `n_trials` and `var_sr_trials`: two keys whose
`net_returns` are identical are one trial. Record the collapsed count and the
raw key count separately so the report can show both.
(c) The `var_sr_trials == 0 → SR* = 0` branch must be restricted to
`n_trials == 1`, or guarded by a minimum number of *distinct* finite trial
Sharpes. `V̂ = 0` from a handful of duplicated draws is not evidence that the
true dispersion is zero, and as written it disables the deflation entirely at
arbitrarily large `N`. Where the guard fires, DSR should be NaN and the gate
should fail with a reason naming the cause.
(d) State the `N` actually used, as a number, in the DSR gate reason (see
finding 8).

---

## 2. [BLOCKER] The Reality Check corrects for fewer trials than the registry holds, and can run over a single trial

**Risk.** `build_trial_matrix` builds its columns as
`{r.key[0]: registry.load_series(r) for r in records}` (`reality_check.py:64`).
`key[0]` is the `strategy_id` alone — the first of the three key slots the M05
carried item deliberately made three. Every trial that shares a `strategy_id`
but differs in `data_semantics_version` or `backtest_config_hash` therefore
collapses into one column, and the survivor is whichever record happened to be
read last. `K` — the number of trials White's and Hansen's max-over-trials
statistic is taken over — silently under-counts exactly the reruns the
three-part key was introduced to distinguish, which makes both the RC hard gate
and the SPA soft gate easier to pass. The `len(records) < 2` guard
(`reality_check.py:59`) is applied to the pre-collapse record list, so it does
not catch the case it exists to catch.

**Evidence.** Four distinct registry keys in one family — three runs sharing
`strategy_id="momentum-deadbeef01"` under different backtest configs with
genuinely different return series, plus one run under a different
`strategy_id`:

```
registry distinct keys (n_trials): 4
records with a stored series     : 4
build_trial_matrix columns (K)   : 2   ['momentum-deadbeef01', 'momentum-cafebabe02']
```

And the degenerate case — two records, one `strategy_id`, two different series:

```
records: 2   matrix K: 1
RC  p = 0.005   n_trials field = 1
SPA p = 0.005   n_trials field = 1
```

A Reality Check whose maximum is taken over one trial applies no
multiple-testing correction at all, yet `reality_check_pvalue` is a **hard**
gate and `p = 0.005` passes it.

**Required remedy.** Label columns by the full three-part key (or a stable
digest of it), not `key[0]`. Move the `< 2` guard to after the matrix is built
so it counts columns. Surface the realised `K` in the RC and SPA gate reasons
and assert in a test that `K` equals the number of distinct registry keys with a
stored series.

---

## 3. [BLOCKER] The Reality Check's benchmark silently becomes zero when `--benchmark` is omitted, while every other benchmark gate keeps using the embedded series

**Risk.** `build_report_card` sets
`benchmark_for_rc = benchmark_result.net_returns if benchmark_result is not None
else None` (`report_card.py:342`), and `build_trial_matrix` treats `None` as a
**zero** benchmark (`reality_check.py:29-30`, `74-75`). But
`metrics.summary()` falls back to `result.benchmark_returns` when no separate
benchmark result is supplied (`metrics.py:361-366`), and so do the
`net_sharpe_vs_benchmark` hard gate and `min_track_record_length`. So a single
report card can test "does the best trial beat SPY" on one gate and "does the
best trial make money at all" on another, from the same inputs, with nothing in
the output saying which. The choice is made by whether the operator typed
`--benchmark`, not by `configs/validation.yaml`; the packet asked for the
benchmark to be a stated choice.

**Evidence.** Six trials, one 144-month SPY-like benchmark series embedded in
every result, identical in both rows:

| RC benchmark | White RC p-value | vs the `max_rc_pvalue: 0.10` hard bar |
|---|---|---|
| zero (what `build_report_card` uses with no `--benchmark`) | 0.000 | PASS |
| the SPY series the result already embeds | 0.272 | FAIL |

**Required remedy.** Fall back to `result.benchmark_returns` for the RC/SPA
matrix exactly as `metrics.summary` does, so the whole card speaks about one
benchmark. Add an explicit `reality_check_benchmark: spy | zero` key to
`configs/validation.yaml` and print the resolved choice in the RC and SPA gate
reasons.

---

## 4. [BLOCKER] `cv_sharpe` never reads the training sets, so purge and embargo cannot change the number the gate reads — and the gate is named as if they do

**Risk.** `cv_sharpe` discards the training positions (`purged_cv.py:123`:
`for _train_positions, test_positions in splits`) and reports the Sharpe of each
contiguous test block of the already-realised `net_returns`. Nothing is fitted,
so nothing can leak, so the purge and the embargo are inert. The gate is called
`purged_cv_mean_oof_sharpe` and its reason string reads "mean purged/embargoed
out-of-fold Sharpe" — a claim of leakage-controlled out-of-sample evidence about
a statistic that is a contiguous-sub-period consistency check on a strategy
whose parameters were chosen on the whole sample. Every fold is in-sample with
respect to the search. A reader of the report card, and any later milestone
quoting it, will over-read this line.

**Evidence.** Same 144-month series, four wildly different split sets:

| splits | mean OOF Sharpe | train sizes |
|---|---|---|
| `embargo=1` (shipped) | 0.7817692617 | [115, 115, 115, 115, 112] |
| `embargo=40` | 0.7817692617 | [76, 76, 76, 84, 112] |
| `label_horizon=24` | 0.7817692617 | [115, 92, 92, 92, 89] |
| train = **every** row (deliberate total leakage) | 0.7817692617 | [144, 144, 144, 144, 144] |

Identical to ten decimal places, including under a training set that contains
the test fold itself. The packet's acceptance criterion 3 is satisfied by tests
on `purged_kfold_splits` alone, which is why this was not caught.

**Required remedy (in-loop, disclosure).** Rename the gate to what it measures
(e.g. `subperiod_sharpe_consistency`) or, if the name is kept, make the reason
string state plainly that no model is refitted per fold, that the purge and
embargo do not affect the value, and that the folds are not out-of-sample with
respect to parameter selection. Add a `known_caveats` entry saying the same.
Pin the inertness with a test asserting the value is invariant to `embargo` and
`label_horizon`, so nobody later assumes otherwise.

**ESCALATE-TO-HUMAN (design, for Alex — do not loop on this).** The packet
itself specifies `cv_sharpe(returns, splits)`, a signature that cannot use
training data, so a real purged CV is out of reach without changing the packet.
The question for Alex is whether M06 should ship a purged-CV *apparatus* that
demonstrably does nothing, or whether the genuine article — refit the strategy's
parameters on each training fold and score the held-out fold, which needs the
backtest engine and is a materially larger piece of work — belongs in M07/M08.
I recommend the latter eventually; for now the disclosure fix above is the
minimum that stops the report card overclaiming.

---

## 5. [BLOCKER] `ELIGIBLE_FOR_PAPER` is unreachable through the shipped CLI, and two registry requirements from the packet have no product caller

**Risk.** The milestone's stated goal is the platform's decision function.
Through `quantlab validate --full` it currently has one reachable outcome.

**Evidence.** `grep` across `src/` and `tests/`: `record_sensitivity` and
`seed_historical_blend_trials` are called **only** from `tests/`. No product
code path records a sensitivity grid point or pre-loads the Phase 3 five-weight
blend sweep, both of which the packet requires
(`plans/M06-validation-2.md`, the `registry.py` bullet). `--full` also passes
neither `sensitivity=` nor `walk_forward=` to `build_report_card`
(`cli.py:180-187`), so `no_cliff_score` fails by construction on every CLI run
and `walk_forward_stability` is always vacuous.

Running the real CLI on a deliberately excellent fixture strategy — 144 months,
annualised Sharpe ≈ 2.0, max drawdown well inside the floor, PSR = 1.0:

```
verdict: REJECTED   n_trials: 1   psr: 1.0   dsr: nan   rc: None   spa: None
  [hard FAIL] deflated_sharpe_ratio        <- var_sr_trials NaN at N=1
  [hard FAIL] reality_check_pvalue         <- fewer than 2 trials with a series
  [soft FAIL] no_cliff_score               <- --full never passes a grid
  [soft FAIL] capacity_ceiling
  [soft FAIL] spa_pvalue
```

Two hard gates fail on the first run of any strategy, so `REJECTED` is the only
attainable verdict until something outside the product populates the registry.
Worse, the verdict then depends on how many unrelated backtests happen to share
`reports_dir`. `tests/test_cli_validate.py:106` asserts only
`verdict in {REJECTED, RESEARCH_ONLY, ELIGIBLE_FOR_PAPER}`, which is a tautology
and is why the suite is green.

The direction here is safe — the decision function is over-conservative, not
permissive — but the milestone does not deliver a working decision function.

**Required remedy.** Wire `record_sensitivity` and
`seed_historical_blend_trials` into the product path (a `validate --full`
that is given a grid, or a `registry` CLI subcommand, or both), pass
`sensitivity`/`walk_forward` through `--full` when available, and replace the
tautological CLI assertion with one that pins the expected verdict for a
fixture built to earn it.

---

## 6. [BLOCKER] Carried M04 verdict item 1 is not closed: the dirty-tree flag never reaches the report card

**Risk.** The binding carried item (packet, "Carried from the M04 verdict",
item 1) requires that "a dirty-tree trial is recorded but flagged, **and the
report card's provenance section says so**". `registry.py`'s own docstring
repeats the promise: "`report_card.py` surfaces it in the provenance section."

**Evidence.** `grep -n "dirty" src/quantlab/validation/report_card.py
src/quantlab/cli.py` returns nothing. `ReportCard` has no provenance section and
no field carrying `quantlab_git_sha`, `dirty` or `dirty_source`
(`report_card.py:233-268`). The registry half of the item is implemented and
tested; the reporting half is absent, and the docstring asserts otherwise.

**Required remedy.** Add a provenance block to `ReportCard` carrying
`quantlab_git_sha`, `dirty`, `dirty_source` and the trial count broken down by
`dirty`, render it in `report_card.md`, and add a `known_caveats` entry when any
counted trial is dirty. Correct `registry.py`'s docstring either way.

---

## 7. [NON-BLOCKING, fix in cycle 2] RC and SPA are over-sized at the shipped block length, and the calibration test cannot see it

**Risk.** The RC p-value gates a hard REJECT. On i.i.d. data at the shipped
`bootstrap.block_len: 6.0`, its actual size at the 0.10 bar is about 0.12, i.e.
roughly 25% more false "significant" verdicts than nominal. The test that is
supposed to certify calibration runs 200 simulations, which lacks the power to
detect it.

**Evidence.** 600 simulations per row, `b=200`, i.i.d. `N(0, 0.03)` columns,
Monte Carlo standard error on a 0.10 rate ≈ 0.012:

| setting | RC size at 0.10 | SPA size at 0.10 | RC mean p | RC KS p vs U(0,1) |
|---|---|---|---|---|
| T=144, K=10, `block_len=6.0` (shipped) | 0.123 | 0.128 | 0.453 | 0.0000 |
| T=40, K=4, `block_len=3.0` (the suite's own test) | 0.125 | 0.128 | 0.469 | 0.0070 |
| T=144, K=10, `block_len=1.0` (i.i.d. resampling) | 0.092 | 0.105 | 0.485 | 0.3328 |

The `block_len=1` row confirms the statistic itself is correctly built — the
miscalibration comes entirely from the block length on i.i.d. input. Note the
middle row: at 600 simulations the suite's *own* settings give KS p = 0.0070,
below the suite's own `ks_p > 0.01` assertion. Real monthly returns are not
i.i.d., so `block_len=6.0` may still be the right choice; what is not acceptable
is an in-tree test that certifies calibration it cannot measure.

Separately, `p_value = float(np.mean(boot_stats >= observed_stat))`
(`reality_check.py:125`, `170`) can return exactly `0.0`, which is not an
attainable p-value under a continuous null and biases p downward by about
`1/(B+1)`. Use the standard `(1 + count) / (B + 1)`.

**Required remedy.** Switch to `(1 + count) / (B + 1)`. Either raise the
calibration test's simulation count until it has power at the shipped
`block_len` and record the measured size, or change the test to assert a size
bound at the gate's own bar (`P(p ≤ 0.10) ≤ 0.13`, say) rather than full
uniformity, and document the measured over-sizing in the RC gate reason.

## 8. [NON-BLOCKING, fix in cycle 2] The markdown report card omits most of what a referee needs

All of the following are in `report_card.json` or in `basic.flags` but absent
from `_report_card_markdown` (`cli.py:249-266`), which renders only the gate
table and `known_caveats`:

- **`N` is never printed as a number.** The DSR gate reason says "after
  correcting for N trials" — the literal letter, not the value
  (`report_card.py:444`). The realised RC/SPA `K` and the RC's `n_periods` are
  likewise unstated.
- **`DSR = NaN` is indistinguishable from `DSR` failing.** The RC gate has a
  distinct "could not be run" reason; the DSR gate prints
  "DSR=nan against the 0.95 bar for significance", which reads as a statistical
  failure when the truth is that the registry held too few trials.
- **The coverage/selection "untrusted fraction" sentence** (carried M04 item 3,
  produced by `validate_basic` as `basic.flags[0]`) does not appear in
  `report_card.md`. It is the one line that tells a reader how much of the book
  is unmeasurable.
- **The Sharpe/Sortino denominator convention** (carried M05 item 8: Sortino
  target 0 at ddof=0, Sharpe at ddof=1) is stated nowhere in the report card or
  the CLI, yet `_validate_one_liner` prints the two side by side
  (`cli.py:277-280`). Carried M05 item 8 is **not** closed.
- **Capacity's spread percentiles** (p10…p99, full and half) are computed and
  serialised but never rendered, though the packet asks for them in the output.

## 9. [NON-BLOCKING] "Intended capital" is the backtest's notional, and the 100× bar will bind on real data

`intended_capital = result.provenance["backtest_config"]["initial_capital"]`
(`report_card.py:638`). **The default is $1,000,000**
(`backtest/config.py:38`), so the shipped `capacity_min_multiple_of_intended_
capital: 100.0` means a $100M floor on `capacity_ceiling_min` — the *most*
conservative of the four ceilings (5% participation at the ADV 10th percentile).
The old repo's own real-data range was $95M–$335M at an assumed 50-name book, so
the low end fails the bar; a 30-name book at ADV p10 reads $38M at 5%
participation and $75M at 10%. On real data this soft gate will almost certainly
fail and cap every strategy at RESEARCH_ONLY.

That is conservative and therefore acceptable, but two things should change:
`intended_capital` should be its own key in `configs/validation.yaml` rather than
inherited from a backtest notional that means something else, and Alex should
set it deliberately (the real account is a retail Trading212 account, nowhere
near $1M, which would make the gate trivially passable — the opposite failure).
State the resolved intended capital in the gate reason.

## 10. [NON-BLOCKING] Unequal trial windows are silently intersected with no floor

`build_trial_matrix` intersects all trials' indices and the benchmark's
(`reality_check.py:65-71`). Two 120-period trials overlapping by 60 produced a
`(60, 2)` matrix: half the headline strategy's own history was dropped from the
test that gates its rejection, with no flag. The only guard is "intersection is
non-empty", so a 3-period overlap would still produce a p-value the hard gate
acts on. Add a minimum-common-periods threshold to
`configs/validation.yaml` and put `n_periods` and the fraction of the headline
window retained into the RC and SPA gate reasons.

## 11. [NON-BLOCKING] Two carried disclosure items are only half-wired

- **Carried M04 verdict item 2** requires the extreme-return counts "beside
  PSR/DSR". `_extreme_return_caveat` is appended to the **DSR**
  (`report_card.py:449`) and **MinTRL** (`report_card.py:510`) gate reasons but
  **not** to the PSR gate's, even though PSR consumes the same truncated
  `skew`/`kurt`. One line to add.
- **Carried M05 verdict item 2** requires the sensitivity result's `edge` /
  `nan_points` flags to be respected in the gate reasons. `nan_points`,
  `neighbourhood_size` and `neighbourhood_truncated` appear nowhere in
  `report_card.py`, so an edge-truncated or NaN-contaminated `no_cliff_score` is
  quoted with the same confidence as an interior one. The `min_net_sharpe`
  pairing half of that item **is** correctly implemented.

---

## Answers to the specific questions put to this gate

- **Is `N` a defensible lower bound?** As documented, yes; as computed, no —
  see finding 1. It is a lower bound on *searches* only if duplicate-return
  trials are collapsed first, which they are not.
- **Is the sensitivity base point double-counted?** Yes, deliberately and
  explicitly (`registry.py` docstring). The disclosure is correct; the claim
  that the direction is conservative is not (finding 1).
- **Is the historical five-weight blend sweep loaded?** Implemented and tested,
  but never called by product code (finding 5).
- **Does DSR fail for many trials and a modest Sharpe?** Yes —
  `N=200, V=0.05` on an annualised-Sharpe-1.0 book gives DSR `0.0001`.
- **Is the CV label horizon the rebalance holding period?** Yes, `label_horizon`
  defaults to 1 and `build_report_card` takes the default; the embargo is
  config-driven (`bootstrap.purged_cv_embargo`). Both are moot given finding 4.
- **Is the OOF Sharpe on the per-period footing?** No — `cv_sharpe` annualises
  (`periods_per_year=m.periods_per_year`). Harmless because the threshold is
  `0.0` and annualisation preserves sign, but it is the one gate on a different
  footing from PSR/DSR/MinTRL and the reason string does not say so.
- **Which benchmark do RC/SPA use, and is it config?** Zero unless
  `--benchmark` is passed, and it is not config (finding 3).
- **Does the registry supply per-trial series aligned on common dates?** Yes,
  but keyed on `strategy_id` alone (finding 2) and intersected without a floor
  (finding 10).
- **Synthetic-null uniformity, planted alternative, SPA ≤ RC?** Statistic
  construction verified; calibration over-sized at the shipped block length
  (finding 7). SPA ≤ RC held in 40/40 independent datasets.
- **Monte Carlo.** Bootstrap parameter `1/L` correct, percentiles correct,
  `P(worse drawdown)` uses a strict `<` with a documented and correct reason,
  reproducible under seed. No finding. Note only that the gate sits at 0.5, the
  approximate centre of the statistic's own null, so it is close to a coin flip;
  it is a soft gate, so the cost is a cap at RESEARCH_ONLY.
- **Capacity.** Verbatim port confirmed; the old repo's $95M–$335M range is
  cited in the docstring but **not** reproduced in-tree — the parity test
  reproduces the *implementation* on a synthetic fixture, which is what the
  packet asked for. Intended capital and the 100× bar: finding 9.
- **Hard vs soft gates, thresholds from YAML, missing inputs fail.** All correct.
  Every gate reads through `thresholds.get(...)`; no hardcoded comparison; soft
  failures cap at RESEARCH_ONLY; missing RC/SPA/capacity/sensitivity inputs fail
  rather than pass. Coverage bound is 15%. `net_sharpe_vs_benchmark` uses
  annualised on both sides from the same `MetricsSummary`. Reasons are populated
  on every gate.
