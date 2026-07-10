# M00 — Core scaffold: HANDOFF (iteration 1)

## Files changed
- src/quantlab/__init__.py, src/quantlab/py.typed
- src/quantlab/core/__init__.py, errors.py, types.py, calendar.py, config.py
- src/quantlab/cli.py
- configs/platform.yaml
- tests/__init__.py, tests/test_calendar.py, tests/test_config.py, tests/test_types.py

## Design decisions / deviations
- **Enums as `enum.StrEnum`** (`Side`, `OrderType`, `DelistingReason`) instead of
  `(str, Enum)` — ruff UP042 on py312 target requires this; behavior identical.
- **`Order.order_type`** limited to `MARKET`/`LIMIT` (packet didn't enumerate values);
  extend when a real order router needs more.
- **`Fill.client_order_id`** used as the "order ref" field (packet said "order ref"
  without a name) to join back to `Order`.
- **`PortfolioSnapshot.positions`** typed `dict[str, Position]` keyed by ticker (packet
  didn't specify container shape) — natural for O(1) lookup later.
- **Immutability**: all core types use pydantic `frozen=True`; attribute reassignment
  raises `pydantic.ValidationError` (subclass of nothing special — tests assert via
  `pytest.raises(ValidationError)`). Note this does not deep-freeze contained
  `dict`/`weights` values in place (`tw.weights['x']=1` would still mutate) — only
  top-level attribute reassignment is blocked. Flagged here since the packet's
  wording ("mutation raises") is satisfied at the attribute level, which is the
  standard pydantic frozen-model contract; deep immutability wasn't requested.
- **`config.py` repo-root resolution**: walks up from `core/config.py` until it finds
  `pyproject.toml`, rather than assuming a fixed `parents[N]` depth or CWD. Relative
  `cache_dir`/`reports_dir` in the YAML resolve against that root.
- **`cli.py` stub text**: used the literal `"not implemented (M0X)"` placeholder from
  the packet text for all five subcommands (no per-command milestone mapping was in
  scope/context to resolve `M0X` to real milestone numbers); `raise typer.Exit()`
  with default exit code 0, matching the packet's literal phrasing.
- No dependency changes; pyproject.toml untouched.

## Environment note (not a code change, for the next iteration's awareness)
The project's editable install in `.venv` predates these source files (it was
installed when `src/quantlab/` was empty), so `import quantlab` failed until I ran:
`python -m uv pip install -e . --no-deps --python "./.venv/Scripts/python.exe"`
(global Python has the `uv` module; `uv`/`uv.exe` is not on PATH and the project
venv has no `pip`). This only reinstalled the local editable package, no
dependency/lock changes. If a future iteration hits `ModuleNotFoundError: No module
named 'quantlab'`, re-run that same command rather than `uv sync`.

## Test command + output
- `./.venv/Scripts/python.exe -m pytest tests/ -q` → **26 passed**, 0 skipped/error.
- `./.venv/Scripts/python.exe -m ruff check` → **All checks passed!**
- `./.venv/Scripts/python.exe -m ruff format --check` → **11 files already formatted**.
- `./.venv/Scripts/quantlab.exe --help` → exit 0, lists `data backtest validate
  report paper` + `--version`.
- Spot-checked acceptance criteria directly (Thanksgiving 2020, 252 trading days in
  2024, 12 month-end dates for 2023 incl. 2023-06-30/2023-12-29, 52 weekly dates for
  2023, `next_trading_day` normalization) — all match before encoding as tests.

## Open questions
- None blocking. `order_type`/enum surface may need extending once `backtest`/`paper`
  milestones define real order types (LIMIT variants, stop orders, etc.) — left
  minimal per "out of scope" boundary.
