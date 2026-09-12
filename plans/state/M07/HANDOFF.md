# M07 Reporting — HANDOFF (iteration 1; see `HANDOFF.2.md` for the REVISE response)

## Files changed
- New: `src/quantlab/reporting/{__init__,plots,context,render}.py`,
  `src/quantlab/reporting/templates/{report.html,report.md}.j2`.
- New tests: `tests/{_report_fixtures,test_plots,test_report_context,test_render,
  test_cli_report}.py`.
- Modified: `src/quantlab/cli.py` — added `report` command; `_report_card_markdown`
  now renders the M07 markdown template (plots skipped, so `validate --full` stays
  fast) instead of the old `{gate.value!r}` stopgap; all three `--full` writes use
  `encoding="utf-8"` explicitly (a Windows-only crash otherwise, see item 7 below).
- Modified: `src/quantlab/validation/reality_check.py` (orchestrator-requested
  addendum, before review) — added `MEASURED_SIZE_AT_SHIPPED_BLOCK_LEN`/
  `MEASURED_SIZE_BLOCK_LEN`/`NOMINAL_SIZE_BAR`; corrected the module docstring's
  stale pre-p-value-fix numbers (0.123/0.128 → 0.117/0.118).
- New artifacts (not code): `plans/state/M07/fixtures/{rejected,research_only,
  eligible}/{result,out}/` — the three M06-shaped verdicts, each with a saved
  `BacktestResult`+`report_card.json` and its rendered `report.html`/`report.md`.

## Design decisions / deviations
1. `build_report_context(result, report_card, config)` takes `report_card` as
   `ReportCard.to_json()`'s **dict**, not the dataclass — matches `render.py`
   loading `report_card.json` from disk; `report_card=None` degrades every
   section gracefully (basic-only `validation_basic.json` fallback synthesizes a
   minimal dict with verdict=None, gates=[]).
2. `plot_universe_size` uses a portfolio-size proxy (nonzero-weight count per
   rebalance) — `BacktestResult` has no per-rebalance universe-size series.
3. `plot_monte_carlo_fan` redraws fresh paths via `monte_carlo.block_bootstrap_paths`
   since `MonteCarloResult` stores only scalar percentiles, not time-indexed paths.
4. **Escalation, not fixed here**: `WalkForwardResult` doesn't retain per-step
   training Sharpes (M05/M06 item, belongs to whoever next touches
   `validation/walk_forward.py`) — the report states this rather than fabricating
   it. Same for "ranking agreement under both cost conventions" — hardcoded "not
   checked" since nothing computes it yet.
5. ~~Jinja autoescape disabled for both templates~~ — **WRONG, reverted in
   HANDOFF.2.md**: it papered over a real HTML-injection surface (ticker
   symbols / YAML values reaching gate reasons unescaped). Left here for the
   record rather than deleted.
6. `tests/test_render.py`'s `rendered` fixture is module-scoped, keyed by verdict
   param (was function-scoped) — cut full-suite time from ~91s to ~56s by building
   each report card's real bootstrap/PSR/DSR pipeline once per verdict, not once
   per assertion.
7. RC/SPA gate details state the documented measured over-sizing
   (`reality_check.py`'s new constants) beside the badge, block-len-gated so it's
   never misattached to a run at a different block length.

## Verification
- `uv run pytest tests/ -q`: **exit 0**, 668 dots (all pass), ~56s wall time.
- `uv run ruff check .`: all checks passed. `uv run ruff format --check .`: 107
  files already formatted.
- `uv run quantlab report --help`: works.
- Three verdict renders (criterion 2): all under 5MB (355/256/283KB html,
  12/12/14KB md). Criteria 3 (verbatim strings) and 4 (numeric parity) covered by
  `test_render.py` on all three verdicts.

## Open questions / carried forward
- Item 4 above remains open against `validation/walk_forward.py`.
- Provenance appendix's "cache dir" isn't in `engine.py`'s provenance dict; shown
  as "not recorded" rather than guessed.
