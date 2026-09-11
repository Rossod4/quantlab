REVIEW: REVISE

Scope: `plans/M03b-share-terms.md` against the uncommitted working tree on
`m03b-share-terms` (`src/quantlab/data/pit.py`,
`src/quantlab/data/providers/edgar_fundamentals.py`,
`src/quantlab/strategies/{value,blend}.py`, plus tests). Verified
independently: `uv run pytest tests/ -q` (exit 0, 224 dots, matches
HANDOFF.md), `uv run ruff check` (all checks passed), `uv run ruff format
--check` (52 files already formatted). `git diff --stat` on `src/` is
unchanged from what I was handed after my two mutation checks (both
reverted).

## Findings

1. **(blocker) Mutation B is not caught by any test — the packet's own
   acceptance criterion is unverified.** `plans/M03b-share-terms.md` states
   "The split window uses asof, NOT the lagged effective_asof." I changed
   `pit.py`'s call site (`fundamentals()`, the `_split_factor_since_filed`
   call) from `self._asof` to `effective_asof` and re-ran the full suite:
   all 224 tests still pass, green. I then built a fixture with
   `filing_lag_sessions=1` and a split ex-dated exactly at `asof` (strictly
   after `effective_asof`, which lag-1 pushes back one session) and
   confirmed the mutated code silently drops that split
   (`shares_outstanding` stayed `100.0`/factor `1.0` instead of the correct
   `400.0`/factor `4.0`). No test in `tests/test_share_terms.py`,
   `tests/test_value_strategy.py`, or the canary file exercises
   `filing_lag_sessions > 0` together with a split, so this real
   distinction — the one the packet calls out by name — has zero test
   coverage. Fix: add a test with `filing_lag_sessions >= 1` and a split
   ex-dated in `(effective_asof, asof]`, asserting the split IS applied
   (i.e. the window's upper bound really is `asof`, not the lagged date).

2. (informational, no fix required) Item 7's judgment call, verified by
   fixture: shares_outstanding filed 2020-01-01, ttm_eps filed 2020-02-01,
   splits 2:1 on 2020-01-15 and 3:1 on 2020-03-01, `asof` 2020-04-01. Both
   fields are restated correctly and independently
   (`shares_outstanding` = 100×6 = 600.0; `ttm_eps` = 8/3 = 2.6667, since
   only the second split postdates ttm_eps's own filed date) — no
   mis-restatement of the actual field values in this straddling case.
   The single scalar `share_terms_split_factor` does report a misleading
   number in this case (6.0, i.e. shares_outstanding's factor, when
   ttm_eps was actually restated by 3.0), but `pit.py`'s docstring
   explicitly documents exactly this limitation ("both fields are always
   restated with their OWN correct factor regardless of what this one
   summary key reports"). The documentation is accurate; the scalar is a
   deliberately-flagged simplification, not a silent bug.

## Item-by-item verification (1-7 from the review request)

1. **Frozen EDGAR numerics.** `_most_recent_instant_with_filed` mirrors
   `_most_recent_instant`/`_most_recent_instant_with_end`'s subset/sort
   (`facts["start"].isna() & (facts["filed"] <= as_of_date)`,
   `sort_values(["end","filed"]).iloc[-1]`) exactly, adding only the
   returned `filed` field; `_ttm_duration_with_latest_filed` mirrors
   `_ttm_duration`'s quarter/annual windows and restated-quarter dedup
   exactly. Neither frozen helper is modified. `uv run pytest
   tests/parity -q` (M02 fundamentals parity + M03 signal parity): 6
   passed, unchanged.
2. **Gate fixture hand-recompute.** 4:1 split 30 sessions after filing:
   confirmed P/E 25.0, P/B 1.66667 to 1e-9
   (`tests/test_share_terms.py::test_gate_fixture_pe_and_pb_correct_after_a_4_for_1_split`,
   also independently hand-verified: raw price 50, ttm_eps 8/4=2 → PE 25;
   shares 100×4=400, market cap 20000/equity 12000 → PB 1.6667). Split
   before filing → factor 1.0 (confirmed). Two post-filing splits (2:1 then
   3:1) compose to 6.0 (confirmed).
3. **Mutation A (lower bound removed).** Widened the window to have no
   `filed` lower bound (`splits.index <= asof` only). Full share-terms
   suite: `test_split_before_the_filing_has_zero_effect` fails
   (`shares_outstanding` comes back 400.0 instead of 100.0). Reverted;
   suite green again.
4. **Mutation B (effective_asof instead of asof).** See finding 1 above —
   REVISE. No test catches it.
5. **TTM EPS filed-date rule.** Verified by fixture with four quarters
   filed on four different dates: `ttm_eps_filed` returns the latest of the
   four (2020-01-25), matching the packet's "latest filed among components
   actually summed" rule.
6. **Blend id.** Code hashes `sorted((child.strategy_id, weight) ...)` plus
   non-`children` own params — no raw child config dict is hashed anywhere
   in `BlendStrategy.strategy_id`. `tests/test_blend.py`'s three new tests
   (order swap, omitted default, child-param change) all pass, confirming
   order-insensitivity, default-insensitivity, and weight/param-sensitivity
   end to end through `load_strategy`.
7. **Scalar judgment call.** See finding 2 — no mis-restatement of the
   actual per-share values in a straddling-filings fixture; the developer's
   documentation of the summary scalar's limitation is accurate.

## Conventions / scope
No hardcoded paths, typed signatures, pydantic config untouched,
`from __future__ import annotations` present. Docstrings are extensive but
in line with this repo's existing style (e.g. `pit.py`'s prior docstrings).
Nothing here reaches beyond the packet's scope.
