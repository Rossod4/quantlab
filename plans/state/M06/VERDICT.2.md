VERDICT: REJECT

M06 cycle 2. This is a much narrower REJECT than cycle 1, and the orchestrator
should read it as such before deciding whether to run a third cycle or escalate.

Five of my six cycle-1 blockers are fully closed and independently re-verified
against the current tree. The sixth (finding 1, DSR) is materially improved and
its worst case is now bounded, but a reachable residual remains. One NEW
permissive hole was introduced by iteration 3's fix for my cycle-1 item 10, and
that is what makes this a REJECT rather than an ACCEPT-with-carried-items.

The single blocking finding below (A) has a small, well-specified remedy — a
few lines in `report_card.py`/`reality_check.py` plus one test. I would expect
one focused iteration to close it. I am recording that estimate explicitly so
whoever decides between a third cycle and an escalation to Alex has it.

Suite re-run at this tree: `uv run pytest tests/ -q` exit 0, 522 tests,
`ruff check` and `ruff format --check` clean (97 files). I mutated no source or
test file; `git status --short` differs from the frozen tree only by
`plans/QUANT-NOTES.md` and this file.

---

## A. [BLOCKER, NEW] The headline strategy can be excluded from its own Reality Check, and the hard gate then passes on other trials' behalf

**Risk.** Iteration 3's `_resolve_overlap` (`reality_check.py:82-181`) correctly
solves the silent-truncation problem I raised as cycle-1 item 10, but it treats
every trial as an equally disposable removal candidate — including the headline
trial, the one strategy the report card exists to judge. When the headline's own
date window is offset from the majority of its family's recorded trials, the
resolver drops the headline, the Reality Check runs over the survivors, and
`reality_check_pvalue` — a HARD gate — returns a verdict about strategies that
are not the one being validated. `build_report_card` records
`headline_retained_fraction` in provenance and pushes the exclusion sentence
into `known_caveats`, so the fact is discoverable, but nothing stops the gate
from answering, and the gate's own reason string does not say the headline is
absent.

**Evidence (permissive direction, through the real `build_report_card`).**
Three strong, mutually aligned trials on a 2014-01..2023-12 monthly window, plus
a headline result on an offset 2019-01..2028-12 window whose own returns are
worthless (mean 0.0002/month, per-period Sharpe ≈ 0):

```
headline_retained_fraction : 0.5
rc  K / best_trial / p     : 3  momentum-maj1  0.0050
RC HARD GATE               : PASS
SPA soft gate              : PASS
gate reason                : "White Reality Check p=0.0050 against the 0.10 bar,
                              over K=3 realised trials, benchmark=zero ..."
headline in the matrix?    : False
```

The data-snooping gate passed at p=0.0050 for a strategy it never examined. The
overall verdict in this particular fixture is still REJECTED, but only because
DSR and MinTRL independently fail on a near-zero Sharpe; a merely mediocre
headline would not be caught by those and would carry a passing Reality Check
into its report card.

**Also reachable in the conservative direction, with a false explanation.** When
the benchmark series is what constrains the common window, `_resolve_overlap`
reaches its "no single removal helps" branch, drops every remaining trial, and
`build_trial_matrix` raises. Because the raise happens before the tuple unpack
at `report_card.py:485`, `rc_excluded` and `retained_fractions` are both
discarded: `headline_retained_fraction` reads `None`, no exclusion caveat is
emitted at all, and the RC gate reason reads "Reality Check could not be run
(fewer than 2 registered trials with a stored return series)" — which is not
what happened. Measured on a four-trial registry where every trial had a stored
series.

**Required remedy.**
1. Pin the headline trial as never-removable in `_resolve_overlap` (pass its
   label in; exclude it from the removal-candidate set). If the headline cannot
   be retained above the floor, the Reality Check must FAIL with a reason naming
   that cause, never run without it.
2. Assert the invariant in `report_card.py`: if `rc` is not None, the headline
   label is a column of the matrix. A test should plant the offset-headline case
   above and pin the gate to FAIL-with-named-reason.
