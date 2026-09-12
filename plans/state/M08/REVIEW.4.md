REVIEW: APPROVE

# M08 review (iteration 4, closes VERDICT.2.md's two blockers)

## Verification commands
- `uv run pytest tests/ -q`: exit 0. Dot count verified by hand: 690/690 (matches
  the handoff's claim; 686 + 4 new).
- `uv run ruff check`: All checks passed.
- `uv run ruff format --check`: 115 files already formatted.
- `git diff --stat` / `git status --short`: matches the developer's file list
  exactly (`engine.py`, `cli.py`, `core/errors.py`, `plans/QUANT-NOTES.md`,
  `tests/canaries/test_lookahead.py` tracked; `paper/`, `backtest/context.py`,
  `docs/` and new test files untracked). No writes under `data/`. All scratch
  probe scripts I used were deleted before finishing.

## Findings

None. Both of the gate's cycle-2 blockers are closed and I verified each with my
own independently-constructed reproduction, not just by re-running the
developer's tests.

## Per-item verification (team-lead's checklist)

1. **Reproduced the gate's two probes with `momentum_12_1.yaml`'s REAL
   `requires()` shape** (not a test-fixture double): wrote a throwaway script
   that loads the actual strategy via
   `load_strategy("configs/strategies/momentum_12_1.yaml")` and runs it through
   the real `run_once`, against 40 fake tickers, `fetched_at=2023-12-02`,
   `asof=2023-12-29` — the gate's exact numbers.
   ```
   all 40 stale:   TRADED, refused_reason=None, dropped_tickers=[], n_targets=30,
                   refresh_calls=40 (all 40 tickers)
   1 of 40 stale:  TRADED, refused_reason=None, dropped_tickers=[], n_targets=30,
                   refresh_calls=1 (['T000'] only)
   ```
   (`n_targets=30` matches `momentum_12_1.yaml`'s own `n_long: 30`, not a bug —
   momentum picks its top 30 by ranking regardless of universe size.) Both
   outcomes are exactly what the gate's remedy demanded and the opposite of what
   VERDICT.2.md reproduced (a `BacktestAbortError` refusal above threshold, a
   silent permanent drop below it). Confirmed by reading the code:
   `_proactive_actions_refresh` (`runner.py:249-309`) runs at `stage="context"`
   (`runner.py:627-630`), strictly before `set_context_factory`/the decision
   context is ever built, reading `actions_fetched_at` (moved to
   `backtest/context.py:52-70`, a straight lift of `engine.py`'s former private
   `_actions_fetched_at` plus the module boundary the docstring explains) over
   the declared universe and every held ticker.

2. **Failing-refresh case.** Ran the developer's
   `test_proactive_refresh_failure_for_one_ticker_still_drops_it_via_the_shared_filter`
   directly (passed), then reproduced it myself against the real
   `momentum_12_1.yaml` strategy (refresh raises `ActionsFetchError` for one of
   40 tickers): `dropped_tickers=['T000']`, `dropped_fraction=0.025`, `T000` not
   in `targets.weights`, `refused_reason=None`, run proceeds on the other 39,
   exactly one journal record. Matches `_proactive_actions_refresh`'s own
   documented behavior: a ticker whose refresh itself fails is left un-refreshed
   and falls through to the shared filter's existing drop-and-count path
   (`runner.py:304-308`), which is the correct place for a genuine data failure
   to be counted, as opposed to routine staleness.

3. **`engine.py` provenance after the `actions_fetched_at` move.** Read
   `engine.py:1199` directly: `fetched_at = actions_fetched_at(providers.cache_dir,
   all_encountered_tickers)`, now imported from `backtest.context` — call site
   unchanged apart from the import. This line runs unconditionally at the end of
   nearly every `run_backtest` call in `tests/test_engine.py`, so a regression in
   the moved function would show up broadly, not just in one dedicated test; ran
   `tests/parity`, `tests/canaries`, `tests/test_engine.py` in isolation: 83/83
   green, same count as iteration 3.

4. **Confirmed the autouse fixture cannot mask a regression.** Mutated
   `runner.py` to delete the `_proactive_actions_refresh` call entirely
   (`refreshed_tickers = _proactive_actions_refresh(...)` → `refreshed_tickers =
   []`), reran the three proactive-refresh tests: all three FAILED, each with
   `BacktestAbortError` (`40/40` or a large majority of tickers "failed a
   data-availability probe"), confirming they exercise the real code path and
   would have caught the exact cycle-2 regression had it still been present.
   Reverted; `diff` against the pre-mutation backup is byte-identical, and the
   three tests pass again.

5. **`broker.account()` raising during a targets-stage failure.** Ran the
   developer's `test_a_failing_broker_account_still_leaves_exactly_one_record`
   directly (passed): a broker whose `account()` raises, combined with a
   strategy whose `generate_targets` raises an unrelated
   `_UnexpectedTestError`, still produces exactly one record, with
   `stage='targets'`, both exception classes named in `refused_reason`
   (`... ALSO: broker.account() failed ...`), and `account_before`/
   `account_after` both set to the documented
   `{"unavailable": "<ExceptionClass>: <msg>"}` marker. Read `_refuse`
   (`runner.py:552-597`) directly: the account fetch is now its own inner
   `try/except`, and I additionally re-ran my own iteration-3 probes (a
   `KeyboardInterrupt`-raising strategy, and a two-call unexplained-mismatch
   double-journal check) against this iteration's code to confirm neither
   guarantee regressed while `_refuse`'s signature changed to accept
   `planned_orders`:
   ```
   [KeyboardInterrupt] raised: KeyboardInterrupt records: 0   (unchanged, correct)
   [double-journal] raised ReconcileError: True n1: 1 n2 (want +1): 2   (unchanged, correct)
   ```

6. **Full suite, ruff, diff.** 690/690 (hand-counted), `ruff check`/
   `ruff format --check` clean, `git diff --stat`/`git status --short` match the
   developer's iteration-4 file list exactly, no writes under `data/`.

## Non-blocking items from VERDICT.2.md — confirmed addressed

- `_refuse` now accepts `planned_orders` and the submit-stage refusal passes the
  actually-planned orders through (read directly, `runner.py`'s submit-stage
  except clause).
- `_next_attempt_number` now excludes refused records (`refused_reason is None`
  added to the filter, `runner.py:420-437`) — a refusal before planning no
  longer burns an attempt number.
- `docs/paper-trading.md`'s Guarantees section now states the
  `KeyboardInterrupt` exclusion and why, per the gate's own ruling.

## Summary across all four iterations

All five cycle-1 blocking findings, cycle-2's one blocking finding (the
structural exactly-one-record guarantee), and this cycle's two blocking findings
(proactive actions-cache refresh; a failing `broker.account()` inside the
refusal writer itself) are fixed and independently verified against the real
shipped strategy shape, not merely re-read from the developer's own tests. The
milestone is ready for the quant gate.
