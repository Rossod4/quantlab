# M01 Handoff — Data layer I: interfaces, cache, quality, prices + constituents

## Files changed
Created:
- `src/quantlab/data/{__init__,interfaces,cache,quality}.py`
- `src/quantlab/data/providers/{__init__,yfinance_prices,sp500_constituents,norgate_prices}.py`
- `tests/{test_interfaces,test_cache,test_quality,test_prices_provider,test_constituents}.py`
- `tests/fixtures/constituents_slice.csv`, `tests/fixtures/prices_slice.parquet`

No changes to `core/`; `DataQualityError`/`ConfigError` already existed and were reused as-is.

## Design decisions
- **Panel format**: long-format `DataFrame` indexed by tz-naive midnight date, columns
  `[ticker, open, high, low, close, adj_close, volume]` (documented in `PriceProvider`
  docstring). Chosen over wide-single-field because the packet requires both raw and
  adjusted close in one return value.
- **`build_provider(kind, name, config)`**: lazy-imports provider modules per branch to
  avoid circularity (providers import the ABCs). Only `"prices"` and `"constituents"`
  kinds are wired; `"fundamentals"`/`"corporate_actions"` raise `ConfigError` since their
  providers are signature-only until M02 — acceptance criteria didn't require otherwise.
- **Constituents URL**: `src/config.py` (the old repo's URL constant) wasn't in this
  packet's Context list, so I couldn't read it. I confirmed the live filename via the
  GitHub contents API and used `.../S%26P%20500%20Historical%20Components%20%26%20Changes%20(Updated).csv`
  as `DEFAULT_CONSTITUENTS_URL`, verified reachable by the (default-excluded) network test.
- **`membership()` before-earliest behavior**: kept as `ValueError` (not a new domain
  error), matching the old repo's documented behavior exactly per the packet's "match it,
  document which" instruction.
- **Fixture CSV**: `constituents_slice.csv` is a *reconstructed* small-scale table (5
  tickers, 4 change rows, 2015–2023) in the real fja05680 quoted-CSV format, not a literal
  500-ticker slice of the real file — committing full 500-wide rows would bloat the repo
  for no parity benefit; behavior (as-of semantics, normalization) is what's under test.
- **`get_prices` drops the old `failed_tickers` return value** — the `PriceProvider` ABC
  signature is fixed to return one `DataFrame`; failed tickers are simply absent from the
  result (no separate reporting channel in M01).

## Mechanical/API updates from the port
- pandas 3.x: `DataFrame.stack()` still requires an explicit `.dropna()` to drop
  unflagged cells (same fix the old repo already carried under pandas 2.x — verified
  empirically, no further change needed).
- **yfinance 1.5.1 vs. the old repo's 0.2.x**: `yf.download(..., group_by="ticker")` now
  *always* returns MultiIndex `(ticker, field)` columns, even for a single-ticker batch
  (the old repo special-cased `len(batch) == 1` to skip the `raw[ticker]` subselect). Fixed
  by checking `isinstance(raw.columns, pd.MultiIndex)` instead of batch size. Caught by the
  network-tier test (`test_real_yfinance_download_of_aapl`), which failed silently (empty
  panel, no error) before the fix — worth flagging to the reviewer as the one place ported
  logic diverges from the old repo's structure, not just its numerical values.

## Test command + output
- `uv run pytest tests/ -v` → **75 passed, 3 deselected** (network tests)
- `uv run pytest tests/ -m network` → **3 passed** (real yfinance + real constituents CSV,
  confirmed working in this sandbox; excluded by default per repo convention)
- `uv run ruff check` → clean
- `uv run ruff format --check` → clean

## Open questions
- `DEFAULT_CONSTITUENTS_URL` is a best-effort live lookup, not sourced from the old repo's
  config — worth a reviewer sanity check against whatever `src/config.py` actually had, if
  accessible later.
- `QualityGate` reason strings are free-form (`"ohlc_sanity:low_gt_high,..."`,
  `"outlier_return:+62.0%"`) rather than an enum — fine for M01's flag-report use case: revisit
  if M02/M03 need to filter/aggregate by reason programmatically.
