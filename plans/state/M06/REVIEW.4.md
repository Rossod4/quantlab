REVIEW: APPROVE

## Findings

The single blocker from VERDICT.2.md (finding A, both its sub-bugs) is fixed
and independently verified end to end, including a mutation test. The three
non-blocking items in scope (B's disclosure, C, D's test) are also done. One
precise, non-blocking observation from the mutation testing below.

1. **[verified fixed] Headline could be excluded from its own Reality
   Check.** Ran the gate's exact planted case
   (`test_rc_hard_gate_fails_named_cause_when_headline_offset_from_siblings`)
   directly: three aligned 2014-2023 trials plus a worthless headline offset
   to 2019-2028 (60/120-month overlap, under the 0.8 floor), through the real
   `build_report_card` - the `reality_check_pvalue` hard gate FAILS, its
   reason contains "headline trial excluded by overlap floor",
   `report_card.rc is None`, and `verdict == "REJECTED"`. Also ran
   `test_headline_trial_can_still_be_rescued_by_removing_a_true_outlier`: a
   headline aligned with the majority, with a genuine non-headline outlier as
   the real constraint, still produces a matrix containing the headline and
   the outlier alone excluded - the fix does not turn into "headline always
   wins," it only guarantees the headline is never the trial sacrificed to
   make room for others.

   **Mutation testing (as asked).** Reverting the specific line that excludes
   `headline_label` from `_resolve_overlap`'s removal-candidate list did
   **not** make either the planted test or
   `test_headline_trial_is_never_a_removal_candidate` fail. Tracing this down:
   `build_trial_matrix` carries a second, independent invariant check after
   `_resolve_overlap` returns (`if headline_had_series and headline_label not
   in series: raise TrialMatrixError("headline trial excluded by overlap
   floor...")`) that fires regardless of *why* the headline is missing from
   the resolver's output, and this check alone reproduces the exact message
   both tests grep for. To confirm this is the actual load-bearing guarantee
   and not a coincidence, I additionally disabled that second check (`if False
   and headline_had_series...`) with the candidate-exclusion line restored:
   both tests then failed immediately (one with an `AssertionError` from
   `report_card.py`'s own `assert headline_label in matrix.columns`, the other
   with a wrong-reason-string `AssertionError`), confirming it is genuinely
   exercised, not vacuous. Both mutations were reverted; `diff` against my
   backup copy showed the file identical afterward, and the full suite passed
   clean before I proceeded.

   Net effect: the code is **correct and even more defensively built than the
   remedy's own description** - the headline can never silently vanish from a
   `non-None` `rc`/`spa` result because of the redundant top-level check, not
   only because of the resolver's candidate exclusion. The candidate-exclusion
   line is not dead code (it is what allows the genuine-outlier "rescue" case
   to keep working when the headline itself would otherwise tie or lose a
   greedy comparison against a real offender - a scenario the current test
   suite does not happen to isolate on its own), but neither of the two named
   regression tests independently pins it; they are both actually pinning the
   second (report_card.py-called) invariant check. This is an informational
   precision note for whoever next touches this code, not a gap in the
   platform's actual behavior.

2. **[verified fixed] Excluded/retained_fractions lost on raise; one generic
   reason regardless of cause.** `TrialMatrixError` (a `ValueError` subclass)
   carries `reason_kind`, `excluded`, `retained_fractions` from all three raise
   sites in `build_trial_matrix`. Ran all three branch tests directly -
   `test_build_trial_matrix_raises_too_few_trials_recorded` (`reason_kind ==
   "too_few_trials_recorded"`, `excluded == []`),
   `test_build_trial_matrix_raises_excluded_by_overlap_floor_without_headline`
   (`reason_kind == "excluded_by_overlap_floor"`, non-empty `excluded`),
   `test_build_trial_matrix_raises_no_common_dates` - each uses a genuinely
   different fixture shape engineered to isolate exactly that cause (a single
   trial for the first, an outlier that still leaves <2 survivors for the
   second, disjoint dates with the floor disabled for the third), and
   `report_card.py`'s three-way `.get(reason_kind, ...)` dict produces a
   distinguishable RC gate reason for each. All three pass.

