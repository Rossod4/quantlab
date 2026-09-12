REVIEW: APPROVE

# M08 review (iteration 3, closes REVIEW.2.md REVISE)

## Verification commands
- `uv run pytest tests/ -q`: exit 0. Dot count verified by hand: 686/686
  (matches the handoff's claim exactly; 681 + 5 new parametrized stage tests).
- `uv run ruff check`: All checks passed.
- `uv run ruff format --check`: 115 files already formatted.
- `uv run pytest tests/parity tests/canaries tests/test_engine.py -q`: all green
  (83/83 dots) — re-verified the engine/context extraction is still undisturbed by
  this iteration's `run_once` restructuring.
- `git diff --stat` on `src/`: matches the developer's own file list
  (`engine.py`, `cli.py`, `core/errors.py`; `paper/runner.py` is untracked/new so
  doesn't show in `git diff`, confirmed unchanged from iteration 2 otherwise via
  `git status --short`).

## Findings

None. The one blocking issue from REVIEW.2.md is closed and I verified the fix
directly, not just by re-reading the developer's own tests.

## Per-item verification (team-lead's checklist)

1. **Reproduced my own zero-record blend case.** Wrote a throwaway script (fake
   providers only, deleted after running, no repository file touched) reproducing
   the exact blend-overreach scenario from REVIEW.2.md:
   ```
   raised UndeclaredDataError: True
   journal record count after the crash: 1
   refused_reason: run_once failed at stage='targets' (UndeclaredDataError:
     prices() requested lookback_days=5 exceeds declared
     DataRequirements.price_lookback_days=1) - refusing to trade; no orders
     were submitted this run.
   planned_orders: []
   ```
   Exactly one record, `stage='targets'`, `UndeclaredDataError` named, matching
   `tests/test_runner.py:833-867`'s own updated assertions.

2. **Five-stage unexpected-exception test.** Ran
   `test_unexpected_exception_at_each_stage_is_journaled_exactly_once` directly
   (`tests/test_runner.py:880-1011`, parametrized over
   `context`/`targets`/`reconcile`/`plan`/`submit`) — 5 passed. Read the fixture
   for each stage: `context` breaks `set_context_factory`, `targets` breaks
   `generate_targets`, `reconcile` pre-seeds a prior traded run and breaks
   `get_actions` inside the roll-forward loop (correctly expects 2 records total,
   not 1, since a prior run's own record is pre-seeded directly rather than via
   `run_once`), `plan` monkeypatches `plan_orders`, `submit` replaces
   `broker.submit` — all via a shared `_UnexpectedTestError(RuntimeError)` none of
   the specific inner handlers anticipate. Each asserts `stage=` and the exception
   class name appear in `refused_reason`.

   **My own construction — a `BaseException` that is not an `Exception`.** I
   defined a strategy whose `generate_targets` raises `KeyboardInterrupt` and ran
   it through `run_once` directly (throwaway script, deleted after):
   ```
   raised: KeyboardInterrupt
   journal record count: 0
   ```
   `except Exception` does not catch `KeyboardInterrupt`/`SystemExit`
   (`BaseException` subclasses, not `Exception` subclasses), so this run_once call
   crashes with zero journal entries, same as before iteration 3's fix. **I judge
   this acceptable, not a gap to close:** deliberately catching `BaseException` to
   journal a `KeyboardInterrupt` would be the more dangerous choice — it would
   delay or swallow an operator's own Ctrl-C, and on Windows a scheduled task
   killed outright terminates the process without raising any Python exception at
   all regardless of what `run_once` catches, so this excess coverage would only
   ever fire on an interactive, manually-interrupted run, where the human doing
   the interrupting already knows what happened and a journal record written from
   a partially-unwound stack (possibly mid-`broker.submit`) could be actively
   misleading. `docs/paper-trading.md`'s Guarantees wording ("journals ANY
   exception that reaches it") is accurate under the conventional Python reading
   of "exception" as `Exception`-derived and doesn't need a caveat for this.

3. **No double-journaling.** Ran the existing `test_planted_mismatch_refuses_to_trade`
   and `test_promotion_gate_refuses_a_rejected_strategy` (3 passed together with a
   third). Additionally wrote my own direct check: two `run_once` calls, second one
   hitting a planted, unexplainable cash mismatch —
   ```
   records after run1: 1
   records after run2 (should be exactly +1): 2
   ```
   Confirmed by reading the code: `_refuse()` sets `already_journaled = True`
   (nonlocal) before any specific inner handler re-raises; the outer
   `except (PromotionGateError, ReconcileError): raise` skips the catch-all
   entirely for those two self-journaling types, and the final
   `except Exception as exc:` checks `if not already_journaled` before writing
   anything. Every inner handler (actions-cache exhaustion, data degradation,
   unscoreable-abort, reconcile, plan, submit) follows the same
   `_refuse(...) ; raise` pattern, so none of them can be double-counted by the
   outer net.

4. **`engine.py` orphaned-reference check.** Read lines 369-390 directly: the dead
   `def membership_history(self, start, end): return self._inner.membership_history(...)`
   fragment is gone; `_drop_terminal_partial_period` ends cleanly at its own
   `return`, and the section-header comment now sits at module level, not
   nested inside a function. Grepped the whole file for `_inner`/
   `_FilteringConstituentsProvider` — the three remaining hits (lines 12, 176, 384)
   are all accurate prose pointing at `backtest/context.py`, nothing orphaned.
   Ran `tests/parity`, `tests/canaries`, `tests/test_engine.py` in isolation:
   83/83 green.

5. **Full suite, ruff, diff.** 686/686 tests (hand-counted), `ruff check` and
   `ruff format --check` clean, `git status --short`/`git diff --stat` confirm
   only `plans/QUANT-NOTES.md`, `backtest/engine.py`, `cli.py`, `core/errors.py`,
   and `tests/canaries/test_lookahead.py` differ from clean `HEAD` (plus the
   untracked new `paper/`/`docs/`/test files), matching the developer's own
   iteration-3 file list. No writes under `data/`. All scratch/probe scripts I
   used for verification were deleted before finishing; none left in the tree.

## Summary across all three iterations

Cycle-1's five blocking findings (reconcile bricking, missing shared decision
context, uncaught delisting crash, unrecoverable partial fills, missing blend
per-child guard) and cycle-2's one blocking finding (the exactly-one-record
journal guarantee being enumerated rather than structural) are all fixed and
independently verified — not merely re-read from the developer's own tests. The
milestone is ready for the quant gate.
