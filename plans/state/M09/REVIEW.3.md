VERDICT: APPROVE

M09 iteration 3 review (answers the quant gate's cycle-1 findings). Branch m09-end-to-end, HEAD 7296580. Counts: 0 blocker, 0 major, 3 minor (non-forcing).

## Measured

- Default suite: exit 0, no failures (developer reports 908 passed), 2m26s wall on BATTERY (BatteryStatus 1, 36% charge, throttled). Not a budget measurement; the 86 s AC figure from REVIEW.2 stands for AC.
- `uv run ruff check` clean; `uv run ruff format --check`: 137 files already formatted.
- `git status --short` was empty after every mutation batch (all reverted).

## Verification of the lead's items

1. Reconciliation tables. `uv run python plans/state/M09/recon_tables.py` is read-only (it only reads parquet, jsonl and file times; the tree stayed clean) and reproduces EVIDENCE.md sections 5 and 6 and the README tables exactly: grid (12,50) 16.2899% / 0.9906 / -20.0879% (hash 9d6aa6d258), headline (12,30) 17.6532% / 0.9783 / -23.2508% (hash d02dafe6e9); value 13 Sept 17.62% / 0.9747, 25 Sept 17.49% / 0.9701, final 17.19% / 0.9493 with the window CAGRs in the README table; 172 of 173 periods differ 13 vs 25 Sept; 39 differ 25 Sept vs final, first 2021-09-30; 66 fundamentals files first written 2026-09-23 00:29 to 2026-09-24 15:14, including the names listed in the README (list truncated in my output but the first 30 and the counts match). The run-time claim "2h51m" is right: the September card at dc5356d records run seconds 10278.07. README text: "SAME strategy" about momentum vs the predecessor is gone ("It is not the same strategy as QuantLab's headline"; 50 vs 30 names); the only remaining "SAME strategy at the SAME parameters" is the correct statement that the 25 Sept grid point has the headline's own params. "TE/BEAM/NE/S/STI line up", "strongest evidence" and the 6.5 h re-run claim are gone (grep clean). The README arithmetic (+1.36 pp CAGR and -3.16 pp drawdown from 50 to 30 names; about 1.4 of 1.96 pp and 3.2 of 3.55 pp) matches the table; the 13-to-25 Sept movement is marked UNRESOLVED and only the 25 Sept-to-final part is "consistent with" quarantine.
2. Drift. Mutations, each reverted: ignoring `assumed_fill_session` (open taken on the price-asof date) fails 2 tests; shifting the session by one day fails 3; removing the missing-input guard (`if False`) fails the missing-open test; ignoring a missing `assumed_fill_session` fails `test_a_record_without_an_assumed_fill_session_reports_no_gap`; computing timing gap against the fill price instead of the open fails 2. Missing input yields an entry in `gaps_not_computed` and no figure, never 0. Closed.
3. Promotion gate. Removing the refusal (`if False`) fails 2 tests (`..._built_on_an_unscanned_cache`, `..._with_no_scan_provenance_at_all`); accepting a missing count (None) fails the no-provenance test. Closed. (A mutant that also accepts count == 1 survives; the tests use 2, so the boundary is not pinned, which is not a defect.)
4. netted_grid. Removing the missing-param refusal fails `test_a_child_param_missing_from_provenance_is_a_refusal_not_a_match`; dropping the vintage disclosure fails `test_data_vintage_differences_are_disclosed_not_refused`. Closed.
5. `git diff 1969fb8..HEAD -- src/quantlab/backtest src/quantlab/data src/quantlab/strategies` is empty. Backtest numerics cannot have moved.
6. Suite and ruff: above.

## Minor findings (do not force REVISE)

1. `src/quantlab/validation/report_card.py` `_unscanned_cached_count`: replacing `unscannable = set(run_provenance.get("no_data_suppressed_tickers", []))` with `set()` survives `tests/test_runner.py` and `tests/test_report_card.py`. The "no_data-only never-scanned list does not block" case is therefore pinned only through a hand-built count of 0 (`test_runner.py:309`, 1608), not through the builder's arithmetic. Add one unit test of `_unscanned_cached_count` with never_scanned = {A, B}, no_data = {B} expecting 1, and never_scanned = no_data expecting 0. This matters because it is exactly what lets a legitimately scanned cache promote.
2. `src/quantlab/validation/netted_grid.py` around line 220: `vintage: list[str] = []` is declared twice in a row (copy-paste; harmless, ruff does not flag it). Delete one.
3. Carried and unchanged: `README.md:229` still says momentum "passes ... the no-cliff sensitivity gate" without noting the truncated 6-point neighbourhood (REVIEW.2 minor 1; the card discloses it). Also note for later: `paper drift` compares the fill-session raw open with the decision-bar raw close, so a split between the two sessions would produce a spurious timing gap; not exercised by any current journal.
