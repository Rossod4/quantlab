# M02 handoff (iteration 1)

## Files changed
New: `src/quantlab/data/pit.py`, `data/requirements.py`, `data/survivorship.py`,
`data/corporate_actions.py`, `data/providers/edgar_fundamentals.py`; `tests/test_pit.py`,
`tests/test_edgar_fundamentals.py`, `tests/test_survivorship.py`,
`tests/test_corporate_actions.py`, `tests/canaries/{__init__,test_lookahead}.py`,
`tests/fixtures/edgar/nath_companyfacts.json`. Edited: `core/errors.py` (+`UndeclaredDataError`).
No M01 provider files touched.

## Central design decision: adj_close / as-of pricing
`prices()` (decision path) returns raw OHLCV only, **never** `adj_close`, no adjustment at
all. `prices_for_returns()` (accounting path, not for signals) adds yfinance's `adj_close`.
Reasoning: the packet's preferred design — raw close × a split/div adjustment replayed only
from actions with ex-date <= asof — needs genuine, independently-ex-dated corporate-action
events. M01's price cache has none (only OHLC + Yahoo's globally-recomputed `adj_close`,
which bakes in *all* future splits/divs, not just those known by asof). I built
`corporate_actions.py` to fetch/cache real yfinance dividend/split events specifically to
enable that replay, but did NOT wire it into `prices()` this iteration: it would be new,
unparitized numerical logic in the platform's most safety-critical spot, with no old-repo
precedent to freeze against and no dedicated parity tests yet. Falling back to the packet's
explicitly-sanctioned escape hatch (raw vs `prices_for_returns()`) trades "adjusted but
unproven" for "unadjusted but provably zero look-ahead risk" — the safer call for a first
pass. Known limitation, documented in code: raw `close` has split discontinuities a momentum
signal must not naively compare across. Follow-up: wire `corporate_actions.py`'s real events
into a parity-tested as-of replay once that's built.

## Other design decisions
- `LookaheadError` is raised by an internal defense-in-depth assertion
  (`_assert_no_future_dates`), called immediately after every hard-slice in `prices()`/
  `actions()`. The public contract (per canaries a/b) is silent exclusion — a single
  contaminated vendor row shouldn't abort a whole backtest; the assertion exists so a future
  regression that weakens the slice fails loudly. Directly unit-tested in `test_pit.py`.
- `UndeclaredDataError`: `fundamentals()`/`universe()` raise if their `DataRequirements`
  field is empty/False; `prices()`/`prices_for_returns()` raise if `lookback_days` exceeds
  `price_lookback_days`. `actions()` is ungated (packet doesn't list it in DataRequirements).
- `DataRequirements` lives in new `data/requirements.py` (dependency-free dataclass) per
  packet's explicit option, for clean M03 re-export.
- `survivorship.coverage_gap()` is a pure function over `PriceAvailability` (has_data,
  last_bar_date, masked_end) rather than reading disk directly — offline-testable, and
  `masked_end` surfaces cache-metadata-masked truncations as coverage loss (QUANT-NOTES M01
  note). `overall_bound` = max per-year %, a conservative ceiling, not an average.
- `edgar_fundamentals.py`: numerical logic ported verbatim; only mechanical change is
  extracting `_flatten_company_facts` out of `get_company_facts` (same ops) so the parity
  test can flatten a real JSON fixture without a live cache file. Pandas 3.x: `zip(..., strict=True)` added (was implicit in old py/pandas).
- Parity fixture: real SEC companyfacts for Nathan's Famous (NATH, CIK 69733), trimmed to
  `TAGS_OF_INTEREST` + `end>=2018` for size (159KB). Expected values computed by running the
  OLD module against this exact fixture offline; hard-coded with provenance comment.

## Tests
`uv run pytest tests/ -q` → 135 passed, 3 deselected (network). `uv run ruff check` /
`ruff format --check` → clean.

## Open questions
- Should `corporate_actions.py`'s real dividend/split events drive `prices()` adjustment in
  M03/M04, once parity-tested? Recommend a dedicated follow-up milestone note.
- `actions()` has no DataRequirements gate — confirm that's intended before M03's Strategy ABC locks in the declaration surface.
