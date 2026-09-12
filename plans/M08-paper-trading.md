# M08 — Paper trading: Broker ABC, Alpaca paper adapter, rebalancer, journal, runner

Goal: Take a strategy that the report card marked ELIGIBLE_FOR_PAPER and run it against
a paper broker on a schedule, with the SAME `PITDataContext` → `TargetWeights` path the
backtest used (no second signal implementation), idempotent orders, a reconciliation
step that refuses to trade on a mismatch, and an append-only journal that M09's
forward-vs-backtest drift check can read. No live money: the Alpaca adapter is
paper-only by construction, and the Trading212 adapter is a contract-tested stub.

## In scope (create these)
- src/quantlab/paper/__init__.py
- src/quantlab/paper/broker.py — `Broker` ABC: `capabilities() -> BrokerCapabilities`
  (fractional shares, shorting, extended hours, min order notional), `account() ->
  AccountSnapshot` (cash, equity, positions as core.types.Position), `submit(orders:
  list[Order]) -> list[Fill | OrderAck]` (client_order_id is the idempotency key: a
  resubmit with the same id must not double-fill), `open_orders()`, `cancel(id)`,
  `is_market_open(asof)`. Errors typed in core/errors.py (`BrokerError`,
  `ReconcileError`, `NotPaperAccountError`).
- src/quantlab/paper/alpaca.py — `AlpacaPaperBroker` via `alpaca-py` (add dependency
  in an optional extra `[paper]`): credentials ONLY from `ALPACA_API_KEY` /
  `ALPACA_SECRET_KEY` env vars; constructor asserts the endpoint is the paper URL and
  raises `NotPaperAccountError` otherwise — there is no code path to a live endpoint.
  Client order ids = `f"{strategy_id[:12]}-{asof:%Y%m%d}-{ticker}"`. Network tests
  marked `@pytest.mark.network` and skipped without keys.
- src/quantlab/paper/trading212.py — `Trading212Broker` stub implementing the ABC with
  `NotImplementedError` bodies and a capabilities declaration (fractional yes, short no,
  ISA no-margin); contract tests run against it and the mock to pin the ABC.
- src/quantlab/paper/mock.py — `MockBroker`: in-memory, deterministic fills at a
  supplied price map, honours idempotency, simulates partial fills and rejects for tests.
- src/quantlab/paper/rebalancer.py — `plan_orders(targets: TargetWeights, account,
  prices, capabilities, config) -> list[Order]`: drift bands (skip a name if
  |current − target| < band, config default 0.5% of equity), lot rounding (fractional
  if capable else floor to whole shares), no-short guard (a long-only strategy must
  never produce a sell below zero; a target with negative weight on a no-short broker
  raises), cash buffer (config, default 1%), sells before buys ordering, max single
  order notional. Pure function; exhaustively unit-tested with hand cases.
- src/quantlab/paper/reconcile.py — `reconcile(journal_expected, account_actual,
  tolerances) -> ReconcileReport`; any position or cash mismatch beyond tolerance
  raises `ReconcileError` and the runner refuses to trade that day (a human resolves).
- src/quantlab/paper/journal.py — append-only JSONL under `reports_dir/paper/<strategy_id>/`:
  one record per run with asof, targets, planned orders, acks/fills, account before/after,
  reconcile report, data_semantics_version, git sha + dirty, and the `known_caveats` of
  the promoting report card. `journal_to_frame()` for M09's drift dashboard.
- src/quantlab/paper/runner.py — `run_once(strategy_config, platform_config, broker,
  asof=None)`: refresh policy for the actions cache (QUANT-NOTES M02b/M04: call
  `refresh_actions_cache` for the universe when `fetched_at < asof`, log it), build
  `PITDataContext(asof=last completed session)` exactly as the engine does (decision
  path only, `accounting=False`), `generate_targets`, reconcile, plan, submit, journal.
  Promotion gate: `run_once` REFUSES unless a report_card.json for this strategy_id +
  data_semantics_version with verdict ELIGIBLE_FOR_PAPER exists in reports_dir (path
  recorded in the journal); `--force-research` flag bypasses with a loud journal flag
  (for testing the plumbing on a REJECTED strategy in paper — never for real money).
- CLI: `quantlab paper run --strategy <yaml> [--broker alpaca|mock] [--asof DATE]
  [--dry-run]`, `quantlab paper status`, `quantlab paper journal --strategy <yaml>`.
- docs/paper-trading.md — Windows Task Scheduler setup (monthly on the first session
  after month-end, 16:30 ET → 21:30 UK; `schtasks` command line), env-var setup, what
  a ReconcileError means and how to clear it, and the explicit statement that this
  system never touches a live account.
- tests: test_broker_contract.py (parametrised over Mock + Trading212 stub + Alpaca
  when keys present), test_rebalancer.py, test_reconcile.py, test_journal.py,
  test_runner.py (mock-broker E2E: two consecutive runs, second is idempotent; a
  planted mismatch refuses to trade; promotion gate refuses a REJECTED card;
  --force-research flags the journal), test_cli_paper.py. Extend
  tests/canaries/test_lookahead.py with (k): the runner's context asof is the last
  COMPLETED session, never today's partial session, and never later than the data's
  last cached bar.

## Out of scope
Live trading of any kind. Trading212 real implementation (post-v1). Intraday.

## Context (read these, nothing else)
- This packet; CLAUDE.md; plans/QUANT-NOTES.md (M02b staleness refresh policy; M04
  runner items); docs from alpaca-py for the paper TradingClient (read the installed
  package docstrings, no web)
- src/quantlab/core/{types,errors,config}.py; src/quantlab/data/{pit,corporate_actions}.py;
  src/quantlab/backtest/engine.py (how contexts are built — mirror it);
  src/quantlab/strategies/{base,registry}.py; src/quantlab/validation/report_card.py;
  src/quantlab/cli.py

## Interfaces to honor
`Order`, `Fill`, `Position`, `PortfolioSnapshot` from core/types.py. `PITDataContext`
and `Strategy` unchanged. Credentials never in code or config.

## Acceptance criteria
1. `uv run pytest` green offline (Alpaca tests skipped without keys); ruff clean.
2. Idempotency: resubmitting the same client_order_id to Mock and (with keys) Alpaca
   does not double-fill.
3. Rebalancer hand cases: drift band, rounding, cash buffer, no-short guard, sells-first.
4. Reconcile refuses on a planted mismatch; journal records it.
5. Promotion gate enforced; `--force-research` leaves a loud flag.
6. Canary (k) passes and fails under mutation (asof = today).
7. Alpaca paper: constructor rejects a non-paper endpoint (unit test with a fake URL);
   with keys, a network-tier smoke test places and cancels one tiny order.
8. docs/paper-trading.md complete enough for Alex to schedule it without asking.

## Verification commands
- `uv run pytest tests/ -q`; `uv run ruff check`; `uv run ruff format --check`
- `uv run quantlab paper --help`; `uv run quantlab paper run --strategy
  configs/strategies/momentum_12_1.yaml --broker mock --dry-run`
