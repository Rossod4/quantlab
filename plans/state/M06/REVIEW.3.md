REVIEW: APPROVE

## Findings

All six quant-gate blockers, plus items 7-9 and the addenda, are fixed and
independently reproduced. No new findings from the code-review side (formula
correctness/regression checks below; methodology re-litigation is the gate's
job, not repeated here).

1. **[verified fixed] DSR-rises-with-N gaming.** Reproduced the gate's exact
   9-sibling-plus-headline scenario independently (standalone script, not the
   test file): raw registry key count grows 10→25→50 across 15/40 cosmetic
   `initial_capital`-only reruns of the headline, but `n_trials()` (deduped by
   `series_hash`) stays fixed at 10, `var_sr_trials` stays fixed at 0.68169,
   and DSR stays fixed at 0.7206 - FAIL throughout, matching
   `test_dsr_stays_failed_after_15_and_40_byte_identical_cosmetic_reruns`
   exactly. Confirmed `var_sr_trials(family, n_periods)` floors at
   `1/(n_periods-1)` on the PER-PERIOD field (registry.py:534-567) - genuinely
   distinct trials sharing an identical per-period Sharpe read `v_hat=0`
   before the floor, `1/(n-1)` after
   (`test_var_sr_trials_floors_at_null_sampling_variance` passes). Confirmed
   `deflated_sharpe_ratio`'s `SR*=0` shortcut now fires only at `n_trials==1`
   (deflated_sharpe.py:113-116); at `n_trials>=2` a literal `var_sr_trials=0`
   flows through the general formula (`sqrt(0)=0`) rather than being
   special-cased, per the binding "do not restore" comment. The false
   "over-counting is conservative" claim is deleted from both
   `registry.py`'s docstring and `_REGISTRY_BASE_POINT_NOTE`.
2. **[verified fixed] RC/SPA undercounting trials.** `build_trial_matrix`
   labels columns by the full three-part key (`_column_label`, joined with
   `|`), and the `<2` guard now runs on `matrix.shape[1]`
   (reality_check.py:60-68, 226-231).
   `test_build_trial_matrix_labels_columns_by_full_key_not_strategy_id_alone`
   reproduces the gate's exact case (3 trials sharing one `strategy_id`,
   distinguished only by `backtest_config_hash`) and gets `K=4` (matrix shape
   `(24, 4)`), not the pre-fix `K=2`.
3. **[verified fixed] RC/SPA silently-zero benchmark.** Independently ran the
   gate's own scenario outside any test (6 trials, one embedded SPY-like
   benchmark series, no `--benchmark` override) directly against
   `build_report_card`: default (`reality_check.benchmark: embedded`, the
   shipped config) gives RC p=0.3522 (over K=6); explicitly setting the config
   to `benchmark: zero` on the SAME data gives RC p=0.0033 - an order of
   magnitude apart, confirming the choice is genuinely config-driven (not a
   hardcoded fallback) and the resolved source string differs accordingly
   ("embedded (result.benchmark_returns) - validation.yaml default" vs. "zero
   (configs/validation.yaml: reality_check.benchmark=zero)"). The magnitude
   differs from the gate's own cited "p ≈ 0.272" only because I used a
   different synthetic seed/window than the gate's fixture; the DIRECTION and
   MECHANISM (near-zero-p under a zero benchmark vs. a much larger p under the
   real embedded benchmark) reproduce exactly what the finding describes.
4. **[verified fixed] Inert/mislabelled purged CV.** `cv_sharpe`/
   `PurgedCVResult` renamed to `subperiod_oof_sharpe`/`SubperiodOOFResult`
   (purged_cv.py), with the module docstring, the gate's reason string, and a
   `known_caveats` entry (`_SUBPERIOD_OOF_CAVEAT`) all stating plainly that no
   model is refit per fold and purge/embargo cannot change the value.
   `test_subperiod_oof_sharpe_is_invariant_to_embargo_and_label_horizon`
   passes; `purged_kfold_splits` itself is kept unchanged (still independently
   verified correct from iteration 1/cycle-1 review) for a future fitted
   caller. This matches the orchestrator decision recorded in
   `plans/QUANT-NOTES.md` under "Orchestrator decisions" - disclosure fix
   in-loop, the design question (a genuine refit-per-fold CV) correctly left
   for a later milestone, not silently built here.
5. **[verified fixed] ELIGIBLE_FOR_PAPER unreachable via the CLI.** Grepped
   `src/` and `tests/` for `record_sensitivity(`/`seed_historical_blend_
   trials(` - both are now called from `src/quantlab/cli.py` (lines 208, 312),
   not only from test files, closing the gate's exact "called only from
   tests" evidence. `validate --full` now: seeds the five historical blend
   trials idempotently every run; runs the sensitivity grid through a real,
   monkeypatchable engine-backed runner
   (`_make_sensitivity_runner`/`_build_sensitivity_result`) gated by
   `sensitivity_enabled`/`--no-sensitivity`; records every grid point into the
   registry; and wires `walk_forward`/`sensitivity` through to
   `build_report_card`. Ran the actual pinned CLI tests directly:
   `test_validate_full_reaches_eligible_for_paper_through_the_cli` asserts
   zero failing gates and `verdict == "ELIGIBLE_FOR_PAPER"`;
   `test_validate_full_reaches_rejected_through_the_cli` asserts
   `verdict == "REJECTED"` - both via `CliRunner`, both with network access
   monkeypatched to raise on any call, neither the old tautological
   "verdict in {...}" check. Confirmed the eligible test's fixture genuinely
   exercises the real `configs/validation.yaml` (`_REAL_VALIDATION_CONFIG`),
   which has `sensitivity.momentum` axes configured - so a passing
   `no_cliff_score` gate in that test is only possible if the sensitivity
   grid genuinely ran through the wired path, not a vacuous pass.
6. **[verified fixed] Dirty flag never reached the report card.** New
   `ReportCardProvenance` dataclass (report_card.py:297-337) carries
   `strategy_id`, `data_semantics_version`, `quantlab_git_sha`,
   `dirty`/`dirty_source`, `n_trials`/`n_trials_raw`, `dirty_trial_count`,
   `rc_trial_count` (K), `rc_spa_benchmark_source`,
   `headline_retained_fraction`, the untrusted-fraction line, and the
   Sharpe/Sortino convention statement. `_report_card_markdown` (cli.py)
   renders all of it under a "## Provenance" section, with a `**DIRTY
   TREE**` badge when `dirty=True`, plus a new "## Headline metrics" section
   printing the Sharpe/Sortino convention beside the actual numbers (closing
   the M05 carried item 8 gap the gate also flagged in finding 8).

Non-blocking items 7-9 and the addenda (10-14), all independently spot-checked:
- p-values are `(1 + count) / (B + 1)` in both `white_reality_check` and
  `hansen_spa` (reality_check.py:281-284, 329-332) - can no longer return
  exactly 0.0. The measured over-sizing at the shipped `block_len=6.0` is
  documented in the module docstring rather than silently left implied-nominal;
  the in-tree calibration test's simulation count was NOT raised (honestly
  left open in HANDOFF.3, not silently claimed fixed).