3. **[verified done, non-blocking] DSR non-monotonicity disclosure.**
   `_DSR_MONOTONICITY_NOTE` is appended to the DSR gate's reason whenever DSR
   is actually computed;
   `test_dsr_gate_reason_discloses_non_monotonicity_beside_the_badge` confirms
   it appears in `dsr_gate.reason`. Read
   `test_dsr_near_duplicate_headline_reruns_move_but_stay_bounded_then_turn_back_down`
   in full and confirmed it genuinely exercises non-identical series: each of
   the 24 reruns adds `1e-6 * k` (a distinct value per iteration) to the
   headline's returns AND a distinct `initial_capital`, so `series_hash`
   dedup (which collapsed the byte-identical cosmetic-rerun case in iteration
   3's regression test) does **not** collapse these -
   `registry.n_trials("momentum") == 4 + 24` asserts every near-duplicate
   counts as distinct. The test then pins the full documented shape: DSR
   rises while `var_sr_trials` is still above the `1/(n_periods-1)` floor,
   peaks exactly where the floor first binds, and is non-increasing
   thereafter as N keeps growing with variance pinned at the floor - matching
   VERDICT.2's own measured shape at a much smaller, fast-running scale.

4. **[verified done, non-blocking] Capacity "trivially passable" note.**
   Present in the gate reason exactly when `capacity_ok and cap_multiple > 10
   * capacity_multiple`; ran both
   `test_capacity_gate_states_trivially_passable_note_at_small_stake` (fixture
   clears >10x, note present) and
   `test_capacity_gate_omits_trivially_passable_note_when_close_to_the_bar`
   (bar raised to just under the fixture's own multiple, note absent) - both
   pass, and both fixtures assert the actual multiple before checking the
   note so the test can't pass vacuously on the wrong side of the threshold.

5. **[verified done, non-blocking] RC/SPA size-bound test at the shipped
   block length.** `test_white_rc_size_at_shipped_block_length_is_bounded`
   runs 300 sims with `block_len=6.0` (the actual `configs/validation.yaml`
   value, not the separate uniformity test's `block_len=3.0`), measures the
   empirical rejection rate at the gate's own `max_rc_pvalue=0.10` bar, and
   asserts it falls in `[0.04, 0.28]` - a band deliberately centred above
   nominal 0.10 (consistent with the module docstring's documented ~0.12-0.123
   measured over-sizing) rather than asserting calibration the test cannot
   detect. Ran it directly, passes.

## Verification performed this iteration

- Ran every test named in HANDOFF.4.md and VERDICT.2.md directly (10 tests,
  the planted case, both branch-cause tests, the DSR near-duplicate
  regression, both capacity-note tests, the size-bound test): all pass.
- Mutation-tested the fix twice: (a) removed the headline's exclusion from
  `_resolve_overlap`'s candidate list - no test failed, traced to a second,
  independent invariant check in `build_trial_matrix`; (b) with (a) reverted,
  disabled that second check instead - both of the fix's headline regression
  tests failed immediately, confirming it is the genuinely load-bearing
  guarantee. Reverted both mutations; `diff` against a pre-mutation backup
  confirmed byte-identical restoration; full suite re-ran clean before
  proceeding to the write-up.
- Grepped `src/` and `tests/` for `VERDICT.2.md` references to independently
  identify which files this iteration actually touched:
  `reality_check.py`, `report_card.py`, `test_reality_check.py`,
  `test_report_card.py`, `test_trials_registry.py` - exactly HANDOFF.4.md's
  stated scope (one unrelated hit in a canary test file references M04's own
  `VERDICT.2.md`, a different milestone's gate document, not this one).
- Full suite: `uv run pytest tests/ -q` - exit 0, 533 dots (matches the
  handoff exactly). `uv run ruff check` and `uv run ruff format --check` both
  clean.
- `git diff --stat -- src/` shows only `cli.py`, `basic.py`, `metrics.py`
  among tracked files, with line counts **identical** to iteration 3's
  (339/+58/+24) - confirming none of those three were touched this cycle,
  consistent with the narrowed scope. `registry.py`, `reality_check.py`,
  `purged_cv.py`, `report_card.py`, `deflated_sharpe.py` remain untracked
  files edited in place.

No part of this iteration's diff touches anything from the prior three
review cycles' verified-correct ground, and nothing there regressed.
