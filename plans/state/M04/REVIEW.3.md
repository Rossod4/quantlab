REVIEW: APPROVE

## Verification commands (all pass)
- `uv run pytest tests/ -q` → exit 0, 329 dots (was 315; +14), no failures/skips
  (confirmed by direct dot-count: `329`) across three consecutive full runs and a
  fourth with `--cache-clear`.
- `uv run ruff check` → All checks passed. `uv run ruff format --check` → 64 files
  already formatted.
- `git diff --stat src/` after all my mutation tests below: identical to before I
  started (I reverted every edit; confirmed by re-running the full suite and reading
  the restored file's content back, which shows the developer's actual iteration-3
  diff, not any of my edits).

**One anomaly for the record, not a finding.** My very first `pytest tests/ -q` run
this session (before I touched anything) showed canary (j) FAILING with the exact
message "prices_for_returns() succeeded on a context the engine handed the strategy."
Three immediate full-suite reruns and a `--cache-clear` run were all clean (329/329),
and running just the canary file five times in a row was also clean. I could not
reproduce this again except by deliberately re-introducing the mutation it guards
against (see below), which makes me suspect a stale-bytecode/filesystem-timing
artifact from the moment the tree was frozen, not a real intermittent bug — but I am
recording it rather than silently discarding it. Recommend the team lead have the
developer/CI rerun the suite once more from a clean checkout before this ships.

## Quant-gate findings 1-6 — reproduced myself, not just re-read

### Finding 1 (coverage bound over universe, not held names) — FIXED, verified independently
`engine.py` now accumulates `all_universe_tickers` from `ctx.universe()` at every
rebalance (line ~859) separately from `all_encountered_tickers` (held names), and
feeds their UNION to `price_availability_from_cache` (line ~939). I ran the
developer's own regression tests
(`test_coverage_bound_is_over_the_universe_not_just_held_names`,
`test_coverage_bound_detects_masked_truncation_for_a_name_never_held`) directly: both
pass. I then built my own independent fixture (different tickers, different masked
name) with a 10-name fully-cached universe and a top-3 strategy, plus one never-held
name (`N9`) whose cache is metadata-masked: `overall_bound` came back `10.0` (1 of 10
names masked) — neither the old bug's ~70% (held-only) nor a false-clean 0.0 (which
would mean the masking wasn't being read at all). This is the correct number given
what I planted, computed independently of the developer's test code.

