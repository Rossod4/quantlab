# M08 handoff (iteration 2 — addresses VERDICT.md cycle-1 REJECT)

## Files
New: `backtest/context.py` (shared `build_decision_context`/`_FilteringConstituentsProvider`,
moved from `engine.py`). Edited: `core/errors.py` (`BacktestAbortError` moved here,
re-exported from `engine.py`), `backtest/engine.py` (`context_factory` calls the shared
helper), `paper/{broker,mock,alpaca,rebalancer,reconcile,journal,runner}.py`, `cli.py`
(`paper rebaseline`), `docs/paper-trading.md`, plus expanded tests across
`tests/test_{runner,reconcile,journal,cli_paper,broker_contract}.py` and the canaries file.
`plans/QUANT-NOTES.md`'s M08 section is the gate's own cycle-1 addition, not mine.

## Per-finding fixes
1. **Reconcile**: `reconcile.roll_forward_expected` rolls the last traded/rebaselined
   run's `account_after` through dividends (credit `qty*value` on ex-date, held qty) and
   splits (`qty*=R`, `avg_cost/=R`) before comparing; `ReconcileReport.applied_adjustments`
   journals what was explained. `accept_broker_state`/`quantlab paper rebaseline --reason`
   is the explicit human escape hatch (`kind="rebaseline"`, never a refusal). Docs fixed.
2. **Shared context**: `backtest/context.build_decision_context` is now the ONE place
   either `run_backtest` or `run_once` builds a decision context — same
   `_FilteringConstituentsProvider`, same `max_dropped_fraction` abort. `PaperRunConfig`
   (`max_dropped_fraction=0.05`, `abort_on_unscoreable=True`, matching `BacktestConfig`
   defaults) governs the paper path. Journal gets `dropped_tickers`/`dropped_fraction`/
   `unscored_tickers`.
3. **Delisted holding**: `plan_orders` exits a zero-target held position with NO price
   needed (`qty=abs(cur_qty)` directly); the runner forces ANY held-unpriceable ticker's
   target to zero regardless of the strategy's own declaration and journals
   `forced_exits`. Every exception path in `run_once` (actions-refresh exhaustion, data
   degradation, unscoreable, planning/submission) now journals exactly one record before
   re-raising — verified by the docstring's own promise.
4. **Partial fills**: `client_order_id_for` gains an `attempt` suffix; the runner cancels
   resting orders before planning each cycle (`cancel_open_before_plan`, default True) and
   plans a fresh `attempt` under a genuinely new id, so a remainder gets topped up across
   runs instead of stuck forever. `resting_orders` (after submit) and `canceled_orders`
   (before planning) are both journaled. `MockBroker.submit`/`AlpacaPaperBroker` now ALWAYS
   surface a duplicate resubmit as `OrderAckStatus.DUPLICATE`, never a replayed `Fill`.
5. **Blend**: `run_once` calls `strategy.set_context_factory` with the same shared-context
   closure the engine uses — a blend child's own `requires()` is enforced exactly as under
   `run_backtest`.

## Carried items closed
Canary (k) extended to pin the data-cache ceiling too (mutation-checked). `journal_to_frame`
widened (`promoting_report_card`, `known_caveats`, `refreshed_actions_tickers`, `targets`,
`kind`, counts). `price_asof_by_ticker` records the bar date used per ticker.
`assumed_fill_session` documents the paper-vs-backtest fill-timing lag (journal + docs).

## Mutation checks (reverted after confirming failure)
`prev_trading_day`→today: original canary (k) failed as before. Data-cache ceiling clamp
deleted: NEW canary failed too (`2024-01-12 <= 2024-01-05`), confirming real power there.

## Tests
`uv run pytest tests/ -q`: **exit 0, 681 dots, 0 failures/skips in the default run**.
`uv run ruff check .`: clean. `uv run ruff format --check .`: clean (115 files).
`git status --porcelain`: no writes under `data/`.

## Open questions
Finding 1's dividend roll-forward keys off the actions frame's ex-date (no pay-date field
exists in this platform's data) — documented choice. A ticker whose actions fetch fails
during reconcile roll-forward specifically is compared unadjusted for that ticker only —
conservative, documented, not a new gap.
