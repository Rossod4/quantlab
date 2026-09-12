REVIEW: APPROVE

# M08 review (iteration 1)

## Verification commands
- `uv run pytest tests/ -q`: exit 0. Dot count verified by hand: 9 full lines of 72
  dots + 1 line of 12 dots = 660, matching the handoff's claim exactly. 0 failures.
  Alpaca network tests (2) and 2 pre-existing network tests deselected by
  `addopts = "-q -m 'not network'"`.
- `uv run ruff check`: All checks passed.
- `uv run ruff format --check`: 114 files already formatted.
- `uv run quantlab paper --help`: renders `run`/`status`/`journal` subcommands correctly.
- `git diff --stat` confirms only `src/quantlab/cli.py`, `src/quantlab/core/errors.py`,
  `tests/canaries/test_lookahead.py` were touched outside the new `paper/` package and
  new test files — matches the handoff's file list exactly.

## Findings

1. [minor] `tests/test_runner.py` covers the actions-cache refresh policy's happy path
   (`test_stale_actions_cache_triggers_a_universe_wide_refresh_and_retries`) but there is
   no test for the packet's other half of item 7: "a second failure surfaces (no infinite
   loop)". I confirmed by reading `runner.py:203-205`
   (`_generate_targets_with_actions_refresh`) that the retry call is *not* wrapped in a
   second `try/except`, so a second `StaleActionsCacheError` necessarily propagates
   uncaught — the code is correct — but this specific behavior has no regression test.
   Fix expected: one test with a `CorporateActionsProvider` fake that always raises
   `StaleActionsCacheError` (never clears after refresh), asserting `run_once`/
   `_generate_targets_with_actions_refresh` raises `StaleActionsCacheError` rather than
   looping or swallowing it.

Nothing else rises above minor. Per-item results below.

## Per-item results (team-lead's checklist)

1. **No live-money path, by construction** — Confirmed. `paper/alpaca.py`'s
   constructor always passes `paper=True` and additionally asserts
   `client._base_url == BaseURL.TRADING_PAPER`, raising `NotPaperAccountError`
   otherwise; `tests/test_alpaca_broker.py::test_constructor_rejects_a_resolved_non_paper_endpoint`
   fakes the client to resolve `BaseURL.TRADING_LIVE` and asserts the raise. Credentials
   read only from `ALPACA_API_KEY`/`ALPACA_SECRET_KEY` (`os.environ.get`), never logged
   (grepped all of `paper/*.py` for logging/print near "key"/"secret"/"cred" — none).
   Grepped the whole package for `api.alpaca.markets`, `paper=False`, hardcoded keys —
   none found; the only "live" hits are docstring prose about there being no live path.

2. **Idempotency** — Confirmed. `MockBroker.submit` checks `order.client_order_id` against
   `self._processed` first and replays the cached outcome
   (`tests/test_broker_contract.py::test_mock_broker_resubmitting_the_same_client_order_id_is_idempotent`
   asserts `first == second` and account state unchanged). `client_order_id_for` in
   `paper/broker.py` is a pure function of `(strategy_id, asof, ticker)` only — no wall
   clock, no object identity. `Trading212Broker` passes the same parametrized contract
   tests as `MockBroker` for `capabilities()`, and its other methods correctly raise
   `NotImplementedError` per its documented stub status.

