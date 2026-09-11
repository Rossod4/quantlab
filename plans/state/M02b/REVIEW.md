REVIEW: APPROVE

# M02b review — as-of adjustment replay + actions-cache staleness

## Verification performed (independent, not copied from HANDOFF.md)
- `uv run pytest tests/ -q` → 156 passed, 3 deselected in ~2.6s.
- `uv run ruff check` → All checks passed.
- `uv run ruff format --check` → 37 files already formatted.
- Mutation test A: weakened `pit.py::_gated_actions_by_ticker`'s hard slice
  (`sliced = raw.loc[raw.index <= self._asof]` → `sliced = raw`). Result:
  `tests/canaries/test_lookahead.py::test_canary_future_dated_action_has_zero_effect_on_prices`
  fails, raising `LookaheadError` from `_assert_no_future_dates`. Reverted;
  `git diff --stat src/quantlab/data/pit.py` empty afterward.
- Mutation test B: weakened `adjustment.py::adjustment_factors`'s internal
  re-gate (`gated = actions.loc[actions.index <= asof_ts]` → `gated =
  actions`). Result: canary (f) still PASSES (pit.py's own hard slice
  already excludes the future action before `adjustment.py` ever sees it —
  genuine defense-in-depth), but
  `test_nvda_10_for_1_split_leaves_price_unadjusted_when_asof_before_ex_date`
  and the AAPL analog (both call `apply_asof_adjustment` directly,
  bypassing pit.py) fail as expected. Reverted; `git diff --stat
  src/quantlab/data/adjustment.py` empty afterward. Both layers are
  independently pinned by some test, just not the same one — see finding 2.
- Hand recomputation: AAPL 500.0/4 = 125.0; cash dividend factor
  1 - 2.0/100.0 = 0.98 → 100.0*0.98 = 98.0; same-day split(3.0)+dividend
  (close_prev_ex=40, D=4) combined factor (1/3)*(1-4/40) = 0.3 — all match
  the fixtures in `tests/test_adjustment.py` exactly.
- Staleness-bypass check: both `PITDataContext` call sites
  (`pit.py:164` and `pit.py:269`) call `get_actions(ticker, _EPOCH,
  self._asof)` — `end` is always `self._asof`, which is set once at
  construction and has no public setter. There is no path through
  `PITDataContext`'s public API (`prices()`, `actions()`) for a caller to
  pass an `end` different from `asof`, so the staleness check cannot be
  bypassed via `pit.py`.
- `cache.py` refactor: `write_price_cache_meta`/`has_sufficient_price_cache`
  now delegate to the new generic `read_json_meta`/`write_json_meta`; a
  line-by-line diff shows this is a pure extraction (identical
  exists-check-then-`json.loads`/`mkdir`-then-`write_text` behavior).
  `tests/test_cache.py` (untouched, 8 tests) still passes unchanged,
  confirming price-cache behavior is unaffected.

## Findings

1. (Minor) `tests/test_adjustment.py`'s `TOL = 1e-9` is looser than the
   packet's acceptance criterion 2 ("parity fixtures ... pass to 1e-12").
   Not a real numeric issue — actual float64 error on these values (e.g.
   `1 - 2/100`) is around 1e-16, far under 1e-12 — but the assertion
   tolerance as written doesn't literally match the stated bar. Tighten
   `TOL` to `1e-12` for full compliance (should still pass).
2. (Minor, informational) The HANDOFF's "mutation check (canary f)" section
   only documents mutating `pit.py`'s hard slice. My mutation test B above
   shows `adjustment.py`'s own internal re-gate is a second, independent
   layer that canary (f) alone does NOT exercise (pit.py's slice already
   shields it) — it's pinned only by the direct `apply_asof_adjustment`
   parity tests. Worth a one-line note in `adjustment.py` or the handoff so
   a future reader doesn't assume canary (f) alone covers both gates.
3. (Minor) `CorporateActionsProvider` (`src/quantlab/data/interfaces.py:82-88`)
   documents nothing about the staleness contract; enforcement lives
   entirely inside the concrete `YFinanceCorporateActionsProvider`. Per the
   team lead's specific question: a second provider (the `NorgatePriceProvider`
   stub is price-only today, but a future `NorgateCorporateActionsProvider`
   or any other new implementer) could satisfy the ABC's stated contract
   with zero staleness protection, silently reintroducing the
   raw-discontinuity bug for that provider — nothing at the interface level
   or in `pit.py` would catch it. Not a defect today: only one concrete
   provider exists, it enforces staleness correctly, and (per the bypass
   check above) `pit.py` always passes `end=asof` so there's no live gap
   yet. But the guarantee is documented in one class's docstring, not on
   the contract new implementers actually read. Recommend a short note on
   the ABC itself pointing at `corporate_actions.py`'s staleness section,
   even if enforcement stays non-abstract (the developer's reason for
   keeping it out of the ABC — not forcing every test fake to implement
   staleness — is sound and shouldn't change).
4. (Minor) No committed test exercises `StaleActionsCacheError` propagating
   end-to-end through `PITDataContext.prices()`/`actions()`; all staleness
   tests target the provider directly. I confirmed by inspection that
   `pit.py` has no `try`/`except` around either `get_actions` call site, so
   it does propagate uncaught — but this central invariant (a stale actions
   cache must block, not silently degrade, a decision) isn't pinned by any
   test. A small integration test in `test_adjustment.py` or `test_pit.py`
   wiring a stale-raising fake `CorporateActionsProvider` into
   `PITDataContext` and asserting `prices()`/`actions()` raises would close
   this.

None of the above are blockers (minors only, per the reviewer charter).
Acceptance criteria 1-5 from `plans/M02b-adjustment-replay.md` are all met;
`plans/state/M02/VERDICT.md` carried item 1's staleness-handling requirement
is satisfied with a documented, defensible enforcement-point decision.
