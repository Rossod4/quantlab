# M08 handoff (iteration 3 — addresses REVIEW.2.md REVISE)

## Files
Edited: `paper/runner.py` (`run_once` restructured), `backtest/engine.py` (dead-code
fragment removed, one stale cross-reference comment fixed), `docs/paper-trading.md`
(Guarantees wording made structural), `tests/test_runner.py` (new parametrized stage
test, finding-5 blend test extended). No other files touched this iteration.

## Blocker fix
`run_once` now wraps everything below the point its identity (`strategy`/
`effective_asof`/`git_sha`/`dirty`) is known in ONE outer `try/except Exception`. The
existing specific inner handlers (promotion gate, actions-cache exhaustion, data
degradation, unscoreable, reconcile, plan, submit) are unchanged in behavior — each still
calls `_refuse` with its own specific reason — but `_refuse` now sets a local
`already_journaled` flag; the new outer `except Exception` only builds a generic
`"run_once failed at stage=... (ExceptionClass: msg)"` record when that flag is still
False, so nothing is double-journaled. `except (PromotionGateError, ReconcileError):
raise` skips the generic handler for the two exception types that are always already
self-journaling. A `stage` variable (`"promotion_gate"`/`"context"`/`"targets"`/
`"reconcile"`/`"plan"`/`"submit"`) is threaded through every reason string, inner and
outer alike, so every refusal record — not just the new catch-all's — names where it
happened. This closes the exact gap the review reproduced: `UndeclaredDataError`/
`LookaheadError` (or any other exception `generate_targets` raises, including via a
blend child's own guard) now gets exactly one journal record before propagating,
instead of zero.

New test: `test_unexpected_exception_at_each_stage_is_journaled_exactly_once`,
parametrized over all five stages, each planting an `_UnexpectedTestError` (a class none
of the specific handlers catch) via a stage-appropriate fixture (a strategy whose
`set_context_factory`/`generate_targets` raises, a hostile `CorporateActionsProvider`
during reconcile, a monkeypatched `plan_orders`, a monkeypatched `broker.submit`) —
asserts exactly one new journal record (two for "reconcile", since that case pre-seeds
one prior traded run to reach the reconcile block at all) naming the right stage and
exception class. `test_blend_child_overreach_raises_via_run_once_set_context_factory`
now also asserts the journal record (`stage='targets'`, `UndeclaredDataError`,
`planned_orders == []`) instead of only the raised exception.

## Cosmetic fix
Deleted the dead, unreachable `def membership_history(self, start, end): return
self._inner.membership_history(start, end)` fragment left in `engine.py` after the
`_FilteringConstituentsProvider` extraction (referenced `self`/`self._inner`, neither of
which exist in `_drop_terminal_partial_period`'s scope — never executed, ruff didn't
flag it). Moved the section-header comment above it to module level where it belongs.
Grepped `engine.py` for every other `_inner`/`_FilteringConstituentsProvider` reference —
all remaining hits are accurate prose, none orphaned; fixed one docstring's stale
"below" cross-reference to point at `backtest/context.py` instead.

## Tests
`uv run pytest tests/ -q`: **exit 0, 686 dots, 0 failures/skips in the default run**
(681 + 5 new parametrized stage tests). `uv run ruff check .`: clean. `uv run ruff
format --check .`: clean (115 files). `git status --porcelain`: no writes under `data/`.