3. **Rebalancer hand cases** — Recomputed by hand:
   - `test_buy_from_flat_uses_investable_equity_after_cash_buffer`: 100,000 × 0.99 × 0.5 /
     100 = 495. Matches.
   - `test_whole_share_rounding_floors_fractional_quantity`: 1000/33 = 30.30 → floor 30.
     Matches.
   - `test_max_order_notional_clips_a_large_order`: target 100,000 capped to 10,000 / 100
     = 100 shares. Matches.
   - `test_negative_target_weight_is_fine_when_the_broker_can_short`: target −20,000,
     current 0 → sell 200 shares. Matches, correctly routed to a SELL.
   - `test_sells_are_returned_before_buys`: AAA drift 10% (sell 1000 shares) then BBB buy
     2500 shares — sells-list-then-buys-list ordering confirmed in code (two separate
     lists, concatenated `sells + buys`).
   Rounding never over-spends cash after the buffer: `qty` is only ever floored (never
   ceil'd) when `not fractional_shares`, so a rounded order's cost is always ≤
   `target_dollars` ≤ `investable_equity` — the 1% buffer can only be preserved or
   exceeded, never eaten into by rounding. No-short guard raises `ValueError` *before* any
   order is planned (checked up front against the raw `targets.weights`, not per-ticker
   mid-loop).

4. **Runner decision context** — Confirmed. `_decision_context` passes `accounting`
   unset (defaults `False`, `data/pit.py`), the same `requirements = strategy.requires()`,
   and omits `panel_store` (`None`) — read `data/pit.py:434-441`: `panel_store` is a pure
   in-memory-caching optimization for a backtest's many repeated calls over one run; when
   `None`, `prices()` falls back to the raw `price_provider` directly, producing identical
   values either way, so omitting it for a single-`asof`-per-invocation paper run is
   correct, not a shortcut. `resolve_asof` clamps to both `prev_trading_day(today)`
   (unconditional ceiling) and the price cache's actual last bar
   (`_cached_data_ceiling`). I independently reproduced the mutation check: changed
   `resolve_asof`'s `safety_ceiling = prev_trading_day(today)` to `safety_ceiling = today`,
   reran `tests/canaries/test_lookahead.py -k canary_paper_runner`, got the same failure
   the handoff reported (`assert Timestamp('2024-01-16') < Timestamp('2024-01-16')`),
   reverted, and reconfirmed the canary and `git diff --stat` on `runner.py` are clean
   (no diff — the file matches the developer's committed-to-tree version).

5. **Promotion gate** — Confirmed. `find_promoting_report_card` requires *both*
   `provenance.get("strategy_id") == strategy_id` and
   `provenance.get("data_semantics_version") == data_semantics_version` (exact string
   equality on both, plus `verdict == "ELIGIBLE_FOR_PAPER"`) before a card counts — a card
   for a different semantics version or a different strategy cannot match.
   `strategies/base.py::strategy_id` is `f"{name}-{sha256(canonical_params_json)[:10]}"` —
   deterministic and content-addressed, so a "stale" card for an old param set naturally
   has a different `strategy_id` and cannot silently promote a changed strategy.
   `--force-research` is exercised end-to-end
   (`test_force_research_bypasses_the_gate_and_flags_the_journal`): journal's
   `known_caveats` gets an unmissable `"FORCE-RESEARCH: ..."` entry and `force_research`
   is `True` on the record.

6. **Reconcile** — Confirmed. `test_planted_mismatch_refuses_to_trade` plants a $5,000
   cash mismatch, asserts `ReconcileError` is raised and the journaled record has
   `planned_orders == []`. Reading `runner.py:354-390`, the reconcile check and its
   `raise ReconcileError` happen structurally *before* `plan_orders`/`broker.submit` are
   ever called (lines 392+) — a mismatch physically cannot reach the broker, not merely
   "happens not to" in the test fixture. `tests/test_reconcile.py` exercises
   `build_reconcile_report`/`reconcile` directly with exact-value hand cases (cash within/
   beyond tolerance, position mismatch, one-sided position, JSON round-trip).

7. **Refresh policy** — Confirmed for the success path
   (`test_stale_actions_cache_triggers_a_universe_wide_refresh_and_retries`: refreshes the
   whole declared universe, not just the offending ticker, and retries exactly once).
   See finding 1 above: the "second failure surfaces" half of this item is correct by
   code inspection but untested.

8. **Journal** — Confirmed append-only (`append_journal` opens `"a"` only, never
   rewrites; `test_append_is_append_only_across_multiple_runs` appends two records and
   reads both back in order). One record per run including on refusal (`_refuse`/the
   reconcile-refusal branch/the promotion-gate-refusal branch each construct exactly one
   `JournalRecord` and `append_journal` once). Every field the packet lists is present
   (`asof`, targets, planned orders, results/acks/fills, account before/after, reconcile
   report, `data_semantics_version`, git sha + dirty, `known_caveats`).
   `journal_to_frame` round-trips correctly
   (`test_journal_to_frame_is_indexed_by_asof_and_has_documented_columns`).

9. **The dry-run CLI on the real cache** — I agree with the developer: a dry run against
   the real, shared `data/cache` **could** write there, and I did not run it. Tracing the
   dry-run code path (`cli.py`'s `paper_run` dry-run branch → `build_backtest_providers`
   → the real `yfinance`/`edgar`/`sp500_community` providers configured in
   `configs/platform.yaml`), all three providers write-through to disk on any cache
   miss or stale "no data" marker, independent of `--dry-run`/`--broker mock` (dry-run
   never touches the actions-refresh path, but it does call `strategy.generate_targets`,
   which calls `ctx.prices()`/`ctx.universe()`/`ctx.fundamentals()` against the real
   providers):
   - `src/quantlab/data/providers/yfinance_prices.py:162-173` — a cold ticker or a range
     not already covered writes `price_cache_path(ticker, cache_dir)` (a parquet under
     `data/cache`) plus its meta file via `write_price_cache_meta`.
   - `src/quantlab/data/providers/edgar_fundamentals.py:120,197` — `write_cache` to
     `cache_dir / "sec_ticker_cik_map.parquet"` and
     `cache_dir / "fundamentals" / f"{ticker}.parquet"`.
   - `src/quantlab/data/providers/sp500_constituents.py:88-95` — `write_cache` to
     `cache_dir / "sp500_constituents.parquet"` when its own cache is stale.
   Whether `momentum_12_1.yaml`'s exact universe/date range is "fully warm" in the shared
   cache right now isn't something I can verify without risking exactly the write this
   worktree is forbidden from making, so per the team-lead's instruction I did not run it.
   `tests/test_cli_paper.py` exercises the identical CLI dry-run code path against fake
   providers only, which is sufficient coverage for this milestone's own tests.

10. **docs/paper-trading.md** — Sufficient for Alex to schedule it. I verified the
    `schtasks` line is syntactically correct by creating and immediately deleting a real
    scheduled task with the doc's exact `/SC MONTHLY /D 1 /ST 21:35` arguments on this
    machine (`schtasks /Query` confirmed `Schedule Type: Monthly`, `Days: 01`,
    `Months: Every month` before I deleted it). The doc correctly explains that `/D 1`
    firing on a non-trading calendar day is harmless because `resolve_asof` always steps
    back to the last completed session regardless of which day the task fires. Env-var
    setup (`ALPACA_API_KEY`/`ALPACA_SECRET_KEY`, User-scope vs. session-only, and the
    Task-Scheduler visibility caveat) is covered. `ReconcileError` recovery is explained
    with concrete causes and a concrete recovery path (let the next clean run reset the
    baseline, or start a fresh journal file). The explicit "never touches a live account"
    statement is present up top and repeated in the Guarantees section, backed by real
    mechanism (not just prose).
