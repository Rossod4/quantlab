REVIEW: REVISE

# M08 review (iteration 2, cycle-2 fixes for quant-gate VERDICT.md cycle-1 REJECT)

## Verification commands
- `uv run pytest tests/ -q`: exit 0. Dot count verified by hand: 9 full lines of 72
  dots + 33 = 681, matching the handoff's claim exactly.
- `uv run ruff check`: All checks passed.
- `uv run ruff format --check`: 115 files already formatted.
- `uv run pytest tests/parity tests/canaries tests/test_engine.py -q`: all green
  (22/24/37 dots respectively) after the `backtest/context.py` extraction — the
  riskiest change verified in isolation, not just as part of the full suite.
- `git diff --stat` on `src/`: unchanged from the developer's own listing after my
  two mutation checks (both fully reverted, verified with a fresh `git diff --stat`
  each time).

## Findings

1. **[BLOCKING]** `run_once`'s own module docstring and `docs/paper-trading.md`'s
   Guarantees section both now claim "no exit path crashes without leaving a
   record" (quant-gate VERDICT.md cycle-1 finding 3's exact promise). This is
   false for the target-generation stage. `run_once` (`src/quantlab/paper/runner.py:490-547`)
   wraps `_generate_targets_with_actions_refresh` in a `try/except` that catches
   only `StaleActionsCacheError`, `ActionsFetchError`, `BacktestAbortError`, and
   `ValueError` — but `PITDataContext`'s own accessors raise `UndeclaredDataError`
   and `LookaheadError` (`src/quantlab/data/pit.py:387,398,526,563,578,148`), neither
   of which is a `ValueError` (`core/errors.py`: both are direct `QuantLabError`
   subclasses). Any strategy whose `generate_targets` over-reaches its own declared
   `requires()` — a bug in the strategy, not a data-provider condition — crashes
   `run_once` with **zero journal entries**, reproducing cycle-1 finding 3's exact
   failure mode via a different exception class.

   This is not hypothetical: the developer's own new test for finding 5
   (`tests/test_runner.py:833-857`,
   `test_blend_child_overreach_raises_via_run_once_set_context_factory`) triggers
   precisely this path and only asserts `pytest.raises(UndeclaredDataError)` —
   it never checks the journal. I reproduced it directly (fake providers only,
   scratch script deleted afterward, no repository file left modified):

   ```
   raised UndeclaredDataError: True
   journal record count after the crash: 0
   ```

   `configs/strategies/blend_50_50.yaml` ships, so a blend child that under-declares
   its footprint hits this on a real schedule, not just in a fixture.

   **Required remedy:** the fix already applied to the planning/submission stage
   (`runner.py:630-670`, `except Exception as exc:  # noqa: BLE001 - never crash
   without a journal record`) needs to also cover target generation — either widen
   that stage's `except` to a catch-all `Exception` (falling through to a generic
   "target generation failed" refusal record, mirroring the planning-stage pattern),
   or restructure `run_once` with one outer try/except around the whole body so the
   exactly-one-record guarantee is structural rather than enumerated per exception
   type. The current enumerate-by-type approach will keep reopening this exact hole
   for the next exception type nobody thought to list.

2. **[should-fix, non-blocking]** `src/quantlab/backtest/engine.py:380-390` has a
   dead-code fragment left over from moving `_FilteringConstituentsProvider` to
   `backtest/context.py`. `_drop_terminal_partial_period` (lines 369-378) returns
   unconditionally on every path, but a nested `def membership_history(self, start,
   end): return self._inner.membership_history(start, end)` (lines 389-390) sits
   after those returns, indented as part of that function — unreachable, and
   referencing `self`/`self._inner`, neither of which exist in that scope. It never
   executes and ruff doesn't flag it, so it's inert, but it's a clear signal the
   extraction diff (explicitly called out as the riskiest change this cycle) wasn't
   read line-by-line before handoff. Delete lines 380-390; the module docstring's
   own cross-reference comment (kept correctly) doesn't need the orphaned method
   fragment underneath it.

## Everything else verified sound

- **Finding 1 (reconcile bricking)**: fixed and directly verified. I read
  `roll_forward_expected` (`paper/reconcile.py:139-216`) — dividends credit
  `qty * value` to cash on ex-date using the qty already in `expected` (documented
  limitation: doesn't reconstruct intra-window qty changes, correctly still refuses
  if that matters); splits restate `qty`/`avg_cost` identically to `data/pit.py`'s
  own M03b convention. `tests/test_runner.py:884-936`
  (`test_dividend_between_runs_is_explained_and_does_not_brick_the_schedule`)
  reproduces the gate's own four-run scenario verbatim and all four runs proceed.
  `test_unexplained_mismatch_still_refuses_even_with_roll_forward` confirms the fix
  is "explain the ordinary case," not "loosen the check." `accept_broker_state`
  (`runner.py:711-762`, `quantlab paper rebaseline`) is the loud, journaled,
  `kind="rebaseline"` human escape hatch — `known_caveats` always carries "MANUAL
  RE-BASELINE:" verbatim, a refused run never becomes the reconcile baseline
  (`_last_traded_or_rebaselined_record`, `runner.py:364-369`), and the next ordinary
  run reconciles cleanly against a rebaseline
  (`test_accept_broker_state_rebaseline_records_a_loud_diff_and_unblocks_the_schedule`).
  Docs section 5 no longer describes a recovery path that can't work.

