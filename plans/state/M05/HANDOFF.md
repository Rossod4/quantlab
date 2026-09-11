# M05 Validation I — HANDOFF

## Files created
- `src/quantlab/validation/{__init__,metrics,rolling,walk_forward,sensitivity,basic}.py`
- `configs/validation.yaml`
- `tests/_validation_fixtures.py` (shared offline `BacktestResult` builder)
- `tests/test_{metrics,rolling,walk_forward,sensitivity,validation_basic}.py`
- `tests/parity/test_{metrics,walk_forward}_parity.py`
- `tests/canaries/test_no_prices_for_returns_in_strategies.py`

## Files modified
- `src/quantlab/cli.py`: `validate` command implemented (basic tier only).

## Design decisions / deviations
1. `validate_basic(result, benchmark_result, config)` matches the packet's
   three positional args, but walk-forward/sensitivity are accepted as
   optional **precomputed** results via keyword-only args, never run
   internally — walk-forward needs each child sleeve's own return series
   (not one blended `BacktestResult`'s) and sensitivity needs a
   strategy_config + injected runner, neither in scope for a single-result
   call. Documented in `basic.py`'s module docstring.
2. `tests/parity/test_walk_forward_parity.py` wasn't in the packet's
   literal "In scope" file list (only `test_metrics_parity.py` was) but is
   required by acceptance criterion 3; added alongside the metrics parity
   test since both import the old repo via `sys.path`.
3. Parity approach: `sys.path` import of the old repo (not hard-coded
   constants) — documented in both parity files' docstrings.
4. `metrics.summary(result, benchmark_result=None)` accepts an optional
   full `BacktestResult` to override `result`'s embedded benchmark series
   (e.g. an independently-costed benchmark run); `None` uses the embedded
   `benchmark_returns`/`benchmark_equity`, matching the packet's literal
   signature when unused.
5. `PERIODS_PER_YEAR` includes `"quarter_end": 4` defensively per the
   packet's own listing, though `RebalanceFreq` doesn't currently emit it.
6. Carried M04 verdict item 2 ("nonzero extreme_returns must appear in the
   one-line summary") is satisfied by M04's own `backtest` CLI, which
   already prints it; M05's `validate` CLI surfaces it via
   `ValidationBasic.flags` instead of duplicating a one-liner.

## Verification
- `uv run pytest tests/ -q`: exit 0, 398 dots, 0 failures.
- `uv run ruff check`: all checks passed (repo-wide).
- `uv run ruff format --check`: 79 files already formatted.
- `uv run quantlab validate --help`: OK.
- Manual end-to-end smoke test: built a fixture `BacktestResult`, saved to
  disk, ran `quantlab validate --result ... --out ...` as a real subprocess
  — produced a sensible one-liner, flags, and a valid `validation_basic.json`.

## Open questions
- `degenerate_excluded_book_dates` isn't surfaced in `ValidationBasic.flags`
  (not one of the packet's enumerated "once each" counters) — flag if M06
  wants it folded in.
- No shipped strategy config currently produces nonzero
  `extreme_returns_short`/coverage-bound values, so the flags text is
  exercised only by synthetic fixtures, not a real run, in this milestone.
