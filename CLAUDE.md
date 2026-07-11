# QuantLab

Bias-free EOD systematic trading research platform. US equities. Research + paper trading only — no live money. **Never propose chart-pattern/technical-pattern analysis.**

## Commands
- If `uv` is not on PATH in your shell, use `python -m uv` (identical behavior).
- Env/deps: `uv sync` (Python 3.12+; dev group includes pytest/ruff)
- Tests: `uv run pytest` (offline by default; network tier: `uv run pytest -m network`)
- Lint: `uv run ruff check` and `uv run ruff format --check`
- CLI: `uv run quantlab --help` (data | backtest | validate | report | paper)

## Non-negotiable invariants
1. **No look-ahead by construction.** Strategies only ever receive a `PITDataContext` (src/quantlab/data/pit.py) hard-bound to its `asof` date. Never hand a strategy a raw provider or unsliced frame. Fundamentals gate on SEC `filed` date, not fiscal period.
2. **Survivorship is measured, not footnoted.** Every `BacktestResult` embeds the universe coverage-gap bound from `data/survivorship.py`.
3. **Delistings book a forced exit** at last available price (haircut configurable) — never silently dropped.
4. **Ported numerical logic is frozen.** Code ported from `..\MomentumValueStrategy` must pass `tests/parity/` golden tests to 1e-10 (signals) / documented tolerance (equity curves). Do not "improve" it.
5. **Tests are offline and deterministic.** Fixtures live in `tests/fixtures/`. Network-touching tests get `@pytest.mark.network`.
6. Bias canaries in `tests/canaries/` must always pass; extend them when adding data paths.

## Build process (agent loop)
**Resuming this project? Read `plans/ORCHESTRATOR-HANDOFF.md` first — it has the
current milestone state and exact next action.**
The platform is built milestone-by-milestone via subagent loops — see `plans/PROTOCOL.md`. Work packets are `plans/M0X-*.md`; loop artifacts go in `plans/state/M0X/`. Agents: `.claude/agents/{developer,code-reviewer,quant-gate}.md`. Do not implement milestone code in the main session; dispatch the loop.

## Conventions
- pydantic v2 models for config (`core/config.py`), YAML in `configs/`; no hardcoded paths — everything flows from `configs/platform.yaml`.
- Typed code (`from __future__ import annotations`), ruff-clean, no notebooks as source of truth.
- Dates are timezone-naive `pd.Timestamp` normalized to midnight, NYSE calendar from `core/calendar.py`.
- Broker credentials only via environment variables (`ALPACA_API_KEY` / `ALPACA_SECRET_KEY`); never in code or config files.
