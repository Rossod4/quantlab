REVIEW: APPROVE

Scope: iteration 2 delta on `m03b-share-terms`, addressing
`plans/state/M03b/REVIEW.md`'s one blocking finding and one non-blocking
note, per `plans/state/M03b/HANDOFF.2.md`.

## Verification performed

1. **Full suite / lint, independent run.** `uv run pytest tests/ -q`: exit
   0, 226 dots (224 + 2 new), no red — matches HANDOFF.2.md. `uv run ruff
   check`: all checks passed. `uv run ruff format --check`: 52 files
   already formatted.

2. **Repeated my own mutation B.** Changed `pit.py`'s
   `_split_factor_since_filed` call site in `fundamentals()` from
   `self._asof` back to `effective_asof` and ran
   `tests/test_share_terms.py` + `tests/canaries/test_lookahead.py`: the
   new test `test_split_at_asof_is_applied_even_with_a_filing_lag` now
   fails as expected (`shares_outstanding` came back `100.0` instead of
   the expected `400.0`), i.e. the exact regression that iteration 1
   passed through green is now caught. Reverted; full suite re-confirmed
   green (226 dots).

3. **Repeated my straddling-filings fixture with the new two-key scheme.**
   `shares_outstanding` filed 2020-01-01, `ttm_eps` filed 2020-02-01,
   splits 2:1 on 2020-01-15 and 3:1 on 2020-03-01, `asof` 2020-04-01:
   `shares_outstanding_split_factor` now reads `6.0` and
   `ttm_eps_split_factor` reads `3.0` independently — both correct, and
   there is no longer a single shared scalar that could misreport one
   field's factor as the other's. Finding 2 from REVIEW.md is fully
   closed, not merely documented around.

4. **`git diff --stat` on `src/`** is unchanged from what I was handed,
   both before and after my two reverts (`pit.py` +117/-3, others
   unchanged from iteration 1).

## Item-by-item

- Finding 1 (blocker, split window vs. `effective_asof`): CLOSED. Test
  added, mutation-checked by both the developer and independently by me.
- Finding 2 (non-blocking, shared scalar): CLOSED via the split into
  `shares_outstanding_split_factor` / `ttm_eps_split_factor`, each gated
  on its own field's declaration (`tests/test_pit.py`'s updated
  declared-fields test and the new
  `test_provenance_key_present_only_for_the_declared_share_term_field`
  both pin this).
- No other production code changed since iteration 1 (`pit.py`'s
  call-site line reverted to its original form; only the provenance-key
  construction and docstring changed). `edgar_fundamentals.py`,
  `strategies/value.py`, `strategies/blend.py` are byte-identical to
  iteration 1's diff.
- Test-only changes are consistent with the new two-key contract
  throughout (`test_pit.py`, canary (h), `test_share_terms.py`); nothing
  papers over a gap.

No further findings. Approved.
