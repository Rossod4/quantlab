# M02b HANDOFF — as-of adjustment replay + actions-cache staleness

`adjustment.py`/`pit.py` wiring (from an interrupted predecessor) was
already correct — untouched. Covers: (1) completed parity tests/canary,
(2) actions-cache staleness — confirmed in-scope per VERDICT.md carried
item 1 (team-lead correction; overwriting this file, no .2, no review yet).

## Files changed
- `tests/test_adjustment.py` (was broken) — 9 tests: NVDA 10:1 / AAPL 4:1
  split parity, cash-dividend factor, split+dividend composition
  (cross-date + same-day order-independence), PITDataContext regressions
  for criteria 4 (12mo momentum across NVDA split: adjusted ≈0%, raw
  exactly -90%) and 5 (prices() before an ex-date unaffected by a future
  action in the provider).
- `tests/canaries/test_lookahead.py` — canary (f): hostile provider returns
  a future split; `prices()` byte-identical with/without it. *Intentional
  change*: `_minimal_context` gained an additive
  `corporate_actions_provider` param.
- `src/quantlab/core/errors.py` — `StaleActionsCacheError(DataQualityError)`.
- `src/quantlab/data/cache.py` — extracted `read_json_meta`/`write_json_meta`
  generic sidecar helpers from `write_price_cache_meta`/
  `has_sufficient_price_cache`, so actions reuse the same mechanism instead
  of a parallel one. Price-cache behavior unchanged.
- `src/quantlab/data/corporate_actions.py` — `get_actions` writes a
  `fetched_at` DATE on every fresh download; raises `StaleActionsCacheError`
  (names ticker, asof, fetched_at) when `end` (== `asof` at every `pit.py`
  call site) is later than `fetched_at`, OR `fetched_at` is missing —
  missing metadata is now STALE, not trusted (reversed from iteration 1: a
  legacy cache needs one `refresh_actions_cache()` before use). No network
  call in this path (CLAUDE.md invariant #5). Added
  `refresh_actions_cache(ticker, cache_dir)`; its download failures
  propagate rather than silently no-op.
- `tests/test_corporate_actions.py` — *intentional changes*: the two
  pre-existing cache-hit tests now write `fetched_at` via new helper
  `_write_actions_cache_and_meta` (a bare cache now raises, not serves). 5
  new tests: (a) asof<=fetched_at passes, (b) asof>fetched_at raises, (c)
  missing fetched_at raises, (d) refresh clears staleness + propagates a
  download failure.

## Design decision: enforcement point
Inside `YFinanceCorporateActionsProvider.get_actions`, not a new
`CorporateActionsProvider` abstractmethod checked from `pit.py`. `pit.py`
always calls `get_actions(ticker, _EPOCH, self._asof)`, so `end` IS `asof`
at the only call site. An ABC-level check was rejected: it would force
every test fake in test_pit.py/test_lookahead.py/test_adjustment.py to
implement a method none of them need.

## Mutation check (canary f)
Unchanged from iteration 1: weakened `pit.py`'s outer ex-date slice, canary
(f) failed via `LookaheadError`, reverted; `git diff --stat` confirms
`pit.py` matches committed state.

## Verification
- `uv run pytest tests/ -q` → **156 passed, 3 deselected in 2.25s**
- `uv run ruff check` → **All checks passed**
- `uv run ruff format --check` → all files formatted

## Open questions
None outstanding.
