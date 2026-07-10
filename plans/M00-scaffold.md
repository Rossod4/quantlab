# M00 — Core scaffold: types, calendar, config, CLI stub

Goal: Implement the `core/` package (shared contracts every later milestone builds on),
a minimal CLI entrypoint, and the platform config file, with offline tests. The repo
skeleton, pyproject, agents, and protocol already exist — do not touch them.

## In scope (create these)
- src/quantlab/__init__.py, src/quantlab/py.typed
- src/quantlab/core/__init__.py
- src/quantlab/core/errors.py — `QuantLabError` base; `LookaheadError`, `DataQualityError`,
  `ConfigError`, `UnknownStrategyError` subclasses.
- src/quantlab/core/types.py — frozen pydantic v2 models (or frozen dataclasses where
  pydantic adds nothing): `Bar` (date, open, high, low, close, adj_close, volume),
  `TargetWeights` (asof: Timestamp, weights: dict[str, float], strategy_id: str;
  validator: weights finite, no NaN), `Order` (client_order_id, ticker, side, qty,
  order_type), `Fill` (order ref, ticker, qty, price, date, commission),
  `Position` (ticker, qty, avg_cost), `PortfolioSnapshot` (date, cash, positions,
  equity), `DelistingEvent` (ticker, last_trade_date, reason: enum
  {ACQUISITION, BANKRUPTCY, UNKNOWN}).
- src/quantlab/core/calendar.py — thin wrapper over `exchange_calendars` XNYS:
  `trading_days(start, end) -> pd.DatetimeIndex` (tz-naive, midnight-normalized),
  `is_trading_day(date) -> bool`, `next_trading_day(date)`, `prev_trading_day(date)`,
  `rebalance_dates(start, end, freq: Literal["daily","weekly","month_end"]) ->
  pd.DatetimeIndex` (weekly = last trading day of ISO week; month_end = last trading
  day of month).
- src/quantlab/core/config.py — pydantic models: `PlatformConfig` (cache_dir,
  reports_dir, providers: {prices: str, constituents: str, fundamentals: str},
  calendar: str = "XNYS", benchmark: str = "SPY"), loader
  `load_platform_config(path) -> PlatformConfig` (YAML; raise `ConfigError` with the
  offending key on failure). Paths resolve relative to the repo root.
- src/quantlab/cli.py — typer app with subcommands data/backtest/validate/report/paper,
  each currently `raise typer.Exit` after printing "not implemented (M0X)"; `--version`.
- configs/platform.yaml — defaults matching PlatformConfig (providers: yfinance,
  sp500_community, edgar).
- tests/__init__.py, tests/test_calendar.py, tests/test_config.py, tests/test_types.py

## Out of scope
Anything under data/, strategies/, backtest/, validation/, reporting/, paper/. Do not
edit pyproject.toml except to add a missing dependency if a listed one is genuinely
required and absent (justify in handoff).

## Context (read these, nothing else)
- This packet; CLAUDE.md; pyproject.toml

## Acceptance criteria
1. `uv run pytest` green; `uv run ruff check` clean.
2. Calendar spot checks in tests: 2020-11-26 (Thanksgiving) is not a trading day;
   2020-11-27 is; trading_days("2024-01-01","2024-12-31") has exactly 252 days;
   month_end rebalance dates for 2023 == 12 dates and include 2023-06-30 and
   2023-12-29; weekly count for 2023 == 52; next_trading_day(Fri 2024-07-05 18:00
   input normalized) == 2024-07-08.
3. `TargetWeights` with a NaN weight raises; all types are immutable (mutation raises).
4. `load_platform_config` on configs/platform.yaml round-trips; a YAML with a bogus
   key raises `ConfigError` naming the key.
5. `uv run quantlab --help` lists the five subcommands.

## Verification commands
- `uv run pytest tests/ -q` → all pass, zero skipped-for-error
- `uv run ruff check` → no findings
- `uv run quantlab --help` → exits 0

## Parity fixtures
None for M00.
