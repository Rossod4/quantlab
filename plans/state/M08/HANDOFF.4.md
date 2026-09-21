# M08 handoff (iteration 4 — addresses VERDICT.2.md's two blockers + 3 notes)

## Files
Edited: `backtest/context.py` (`actions_fetched_at` moved here from `engine.py`, public
now), `backtest/engine.py` (re-points to it), `paper/runner.py` (`_proactive_actions_refresh`,
`_refuse` account guard, `_next_attempt_number`/`cancel_open_before_plan` docstring fixes,
submit-stage `planned_orders` passthrough), `docs/paper-trading.md` (KeyboardInterrupt
clause), `tests/test_runner.py` (3 new proactive-refresh tests, 1 new account-failure
test, an autouse safety fixture, 2 pre-existing tests re-asserted for the new two-line
refresh behavior). No other files touched.

## Blocker 1 — proactive refresh
`_proactive_actions_refresh` runs BEFORE the decision context is built: reads
`actions_fetched_at` (moved to `backtest/context.py`, was `engine.py`'s private
`_actions_fetched_at`) for the strategy's declared universe (`needs_universe`) AND every
currently held ticker, force-refreshes any missing/stale relative to `asof`, logs the
list. The reactive catch-and-retry in `_generate_targets_with_actions_refresh` is kept as
a second line; `refreshed_tickers` is the union of both passes. This is the exact remedy
VERDICT.2.md specified — read the sidecar directly, refresh, THEN build the context —
closing the gap where the shared filter (cycle-2's own fix) silently converted staleness
into a drop before a reactive-only check could ever see it.

Three new regression tests via `run_once` using the shipped shape
(`needs_universe=True, price_lookback_days=1`, matching `momentum_12_1.yaml`):
(a) whole 5-ticker universe stale → `refresh_actions_cache` called once per ticker, run
trades all 5, no `BacktestAbortError`; (b) 1 of 40 stale (39 have real, fresh sidecar
files written) → refreshed and INCLUDED, `refresh_actions_cache` called for that ticker
ONLY; (c) refresh itself fails (`ActionsFetchError`) for 1 of 40 → dropped via the shared
filter, `dropped_fraction≈0.025`, run proceeds on 39. Added an autouse
`_no_real_actions_refresh` fixture (no-op spy by default) after discovering the proactive
pass, unguarded, made nearly every `needs_universe=True`/held-position test in this file
attempt a REAL network call (one test measured 12.9s; after the fixture, back to
sub-second) — tests that specifically exercise refresh behavior re-monkeypatch the same
name locally, overriding the default. The two pre-existing `_ActionsProbeStrategy` tests
(a declaration shape the filter does NOT engage for) are kept, re-asserted for two
refresh attempts (proactive + reactive) instead of one, since both lines now run.

## Blocker 2 — guarded `_refuse`
`_refuse`'s own `broker.account()` call is now wrapped: on failure, `account_before`/
`account_after` become `{"unavailable": "<ExceptionClass>: <msg>"}` and `reason` gets an
appended "ALSO: broker.account() failed..." clause, so the run still leaves exactly one
record naming the stage and both causes. New test: a broker whose `account()` raises
during a stage-`targets` failure still produces exactly one record with the marker.

## Non-blocking items, all done
`_refuse` now accepts `planned_orders` (defaults `[]`); the submit-stage refusal passes
the actually-planned orders through instead of losing them. `_next_attempt_number` now
excludes refused records (`refused_reason is None` added to its filter) so a refusal
before planning doesn't burn an attempt number. `PaperRunConfig.cancel_open_before_plan`'s
docstring now states plainly that `False` can stack a second live order on a still-resting
first one. `docs/paper-trading.md`'s Guarantees section now states the `KeyboardInterrupt`
exclusion and why (per the gate's own ruling — no behavior change, docs only).

## Tests
`uv run pytest tests/ -q`: **exit 0, 690 dots, 0 failures/skips** (686 + 4 new).
`uv run ruff check .`: clean. `uv run ruff format --check .`: clean (115 files).
`git status --porcelain`: no writes under `data/`.