3. Capture `excluded`/`retained_fractions` even when `build_trial_matrix`
   raises (return them on the exception, or resolve overlap before the
   matrix build), and give the `rc is None` path a reason that distinguishes
   "fewer than two trials recorded" from "excluded by the overlap floor" from
   "no common dates".

---

## B. [NON-BLOCKING, carry] Finding 1's residual: near-duplicate reruns of one trial still move the DSR hard gate across its threshold

Iteration 3's two mechanisms both work and both are correctly documented. The
return-series hash dedup completely neutralises the exact case I demonstrated at
cycle 1, and the `1/(n_periods-1)` variance floor (correct as a Lo 2002
small-sample null variance, and on the right per-period footing) bounds the
damage and restores monotonicity once it binds. Critically, the *normal*
workflow is now correct.

Byte-identical cosmetic reruns — cycle 1's exact reproduction, now flat:

| headline mean | reruns 0 | 5 | 15 | 30 | 40 |
|---|---|---|---|---|---|
| 0.0075 | DSR 0.9024 FAIL | 0.9024 FAIL | 0.9024 FAIL | 0.9024 FAIL | 0.9024 FAIL |

N stays at 10 distinct while the raw key count rises to 50. Exactly right.

Replicating the WHOLE sensitivity grid under successive 1bp cost changes — the
workflow `--full` now produces automatically — is also right, and moves in the
correct direction:

| cost levels | 1 | 2 | 3 | 5 | 8 |
|---|---|---|---|---|---|
| N | 10 | 19 | 28 | 46 | 73 |
| DSR | 0.9024 | 0.7769 | 0.6799 | 0.5456 | 0.4229 |

The residual is narrower than cycle 1's and needs many near-duplicates of ONE
point rather than of the grid. Re-running only the headline under successive 1bp
cost changes (a real, deterministic shift, not contrived jitter):

| headline reruns | 1 | 3 | 6 | 10 | 16 | 25 | 40 |
|---|---|---|---|---|---|---|---|
| N | 10 | 12 | 15 | 19 | 25 | 34 | 49 |
| var_sr_trials | 0.0234 | 0.0197 | 0.0157 | 0.0123 | 0.0092 | 0.0070 | 0.0070 |
| DSR | 0.9024 | 0.9167 | 0.9356 | **0.9537** | 0.9696 | 0.9796 | 0.9715 |
| `min_dsr` gate | FAIL | FAIL | FAIL | **PASS** | PASS | PASS | PASS |

The gate flips at about ten reruns and peaks at 0.9796 before the floor binds
(0.006993 = 1/143) and the curve turns back down. So the hole is bounded, but
"I nudged my cost assumption a dozen times on my headline strategy, then
validated" still moves the platform's central bias guard across its threshold.

I am NOT blocking on this. The mechanism is inherent to estimating Bailey &
López de Prado's `V[SR]` from recorded trials, the direction is bounded, and
`registry.py`'s docstring is now honest — it claims the fix only for the
at-or-below-floor regime and no longer asserts general monotonicity. Two things
are required in cycle 3 regardless: the report card must state that DSR is not
monotone in N in the above-floor regime (today nothing says so), and the
regression test must cover the near-duplicate path, not only the
byte-identical one it currently pins.

## C. [NON-BLOCKING] The orchestrator's own capacity decision is not implemented in the report

Decision (d) required `intended_capital_usd` to default to 1000 "with the report
required to say the capacity gate is trivially passable at a retail stake". The
default and the resolved-figure disclosure both landed — the gate reason reads
"worst-case capacity ceiling is 75000x the resolved intended capital ($1,000,
configs/validation.yaml intended_capital_usd) against the 100x bar". The
"trivially passable" half did not: grepping `trivially` and `retail` across
`report_card.py`, `cli.py` and `configs/validation.yaml` finds only a YAML
comment. A reader of the report card sees a capacity gate passing at 750x its
bar with nothing saying the bar is vacuous at this stake. Add the sentence to
the gate reason (or a `known_caveats` entry) whenever the multiple clears the
bar by more than an order of magnitude.