- `intended_capital_usd` (new `ValidationConfig` field, default 1000.0) now
  drives the capacity gate's denominator (report_card.py:846), replacing the
  backtest's own `initial_capital` notional; the gate reason states the
  resolved dollar figure and its source.
- `_resolve_overlap`'s greedy algorithm: read the full implementation
  (reality_check.py:82-181) and the two dedicated tests
  (`test_build_trial_matrix_excludes_trials_below_min_overlap_fraction`,
  `test_build_trial_matrix_detects_two_same_length_offset_windows`) - both
  pass; the docstring is honest that this is best-effort, not a global
  optimum.
- `_check_child_rebalance_frequencies` raises a named `ValueError` on a
  frequency mismatch before `walk_forward_blend` can silently intersect
  sparse dates; `_build_walk_forward_result`'s existing try/except still
  degrades this to a specific "walk-forward skipped: <message>" + `None`
  rather than crashing `--full`. All three dedicated tests pass.
- PSR's gate reason now carries the extreme-return caveat alongside DSR/MinTRL
  (report_card.py:704-708); `no_cliff_score`/`min_net_sharpe`'s reasons now
  carry the sensitivity result's `neighbourhood_size`/`neighbourhood_
  truncated`/`nan_points` flags (report_card.py:737-743, 768-769).

## Verification performed this iteration

- Independently reproduced (standalone script, outside any test file) the
  gate's exact 9-sibling DSR-gaming scenario against the real
  `TrialsRegistry`/`deflated_sharpe_ratio`: N(dedup) stays at 10, DSR stays at
  0.7206 (FAIL) after 15 and 40 cosmetic reruns; raw key count correctly grows
  to 25 and 50.
- Independently reproduced the RC/SPA benchmark-choice mechanism against the
  real `build_report_card` on a fresh 6-trial fixture: `embedded` (default)
  vs. `zero` gives RC p=0.3522 vs. p=0.0033 on identical data, with the
  resolved source named in the gate reason both ways.
- Ran `tests/test_trials_registry.py`, `tests/test_reality_check.py`,
  `tests/test_purged_cv.py`, `tests/test_cli_validate.py` directly: 50/50
  passed, including every test the gate's remediation list named by name
  (`test_dsr_stays_failed_after_15_and_40_byte_identical_cosmetic_reruns`,
  `test_build_trial_matrix_labels_columns_by_full_key_not_strategy_id_alone`,
  `test_subperiod_oof_sharpe_is_invariant_to_embargo_and_label_horizon`,
  `test_validate_full_reaches_eligible_for_paper_through_the_cli`,
  `test_validate_full_reaches_rejected_through_the_cli`, both child-frequency
  tests).
- Grepped `src/` and `tests/` for `record_sensitivity(`/
  `seed_historical_blend_trials(`: both now called from `cli.py`, not only
  from test files.
- Read `deflated_sharpe.py`'s updated `n_trials==1`-only special case and
  `registry.py`'s `var_sr_trials` floor in full - both match the remedy
  exactly as described, with the binding "do not restore" comment preventing
  regression.
- Read `report_card.py`'s full `ReportCardProvenance`/gate-reason wiring and
  `cli.py`'s `_report_card_markdown` end to end - every field the gate asked
  for (dirty/dirty_source, N deduped and raw, K, benchmark source,
  untrusted-fraction line, Sharpe/Sortino convention, headline retained
  fraction) is present in both the dataclass and its markdown rendering.
- Full suite: `uv run pytest tests/ -q` - exit 0, 522 dots (matches the
  handoff exactly). `uv run ruff check` and `uv run ruff format --check` both
  clean. `git diff --stat -- src/` shows only `cli.py` (+339/-… ), `basic.py`
  (+58), `metrics.py` (unchanged from iteration 2) - consistent with the
  handoff's file list; `registry.py`, `reality_check.py`, `purged_cv.py`,
  `report_card.py`, `deflated_sharpe.py` are untracked files edited in place,
  as in prior iterations.

No part of this iteration's diff touches anything from the prior two review
cycles' "verified correct" ground (PSR/DSR/MinTRL closed forms, purged K-fold
construction, stationary bootstrap, capacity port, per-period footing fix,
method-of-moments skew/kurt), and nothing there regressed.
