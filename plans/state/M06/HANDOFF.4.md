# M06 handoff, iteration 4 (narrow cycle-3 gate: VERDICT.2.md items 1-5 only)

Scope was explicitly narrowed to VERDICT.2.md's five listed items; Finding E
(cosmetic `{gate.value!r}` markdown rendering) is listed there but was NOT in
the team lead's numbered list and was left untouched, per instruction.

## Per-item status

**1 [blocker] headline could be dropped by the overlap resolver - FIXED.**
`_resolve_overlap` takes `headline_label`; it is never a removal candidate,
but a below-floor headline can still be RESCUED by removing some other
genuinely offending trial first (normal greedy search keeps running on
non-headline candidates). Only when no other removal helps does the final
"drop everyone below floor" pass give the headline its own named reason
("headline trial excluded by overlap floor (retained_fraction=...)") instead
of the generic one. `build_trial_matrix` raises `TrialMatrixError` naming this
cause if the headline was recorded with a series but isn't in the survivors.
Code-level invariant (not only a test): `report_card.py` asserts
`headline_label in matrix.columns` immediately after every successful
`build_trial_matrix` call, before either RC or SPA runs. Regression (planted
case verbatim): 3 trials aligned 2014-2023 + worthless headline offset
2019-2028 (60/120-month overlap, under the 0.8 floor) -> `TrialMatrixError`
at `reality_check.py` level and `reality_check_pvalue` gate FAILS by name,
`report_card.rc is None`, verdict REJECTED, at `report_card.py` level
(test_reality_check.py, test_report_card.py). A second test confirms the
headline can still be rescued when a true outlier (not the headline) is the
actual constraint.

**2 [blocker] excluded/retained_fractions lost on raise; one generic RC-is-
None reason - FIXED.** New `TrialMatrixError(ValueError)` carries `reason_kind`
("too_few_trials_recorded" | "excluded_by_overlap_floor" | "no_common_dates"),
`excluded`, `retained_fractions` - all three raise sites in
`build_trial_matrix` now populate these before raising instead of losing them
to the tuple-unpack never running. `report_card.py`'s `except ValueError`
reads them via `getattr` (safe for a plain `ValueError`, though none are
raised anymore) and picks one of three distinguishable gate reasons. Each
branch has its own regression test in test_reality_check.py.

**3 [non-blocking] DSR non-monotonicity disclosure - DONE.** New
`_DSR_MONOTONICITY_NOTE` appended to the DSR gate's reason whenever DSR is
actually computed (not the separate "registry too thin" NaN branch, which
already explains itself). Extended regression
(test_trials_registry.py, new test): near-duplicate (not byte-identical) 1bp-
cost-style headline reruns move DSR up as `var_sr_trials` shrinks, peak
exactly where the `1/(n_periods-1)` floor first binds, then turn back down
(non-increasing) as N keeps growing with variance pinned - pins both "it
moves" and "bounded, not unlimited" at a small (n=12), fast fixture found by
numeric probe rather than reproducing VERDICT.2's literal 144-period numbers.
Disclosure-text presence checked separately in test_report_card.py.

**4 [non-blocking] capacity "trivially passable" sentence - DONE.** Appended
to the capacity gate's reason whenever `cap_multiple > 10 * capacity_multiple`
and the gate passes. Two tests: fixture clears >10x -> note present; bar
raised to just under the fixture's own multiple -> note absent.

**5 [non-blocking] RC/SPA calibration test lacked power at the shipped
block_len - DONE.** Existing `test_white_rc_synthetic_null_pvalues_are_uniform`
now explicitly documents (inline) that it runs at `block_len=3.0`/200 sims and
is a construction sanity check, not a calibration measurement. New
`test_white_rc_size_at_shipped_block_length_is_bounded` runs 300 sims at the
shipped `block_len=6.0`, measures the actual size at the gate's own
`max_rc_pvalue=0.10` bar, and asserts a wide tolerance band (0.04-0.28)
centred above nominal, matching the module docstring's documented ~0.12
measured over-sizing - catches a gross regression without flaking.

## Verification

`uv run pytest tests/ -q`: exit 0, 533 passed, 0 failed, 533 dots, ~25s wall
(well under the 90s budget). `uv run ruff check`: all checks passed. `uv run
ruff format --check`: 97 files already formatted.

## Open questions

None for this cycle's scope. Finding E remains open and untouched, as
instructed.