## D. [NON-BLOCKING, carried forward] RC/SPA over-sizing and the calibration test's power

The `(1 + count) / (B + 1)` estimator is in and works — the minimum attainable
p-value is now 0.00498 = 1/201 rather than exactly 0. It also shaved the
over-sizing slightly. 600 simulations per row, i.i.d. data, MC se on a 0.10 rate
≈ 0.012:

| setting | RC size at 0.10 | SPA size at 0.10 | RC KS p |
|---|---|---|---|
| T=144, K=10, `block_len=6.0` (shipped) | 0.117 (was 0.123) | 0.118 (was 0.128) | 0.0000 |
| T=40, K=4, `block_len=3.0` (the in-tree test's own settings) | 0.118 | 0.127 | 0.0121 |
| T=144, K=10, `block_len=1.0` (control) | 0.085 | 0.093 | 0.4029 |

The control row confirms again that the statistic itself is sound and the block
length is the whole story. **The in-tree calibration test still does not have
power at the shipped block length**: at its own settings, 600 sims put RC's KS
p at 0.0121, barely clearing its own `ks_p > 0.01` assertion, and SPA's at
0.0016. The developer explicitly declined to raise the simulation count and said
so rather than silently adjusting it, which is the right call — this remains
CARRIED, not closed. The measured over-sizing is documented in
`reality_check.py`. Real monthly returns are not i.i.d., so `block_len=6.0` may
well be the right choice; what is still missing is a test that measures size at
the gate's own bar instead of asserting a uniformity it cannot detect.

## E. [NON-BLOCKING, cosmetic] `{gate.value!r}` renders numpy scalars into the deliverable

`_report_card_markdown` uses `repr`, so the rendered table contains
`np.float64(1.0)` in the `no_cliff_score` row, and bare `nan` for Calmar and
Sortino in the headline metrics. Cosmetic, but this file is the human-readable
deliverable until M07 replaces it.

---

## Closed and re-verified this cycle

- **Cycle-1 finding 2 (RC under-counts trials) — CLOSED.** `_column_label` now
  joins the full three-part key. My cycle-1 reproduction: four distinct registry
  keys with four stored series, three of them sharing one `strategy_id`, now
  give a matrix with **K=4** (was K=2). Two records sharing a `strategy_id` give
  **K=2** (was K=1, a "reality check" over one trial). The `< 2` guard now runs
  on `matrix.shape[1]`.
- **Cycle-1 finding 3 (RC benchmark silently zero) — CLOSED.** With no
  `--benchmark` supplied, `provenance.rc_spa_benchmark_source` reads "embedded
  (result.benchmark_returns) - validation.yaml default" and the RC gate reason
  names it inline. On the six-trial fixture that produced cycle 1's p=0.000 vs
  p=0.272 split, the card now reports p=0.2687 against the embedded benchmark —
  the same benchmark every other gate uses. `reality_check.benchmark` is a real
  config key with an `embedded`/`zero` choice, and an explicit `--benchmark`
  result still overrides with a named reason.
- **Cycle-1 finding 4 (purged CV inert and misnamed) — CLOSED as disclosure, and
  better than I asked for.** Renamed to `subperiod_oof_sharpe`. The gate reason
  now reads "mean Sharpe 4.97 over 5 contiguous sub-periods of a strategy with
  NO FITTED PARAMETERS - purge/embargo have no effect on this value by
  construction; NOT a purged cross-validation", and a `known_caveats` entry says
  the same. I re-confirmed the underlying invariance is unchanged and now
  correctly advertised: 0.7817692617 identically under `embargo=1`,
  `embargo=40`, `label_horizon=24`, and a fully-leaking training set.
  `purged_kfold_splits` is retained, correct, and reserved for a future fitted
  strategy. **I accept the orchestrator's recorded decision (a)** — no fake CV
  ships, and the genuine refit-per-fold CV is carried post-v1. That reasoning is
  sound and I am not escalating it.
- **Cycle-1 finding 5 (ELIGIBLE_FOR_PAPER unreachable) — CLOSED.**
  `_make_sensitivity_runner` is a real engine-backed factory (monkeypatched only
  to keep the test offline), `--full` seeds historical trials, runs and records
  the sensitivity grid, and runs the walk-forward for blend families.
  `test_validate_full_reaches_eligible_for_paper_through_the_cli` runs the real
  CLI against the real `configs/validation.yaml` and asserts
  `failing == []` and `verdict == "ELIGIBLE_FOR_PAPER"`; the companion test pins
  REJECTED. The cycle-1 tautological assertion is gone. I rendered the resulting
  `report_card.md` end to end and read it in full.
- **Cycle-1 finding 6 (dirty flag never reached the report card) — CLOSED.**
  `ReportCard.provenance` carries `strategy_id`, `data_semantics_version`,
  `quantlab_git_sha`, `dirty`, `dirty_source`, `n_trials`, `n_trials_raw`,
  `dirty_trial_count`, `rc_trial_count`, `rc_spa_benchmark_source` and
  `headline_retained_fraction`, all rendered in a Provenance section of
  `report_card.md`, with a `known_caveats` entry when any counted trial came
  from a dirty tree. Verified live on a fixture with a planted dirty trial:
  `dirty=True`, `dirty_source='provenance'`, `dirty_trial_count=2`.
- **Cycle-1 item 8 (markdown completeness) — LARGELY CLOSED.** N is now printed
  as a number ("after correcting for N=14 distinct trials", plus the raw key
  count in provenance), K is printed on both the RC and SPA gates, the
  coverage/selection "untrusted fraction" sentence is in the Provenance section,
  and a new Headline metrics section prints Sharpe beside Sortino with the
  ddof=1-annualised / target-0-ddof=0 convention stated immediately below them.
  Capacity's spread percentiles remain JSON-only (out of scope per the handoff,
  fine for M07).