- **Finding 2 (shared decision context)**: fixed. `backtest/context.py`'s
  `build_decision_context`/`_FilteringConstituentsProvider` is now the one place
  either `run_backtest` (`engine.py:831-862`) or `run_once`
  (`runner.py:406-420`) builds a decision context, same `max_dropped_fraction`
  abort policy (`PaperRunConfig`, same defaults as `BacktestConfig`). I ran
  `tests/parity`, `tests/canaries`, and `tests/test_engine.py` in isolation after
  the extraction — all green, confirming the "riskiest change" didn't perturb the
  engine's own behavior. `test_one_unclearable_ticker_below_threshold_drops_and_continues_trading`
  (`tests/test_runner.py:603-638`) reproduces the gate's own 40-name/one-unclearable
  probe: the dropped ticker never reaches the strategy, the other 39 rebalance to
  1/39 each (matching the gate's own reported engine behavior), and the drop is
  journaled (`dropped_tickers`, `dropped_fraction`). `abort_on_unscoreable` is
  exercised both ways (`test_abort_on_unscoreable_true_refuses_and_journals`,
  `test_abort_on_unscoreable_false_holds_prior_positions_without_refusing`).

- **Finding 3 (delisted holding)**: the forced-exit mechanism itself is correct.
  `plan_orders`'s new step 8 (`paper/rebalancer.py:116-134`) exits a zero-target,
  nonzero-held ticker to `abs(cur_qty)` without needing a price at all — I hand-
  checked `test_delisted_holding_is_force_exited_journaled_and_never_crashes`
  (50-share DEAD position, no price anywhere): sells exactly 50 shares, journals
  `forced_exits == {"DEAD": "forced exit: no price / delisted"}`, and the broker's
  own rejection of an unpriced order is itself journaled honestly
  (`OrderAckStatus.REJECTED`, never silently dropped or mistaken for a fill). What
  is NOT fully fixed is the general "every exit path journals exactly one record"
  claim this finding also required — see finding 1 above; the delisted-holding case
  specifically is fine, but the promise is broader than that one case and the gap
  I found is in a different exception class from the same stage.

- **Finding 4 (partial fills)**: fixed. `client_order_id_for` gained an `attempt`
  suffix (`paper/broker.py:55-75`); `run_once` cancels resting orders before
  planning each cycle (`_cancel_resting_orders`, `PaperRunConfig.cancel_open_before_plan`
  default `True`) and journals both `canceled_orders` (before planning) and
  `resting_orders` (after submit, so a remainder is visible in the SAME run's
  record, not only retroactively). `MockBroker.submit` (`paper/mock.py:74-90`) and
  `AlpacaPaperBroker._order_to_ack_or_fill` (`paper/alpaca.py:147-164`) now both
  surface every resubmit as `OrderAckStatus.DUPLICATE`, never a replayed `Fill` —
  read both directly, no keys needed for the Alpaca one since the fix is in the
  status-mapping logic, not a network call. I hand-recomputed
  `test_partial_fill_is_topped_up_across_runs_via_cancel_and_fresh_attempt_id`'s
  three runs at 25% fill: 990×0.25=247.5, 247.5+742.5×0.25=433.125,
  433.125+556.875×0.25=572.34375 — matches the gate's own reported
  247.5 → 433.1 → 572.3 sequence.

- **Finding 5 (blend child context)**: the guard itself is correctly restored
  (`run_once` calls `strategy.set_context_factory(context_factory)` when the
  strategy supports it, `runner.py:424-425`, using the identical shared-context
  closure the engine uses) and `test_blend_child_overreach_raises_via_run_once_set_context_factory`
  confirms an over-reaching child raises rather than silently reading extra
  history. The side effect of this fix (the exception it now correctly raises
  crashes with no journal record) is finding 1 above — the guard's restoration
  is right, the run_once robustness around it is not yet complete.

- **Canary (k) mutation-tested by me, both halves**: I deleted
  `resolve_asof`'s `prev_trading_day(today)` ceiling — the original half of canary
  (k) failed as expected. I separately deleted only the NEW data-cache-ceiling
  clamp (`_cached_data_ceiling`'s consumption in `resolve_asof`,
  `runner.py`) — `test_canary_paper_runner_asof_never_exceeds_the_price_caches_last_bar`
  failed with `2024-01-12 <= 2024-01-05`, confirming real power on the half the
  gate said was missing last cycle. Both mutations reverted; `git diff --stat` on
  `runner.py` is clean.

- **Journal widened**: confirmed `journal_to_frame`'s `_FRAME_COLUMNS`
  (`paper/journal.py:157-183`) now carries `kind`, `promoting_report_card`,
  `known_caveats`, `refreshed_actions_tickers`, `dropped_tickers`,
  `dropped_fraction`, `unscored_tickers`, `forced_exits`, `targets`, and
  `assumed_fill_session`. `price_asof_by_ticker` is in the raw JSONL
  (`JournalRecord`) but deliberately not summarized in the frame (documented,
  reasonable — it's a per-ticker dict, not a scalar/count like the other widened
  fields).

- **Docs**: section 5's recovery text now matches what the code does (rebaseline
  command, corporate-action roll-forward explained first). Section 7 documents the
  ~1.5-session paper-vs-backtest timing lag and `assumed_fill_session`. Section 8
  documents the data-degradation/coverage behavior. The Guarantees section's claim
  about "no exit path crashes without leaving a record" needs to become true (see
  finding 1) or be narrowed to what's actually guaranteed today, same category of
  problem the gate flagged for cycle 1's Guarantees paragraph.