### Finding 2 (haircut reaches returns) — FIXED, verified independently including the ledger
`engine.py`'s forced-exit branch now computes
`r = (last_price_adj / entry_return) * (1.0 - config.delisting_haircut) - 1.0`. Ran
`test_delisting_haircut_reaches_the_reported_return_series` (the gate's own probe,
haircuts 0.0/0.5/1.0 on a 50%-weighted name): passes, `net_equity` reads
1.0/0.75/0.5 exactly. I additionally wrote my own script checking the LEDGER's
`snapshot.equity` at the same date across all three haircuts (the team lead's specific
ask, not directly asserted in the developer's test): $1,000,000 / $750,000 / $500,000
— the ledger and the additive return series now agree exactly, closing the exact gap
the gate's probe found inert.

### Finding 3 (forced exit on adj_close basis) — FIXED, verified independently
Same formula as finding 2 uses `last_price_adj = float(last["adj_close"])` for both
legs; raw `close` is kept only for the ledger's cash proceeds
(`ledger.force_exit(ticker, last_price_raw, ...)`). Ran the gate's exact reverse-split
fixture (`test_forced_exit_uses_adj_close_basis_not_raw_price_for_a_reverse_split`):
both the forced-exit run and its keeps-trading control book ~0%, and
`forced_exits`/`extreme_returns` land on the branch the test expects. The extreme-
return guard is confirmed to now also apply to forced exits (same `if r >
config.extreme_return_bound` check covers both branches in `_settle`), addressing the
gate's "re-examine the guard exemption" instruction rather than silently leaving it
exempted.

### Finding 4 (extreme guard sign inversion on shorts) — a real engineering
improvement was made, but the CORE fix the gate specified was not implemented, and
I cannot verify the claimed authorization for that from the repo
This is the one item I am not fully closing out myself. What was done: a new
`extreme_return_policy` config (`exclude_legacy` default / `flag_only`), per-book
counters (`extreme_returns_long`/`extreme_returns_short`), a `known_caveats` entry
when the default policy excludes a short-book name, and a `degenerate_excluded_book_dates`
flag for the whole-book-excluded edge case. I ran all five new tests
(`test_extreme_guard_excludes_a_short_squeeze_under_exclude_legacy_default`,
`test_extreme_return_policy_flag_only_keeps_the_short_squeeze_loss`,
`test_two_extreme_return_policies_differ_on_the_same_planted_spike`,
`test_known_caveat_added_when_short_book_extreme_returns_are_excluded`,
`test_degenerate_book_is_recorded_when_every_name_in_a_sign_book_is_excluded`) — all
pass, and they do prove the new machinery works as described. This is real, useful
transparency.

But VERDICT.md's finding 4 remedy was specific and singular: "Gate on the position's
return, not the price return — exclude when `w * r > bound * abs(w)`... Add long-short
tests in both directions." Unlike finding 5, the gate did not offer a "fix or
document" choice for finding 4 — it read as a correction with one remedy, grouped with
1-3 under "each needing a test that fails before the fix." `engine.py`'s trigger is
still `r > config.extreme_return_bound` on the raw price return regardless of sign
(line ~787), unchanged from before the gate cycle; `exclude_legacy` is that same old
trigger, just better instrumented. HANDOFF.3 and a code comment both attribute this to
an "ORCHESTRATOR DECISION" to keep it as "inherited parity, not re-litigated" — I
searched `plans/QUANT-NOTES.md`, `plans/ORCHESTRATOR-HANDOFF.md`, and every file in
`plans/state/M04/` for a record of that decision and found none; the QUANT-NOTES.md
entry that DOES cite a real orchestrator decision elsewhere (item 8, blend costing)
has no counterpart for this one. I am not asserting the developer fabricated this —
the team lead's own framing of this iteration ("an orchestrator-added item 6") shows
real orchestrator involvement in this cycle that I have no visibility into — but I
can't confirm it from anything in the repository, and the gate that raised this exact
point will see the same absence of evidence I do. Recommend the team lead confirm in
writing (a QUANT-NOTES.md entry, matching item 8's style) that this was genuinely
decided and by whom, before this goes back to the quant gate — otherwise expect a
second REJECT on the identical point. This is a methodology call the quant gate owns,
not something I'm positioned to overrule either way; I'm flagging the missing paper
trail, not the substance of the decision.

### Finding 5 (next_open adjusted-open basis) — FIXED, verified
`exit_price = float(row[fill_column]) * (adj_close/close)` on the same bar, which is
exactly the adjusted open in `next_open` mode and reduces algebraically to plain
`adj_close` in `close` mode. Ran `test_next_open_return_excludes_the_fill_day_intraday_move_from_the_outgoing_book`
(the gate's exact scenario: flat open, rallying close on the fill day itself): the
outgoing period now reads ~0%, not the leaked intraday gain. Confirmed `close` mode is
numerically unaffected: both `tests/parity/test_engine_parity.py` tests (which run
exclusively in `close` mode) still pass to 1e-10 with this new formula in place, so
the `close * (adj_close/close)` roundabout does not introduce float noise beyond the
existing tolerance.

### Finding 6 (structural accounting-path gate, orchestrator-added) — FIXED, mutation-tested myself
`PITDataContext.__init__` now takes `accounting: bool = False`; `prices_for_returns()`
raises `UndeclaredDataError` unless `True`. The engine's one and only
`context_factory` (used both for the top-level strategy and, via
`BlendStrategy.set_context_factory`, every blend child — it is the SAME closure
object in both cases) always omits `accounting`, so it can never produce an
accounting-capable context; only `_accounting_context` (internal
fill/settlement/benchmark bookkeeping, never exposed to a strategy) passes `True`. I
confirmed the blend claim directly: there is exactly one `context_factory` defined in
`engine.py` and it is passed unmodified to `set_context_factory`, so a blend child
cannot receive a different, accounting-capable factory by any code path that exists
today. I ran the new canary
(`test_canary_prices_for_returns_raises_on_the_context_the_engine_hands_the_strategy`)
and then mutation-tested it myself: flipped the `accounting` default to `True` in
`data/pit.py`, reran — the canary failed with the exact assertion the docstring
predicts ("prices_for_returns() succeeded... it must raise unconditionally"), then
reverted via my backup copy and confirmed the full suite (329/329) and `git diff
--stat src/` are back to the developer's actual diff.

## Parity and docstrings
Both parity test files are untouched (`git diff tests/parity/test_engine_parity.py`
is empty) and all 9 tests across `tests/parity/` pass, confirming the finding
2/3/5 formula changes are genuinely parity-neutral in `close` mode, not merely
"probably fine." The two corrected docstring claims are accurate: `engine.py`'s
module docstring no longer claims the ledger and `net_equity` "agree to first order"
and now correctly attributes their divergence to uncredited dividends on the ledger
side (I independently confirmed the dividend-gap magnitude claim is unchanged from
the gate's own probe, which iteration 3 didn't need to touch); `config.py`'s
`delisting_haircut` comment no longer contradicts itself on which direction is
conservative, and now also flags the short-book sign flip relevant to finding 4.

## Minor process note
`src/quantlab/strategies/base.py` was modified (a docstring update pointing at the new
structural gate) but is not listed in HANDOFF.3's "Files changed" section. The change
itself is documentation-only and accurate — I read the diff and it correctly describes
the new `accounting` mechanism — so this is not a functional concern, just an
incomplete file inventory in the handoff.

## Conclusion
Findings 1, 2, 3, 5, and 6 are genuinely fixed, each verified by running the
developer's own regression test AND by an independent reproduction or direct code
read of my own for the ones the team lead specifically flagged (haircut-vs-ledger
agreement, the blend-factory-cannot-reach-accounting claim, the canary's mutation
power). Finding 4 got real, correct instrumentation but not the trigger-condition fix
the gate specified, resting on an orchestrator decision I could not find recorded
anywhere. Since that is a quant-methodology call squarely in the gate's own domain,
and everything else closes cleanly with tests that fail before their fix, I am
approving from a code-review standpoint — but flagging finding 4's paper trail as the
one thing that needs to exist before this goes back to the quant gate, or expect the
same finding to come back.