- **Cycle-1 item 9 (intended capital) — CLOSED as to mechanism.**
  `intended_capital_usd` is its own config key, no longer the backtest notional,
  and the gate reason states the resolved dollar figure. See C above for the
  half that is missing.
- **Cycle-1 item 10 (silent intersection truncation) — CLOSED, and the
  motivating case now works.** My own two-same-length-offset-windows case, which
  cycle 1 measured as a silent (60, 2) truncation: the resolver now excludes the
  offset trial with a named reason and the aligned majority **keeps its full 120
  periods** — matrix shape (120, 3), retained fractions
  `{offset: 0.5, maj0: 1.0, maj1: 1.0, maj2: 1.0}`. This is a genuine
  improvement. Finding A above is the cost of it.
- **Cycle-1 item 11 (half-wired carried disclosures) — CLOSED.** The
  extreme-return caveat is now on the PSR gate as well as DSR and MinTRL, and
  `neighbourhood_size`/`neighbourhood_truncated`/`nan_points` are appended to
  both the `no_cliff_score` and `min_net_sharpe` gate reasons.
- **The false "over-counting N is conservative" claim — REMOVED and correctly
  replaced.** The `known_caveats` base-point note now says over-counting is NOT
  generally conservative once `var_sr_trials` is estimated from the same trial
  set, and justifies the disclosure by the effect's small size rather than by a
  guaranteed direction. That is the right correction.

## Re-confirmed unchanged from cycle 1

The closed-form statistics were not touched by iteration 3 except for the
`SR* = 0` branch restriction, which I re-read: it is now `n_trials == 1` only,
and `var_sr_trials == 0` at N >= 2 flows through the general formula where
`sqrt(0) = 0` gives the same number by ordinary arithmetic without ignoring N.
That is the correct narrowing of what I asked for. PSR, MinTRL, White's
recentring, Hansen's threshold and the stationary bootstrap are unchanged and
were verified at cycle 1 to 0.0 absolute.
