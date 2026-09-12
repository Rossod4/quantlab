# M07 Reporting — HANDOFF.3 (iteration 3: REJECT response)

Responds to `plans/state/M07/VERDICT.md` (REJECT, 3 blockers + 8 non-blocking/
cosmetic, all fixed). Tree untouched between handing off and the gate's review.

## Blockers
1. **Walk-forward table transposed.** `WalkForwardResult.to_json()`'s `comparison`
   is `{metric: {grid_point: value}}` (metric-indexed DataFrame); the consumer
   assumed the opposite. Added `_transpose_comparison_by_grid_point` in
   `context.py`. Replaced the hand-written test fixture with a REAL
   `walk_forward_blend(...).to_json()` output (`tests/_report_fixtures.py`'s
   new `real_walk_forward_result`), used in both a unit test and a new 4th
   rendered fixture (`build_eligible_with_walk_forward`) so the rendering
   acceptance suite exercises it, not only a unit test.
2. **Chosen-weight sequence / sensitivity surface PNG-only.** Both now render as
   real tables in both templates (`chosen_weight_header`/`chosen_weight_
   separator`/`markdown_line` precomputed in `context.py` - a per-column
   `{% for %}` at end-of-line silently ate the next newline under
   `trim_blocks=True`, collapsing rows onto one line; fixed by precomputing
   whole lines in Python instead of nesting loops in the template).
3. **Old-repo $95M-$335M capacity range missing.** Added `OLD_REPO_CAPACITY_
   RANGE_USD`/`_ASSUMPTION` to `capacity.py` (same pattern as iteration 2's
   `reality_check.py` constants); printed beside this run's own AUM ceiling
   with "NOT the output of this run" (reworded from "this run's own output" -
   apostrophe would escape under HTML autoescape).

## Non-blocking / cosmetic (all fixed)
4. Unscored-names caveat now states the run's `data_semantics_version` and
   which meaning applies (pre-/post-M04b).
5. `_num`/`_pct` render infinity as `"unbounded (n/a)"`; Sortino's NaN gets its
   own "no downside observations" reason. (report_card.py's own prose reason
   text still says "inf" - out of scope, a read-only interface.)
6. New 4th fixture also fully populates `backtest_config` (`execution=
   next_open` etc.), closing the criterion-3 coverage gap for section 6.
7. Plot failures logged (`logging.getLogger("quantlab.reporting.render")`) and
   rendered as a visible "plot unavailable: `<reason>`" instead of silently
   omitted.
8. `quantlab report` gained `--config` (default `configs/validation.yaml`),
   passed through to `render_report` so the Monte Carlo fan uses the
   configured seed.
9. `_synthesize_report_card_from_basic` finds the untrusted-fraction flag by
   its "SEPARATE selection effects" content, not `flags[0]`.
10. Added `VERDICT_LEGEND` (what each verdict/gate kind means; "a verdict is
    not evidence of edge") under the header in both templates.
11. Deduped the coverage-bound sentence (was in trust panel + Robustness→Flags);
    replaced `&middot;`/`&mdash;` with plain `·`/`-` in the markdown twin;
    rolling tables now show first/last 5 of N rows; `_markdown_environment`'s
    docstring states the twin is safe only as plain text.

## Verification
- `uv run pytest tests/ -q`: exit 0, 735 dots, ~80s (reduced fixture bootstrap
  B/paths 300/200→60/40 to hold the 90s budget with a 4th fixture added).
- `uv run ruff check .` / `format --check .`: both clean.
- Regenerated all four `plans/state/M07/fixtures/*/out/`; spot-checked the
  walk-forward comparison and chosen-weight tables render real numbers, one
  row per line, in both formats.
