VERDICT: REVISE

## Findings

1. **[blocker] `report_card.py:283-301` — PSR/DSR/MinTRL are called with mismatched
   footing (annualized Sharpe vs. per-period `n`/skew/kurt), contradicting
   `deflated_sharpe.py`'s own documented contract.**
   `deflated_sharpe.py`'s module docstring states: "`sr`/`sr_benchmark`/`sr_trials`
   must all be on the SAME footing (all annualized, or all per-period) as each
   other and as `n`'s implied frequency — this module never annualizes or infers
   a frequency itself." `build_report_card` violates this: it passes
   `m.net_sharpe` (ANNUALIZED — `MetricsSummary.net_sharpe` is
   `sharpe_ratio(net_returns, periods_per_year=periods_per_year)`, i.e. scaled by
   `sqrt(periods_per_year)`) into `probabilistic_sharpe_ratio`, `deflated_sharpe_ratio`,
   and `min_track_record_length`, alongside `n = len(net_returns)` (the RAW,
   un-annualized period count) and `skew`/`kurt` computed directly on the raw
   per-period `net_returns`. The formula's `√(n−1)` scaling and the
   `variance_factor` denominator are calibrated for a per-period SR estimated
   from `n` iid per-period draws (Lo 2002 / Bailey–López de Prado's own
   derivation) — plugging in an SR that has already been multiplied by
   `√(periods_per_year)` without correspondingly adjusting `n` inflates the
   z-score by roughly that same factor, making PSR/DSR/MinTRL spuriously easy
   to pass. Independently recomputed by hand (`numpy`/`scipy`, outside the
   module) on a synthetic monthly series (n=48, mean=0.006, vol=0.045,
   `var_sr_trials`=0.05, `n_trials`=10): the report_card.py convention (annualized
   SR, n=48) gives DSR≈0.256; the textbook-correct convention (per-period SR,
   same n) gives DSR≈0.029 — an order of magnitude apart, on opposite sides of
   a plausible `min_dsr` bar. The packet's own report-card fixtures don't catch
   this because they deliberately use saturated/extreme Sharpes (PSR/DSR pinned
   at 1.0 under either convention — see `test_report_card.py`'s own docstring
   on why the fixture Sharpe is "comfortably below" the ceiling but still very
   high). **Fix expected:** compute a per-period Sharpe (e.g.
   `net_returns.mean() / net_returns.std(ddof=1)`, matching `sharpe_ratio`'s own
   `ddof=1`) and pass THAT — consistently with `n = len(net_returns)` and
   per-period `skew`/`kurt` — into `probabilistic_sharpe_ratio`,
   `deflated_sharpe_ratio`, and `min_track_record_length`; keep `m.net_sharpe`
   (annualized) only for display/gate labels. This cascades into `registry.py`:
   `TrialRecord.net_sharpe` (used for `var_sr_trials`, i.e. `sr_star`'s
   dispersion input) is also currently annualized
   (`record_backtest`'s `sharpe_ratio(result.net_returns, periods_per_year=periods_per_year)`);
   it must move to the same per-period footing as whatever `sr` is compared
   against it, or the fix will just move the mismatch from one side of the
   `sr` vs. `sr_star` comparison to the other.

2. **[minor] `report_card.py:283-286` — pandas `.skew()`/`.kurt()` are the
   bias-corrected (unbiased, "G1"/"G2") sample-moment estimators, not the plain
   method-of-moments ("g1"/"g2") estimators the DSR literature and this repo's
   own tests assume.** `test_report_card.py`'s module docstring explicitly
   asserts "An exactly-alternating, equal-count two-point series has skew=0
   and (non-excess) kurtosis=1 exactly" as the basis for its fixture design.
   Independently checked: for the actual 60-point alternating fixture used
   there, `pandas.Series.kurt()` (bias-corrected) gives non-excess kurtosis
   ≈0.9298, not 1.0 exactly (`scipy.stats.kurtosis(fisher=False, bias=True)`
   gives exactly 1.0, confirming the biased/plain estimator is what the
   test's own reasoning relies on). This doesn't currently break any
   assertion (no test asserts the literal kurtosis value), but the
   documented reasoning in the test file is quietly wrong about what the
   code computes, and — more importantly — this convention question is
   entangled with finding 1's fix, since whichever skew/kurt convention is
   chosen needs to be stated and matched consistently once the footing bug
   is corrected. Worth reconciling in the same pass (either switch to
   `scipy.stats.skew(..., bias=True)` / `kurtosis(..., fisher=False, bias=True)`
   to match the literature, or explicitly document why the bias-corrected
   pandas convention is intentional and correct the test docstring's claim).

## Verified correct (no findings)

- **PSR/DSR/MinTRL formulas themselves** (`deflated_sharpe.py`): recomputed
  independently in `numpy`/`scipy` outside the module — PSR's z-score,
  variance-factor, DSR's `SR*` (Euler–Mascheroni term), and MinTRL all match
  Bailey & López de Prado's equations exactly, to the same tolerance the
  module produces. `PSR(SR=SR*)=0.5` confirmed; DSR decreases monotonically
  in `n_trials` confirmed (0.999→0.997→0.993→0.976→0.947→0.897 for
  N=2,5,10,50,200,1000); the `var_sr_trials==0` special case reduces exactly
  to `PSR(sr, 0, n, skew, kurt)` at both `n_trials=1` and `n_trials=5`,
  confirmed. Sharpe itself uses pandas `ddof=1`, consistent with the M05
  carried item.
- **Purged K-fold** (`purged_cv.py`): independently brute-forced with the
  exact requested parameters (100-period index, `n_splits=5`, `embargo=3`,
  `label_horizon=2`) — no train index falls in `[test_start−h+1, test_end+embargo)`
  for any fold; folds partition the index exactly (no gaps/overlaps);
  `embargo=0, label_horizon=1` reduces to plain contiguous K-fold exactly.
  The packet's own negative test (`test_assertion_detects_a_deliberately_unpurged_split`)
  proves the leakage assertion is not vacuous.
- **Stationary bootstrap** (`bootstrap.py`): continuation probability is
  `1 − 1/block_len` (i.e. the geometric parameter is `1/L`, not `L`) —
  correct per Politis & Romano; wrap-around indexing confirmed; `block_len=1`
  reduces to exactly the "restart" (iid) draw, verified both by the module's
  own test (reproducing the RNG draw sequence by hand) and independently.
- **White Reality Check / Hansen SPA** (`reality_check.py`): re-ran the
  synthetic-null KS test with a different seed (999, not the suite's 0) —
  KS p=0.56 (well above the 0.01 bar), confirming the calibration isn't an
  artifact of the seed the tests happen to use. Planted-alternative p and
  best-trial identification reproduced. SPA's "consistent" recentering
  (threshold `−√(2 ln ln T)`) matches Hansen (2005) eq. 16–17; SPA ≤ RC
  reproduced directionally on a second, independently constructed dataset.
- **Capacity parity** (`capacity.py` / `test_capacity_parity.py`): the ported
  `corwin_schultz_spread` is byte-for-byte identical (beta/gamma/alpha/k
  algebra, floor-negative-alpha, median reduction) to
  `..\MomentumValueStrategy\scripts\cost_realism_analysis.py`'s own function,
  confirmed by direct comparison of both source files (only `l`→`low_arr` and
  title-case→lowercase column renames differ). The capacity-ceiling arithmetic
  (`participation * adv / position_frac`) is likewise identical. Golden test
  passes to 1e-9.
- **Registry** (`registry.py`): idempotence, changed-param increment,
  semantics-version-change increment, and changed-backtest-config-hash
  increment all independently re-derived from the test file and consistent
  with the M05-carried three-part key. `dirty_source` exercised on both
  branches (`provenance` vs. `registry_at_record_time`) with a test proving
  the provenance branch isn't accidentally hitting the same fallback value.
  The five historical Phase 3 blend trials are pre-seeded, idempotent, NaN-Sharpe,
  and excluded from `var_sr_trials`/Reality Check's matrix as documented.
- **Report card gates**: three fixtures produce REJECTED / RESEARCH_ONLY /
  ELIGIBLE_FOR_PAPER as required; every gate's `reason` is non-empty in all
  three; the coverage-threshold test flips the verdict via a config-only
  change; RC/SPA missing-input paths fail (not silently pass) as documented;
  capacity's missing-ticker names are threaded through
  `price_panel_missing_tickers` end-to-end (confirmed in the CLI test, not
  just report_card.py in isolation); soft-gate failures cap at
  RESEARCH_ONLY, never REJECTED (`_evaluate_gates`'s `hard_failed`/`soft_failed`
  logic). Grepped every gate for a hardcoded numeric comparison — none found;
  all read through `thresholds.get(...)`.
- **CLI `--full` end-to-end**: runs on a fixture result + temp platform/cache
  config; network isolation is a real assertion, not a mock stub — 
  `_download_batch` is monkeypatched to raise `AssertionError` on any call,
  and the warm-cache test passes without tripping it. The missing-ticker
  test confirms a per-ticker (not whole-batch) failure is correctly isolated
  by the underlying `YFinancePriceProvider`, so only the genuinely-missing
  ticker is named in the gate reason.
- **Suite time / hygiene**: `uv run pytest tests/ -q` — exit 0, 506 dots
  (matches the handoff's count exactly), ~18–19s wall time, well under the
  90s budget. `uv run ruff check` and `uv run ruff format --check` both
  clean. `uv run quantlab validate --help` shows `--full`/`--platform`
  wired as documented. All eight new/changed validation modules carry
  `from __future__ import annotations`; `BootstrapConfig` is a proper
  pydantic `BaseModel` with `extra="forbid"`, consistent with the rest of
  `basic.py`.

## Scope note

Item 2 above (skew/kurt bias convention) is arguably quant methodology
rather than a pure code-correctness bug, and would normally be quant-gate's
call rather than code-review's — flagged here only because it's directly
entangled with finding 1's fix (both concern the same two lines) and because
the team-lead's brief for this iteration specifically asked for the PSR/DSR
formulas to be checked against the literature. No other quant-methodology
opinions are offered.
