# M09 HANDOFF.2 (iteration 2, answering plans/state/M09/REVIEW.md) - developer 3

Default suite 899 passed / 100 deselected; ruff check and format clean. Code at 212159c; blend card re-validated at 212159c (committed 8eb8ce1); momentum card re-validated from clean sha 8eb8ce1 (uncommitted artefacts in the tree).

## Re-validation results
- blend_50_50: REJECTED, verdict, all gate pass/fail and reason texts identical to before; N=8, K=3; ranking agreement unchanged (tau 1.0, same five Sharpes). Card now has repo-relative run dirs, `validated_by_git_sha` 212159c, `validated_by_dirty` false. One live registry row per key (headline has 3 raw rows, superseded).
- momentum_12_1: REJECTED unchanged; every gate value identical except no-cliff. The grid is now centred on the headline (base point lookback_months 12, n_long 30): neighbourhood_size 6, `neighbourhood_truncated` True (n_long=30 is the EDGE of [30,50,70]), no_cliff 0.9720 (was 0.9452 when centred on n_long=50; a truncated neighbourhood mechanically flatters the score, so read it with that caveat). Card: `validated_by_git_sha` 8eb8ce1, `validated_by_dirty` false. Registry: the nine sensitivity rows have live dirty=False rows; the nine earlier dirty=True rows are superseded in the jsonl (36 raw rows total).
- Restart note: the first momentum re-validation was killed at about 78 CPU-minutes because three regenerated blend report files were uncommitted at its start (tree dirty); it was restarted from a clean tree (8eb8ce1, 2 Oct 20:19) and is the one recorded here.
- value_composite card is as produced at dc5356d (no `validated_by_*` fields); only its `report.md` was re-rendered.

## Closure of REVIEW.md findings
| # | Status | Evidence |
|---|---|---|
| 1 | fixed | canary (l) in tests/canaries/test_lookahead.py, 4 cases; your mutation (`as_of_date + 3650d` in `_ttm_duration_components`) fails 4/4 |
| 2 | fixed | tests/test_drift.py asof-spy tests (single + blend path); `asof=_asof + 30d` mutation fails both |
| 3 | fixed | test_runner.py + test_cli_paper.py: other-strategy card, "m03b" card refused; real `build_report_card` card accepted; both condition mutants fail 2 tests each |
| 4 | fixed | default-tier `quantlab run` exit 0/2/3 test (stubbed engine and card builder); "always 3" mutant fails 2 cases |
| 5 | fixed | `_build_sensitivity_result` passes headline params as base point, refuses off-grid or missing axis (3 tests); momentum card regenerated (see above); value unaffected (n_holdings=30 is the middle of [20,30,40]) |
| 6 | fixed | README value text names the three hard failures; drawdown is context only |
| 7 | fixed, residue below | `core/paths.portable_path` in ranking run dirs and report provenance; provenance.json re-ignored and de-indexed (counts live in cards' known_caveats, the report's Quarantined row and EVIDENCE.md section 4) |
| 8 | fixed | README recipe uses the committed blend configs for the interior runs, adds `--record-trial` and the report step; strategy YAML headers corrected (ids unchanged: blend-a7f7c30ce1, blend-9231a3894e) |
| 9 | closed with caveat | 899 passed in 55.24 s pytest-reported, on AC (BatteryStatus 2) with one detached validation running concurrently (under the 90 s budget; not a quiet-machine figure). Battery figures 123-133 s are throttled and not the budget's definition. Slow tier not re-run |
| 10 | fixed | plans/state/M09/EVIDENCE.md (A/B commands, shas, series hashes, 42->36 list, run provenance table), README points to it; cards record `validated_by_git_sha`/`validated_by_dirty` (additive, tested) |
| 11 | fixed | prefetch test asserts actions requested from `_EPOCH`; `start_ts` mutation fails it |
| 12 | fixed | test asserts an infinite min-TRL reason says "unbounded", not "inf"; "inf" mutation fails it |

## Path-residue grep (tracked reports/ and README, `Users\` or `Users/`)
Only `reports/value_composite/report_card.md` (written by validate; value's card stays as produced). README and the momentum and blend files are clean. Outside reports/: older plans/ packets, plans/state/M04b/*/provenance.json and tests/parity (September-era, untouched).

## Notes for the gate
- Deviations carried from HANDOFF.md still stand (fresh registry, latest-row-supersedes, grid blends as trials, five-point ranking, runs at dc5356d).
- The headline-centred base point makes momentum's no-cliff figure comparable to value's only loosely (different neighbourhood sizes: 6 vs 3).
