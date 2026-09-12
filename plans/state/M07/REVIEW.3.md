REVIEW: APPROVE

Iteration 3 verification, in response to the quant-gate's REJECT (plans/state/M07/VERDICT.md,
cycle 1) and HANDOFF.3.md's fixes. I did not take the handoff's word for any of the
three blockers — each was re-derived independently below, on cases I built myself
rather than the developer's own fixtures.

## Fresh verification

`uv run pytest tests/ -q`: exit 0, 735 dots, ~80s wall time (two runs, 80.1s/81.1s) —
under the 90s budget but with less headroom than earlier cycles (52-56s → 53s → ~80s
as the fixture set has grown to four rendered verdicts). Not a blocker, but the next
milestone that touches this suite should watch it. `uv run ruff check .` / `format
--check .`: both clean. `git diff --stat` on `src/` identical before and after my
checks: only `cli.py`, `validation/capacity.py` (+9 lines, one constant),
`validation/reality_check.py` (+38/-changed, docstring + one constant already accepted
in iteration 2) — no other production file touched. `plans/QUANT-NOTES.md` was updated
(gate-cycle history, not code).

## The three blockers, independently reproduced

**1. Walk-forward comparison table transpose — FIXED, verified on a fresh case.**
I built my own `walk_forward_blend` (2 sleeves, 48 quarterly periods, 3-point grid,
4y/1y train/test — different numbers from the developer's own fixture), serialised it,
built a report card, and rendered both formats. `_transpose_comparison_by_grid_point`
(context.py:556-573) correctly re-keys `{metric: {grid_point: value}}` to
`{grid_point: {metric: value}}`. Every one of the 4 rows in both the HTML and markdown
comparison tables carried a real number matching the raw JSON exactly (CAGR/vol/Sharpe/
max-DD for "Walk-Forward" and all 3 fixed-weight grid points) — zero `n/a` cells. Cross-
checked cell-by-cell against a hand-transposed copy of the JSON; all matched.

**2. Chosen-weight sequence and sensitivity surface as real tables — FIXED, verified
structurally in both formats.** On the same fresh walk-forward case: the HTML chosen-
weight table renders 9 real `<tr>` elements (1 header + 8 step dates), each with the
correct per-child weight; the markdown twin renders the same 8 steps as 8 distinct table
lines (`| 2012-06-30 | 0.60 | 0.40 |`, one row per line, not collapsed). I checked the
precomputed-line fix in context.py:598-623 and confirm it's a real fix for a real bug:
the *header* row's per-column `{% for %}...{% endfor %}` on one line WOULD lose its
trailing newline under `trim_blocks` (the endfor tag is what eats it), collapsing header
and separator onto one line — precomputing `chosen_weight_header`/`_separator` in Python
sidesteps that correctly. The sensitivity surface table uses a different, safe pattern
(`{% for r in surface_rows %}` opening the line, `{% endfor %}` on its own following
line, so the loop body's own newline is preserved per iteration) and needed no such
workaround — confirmed empirically on the `eligible` fixture: 3 real rows on 3 separate
markdown lines, base point and value all correct.

**3. Old-repo $95M-$335M capacity reference range — FIXED.** `OLD_REPO_CAPACITY_RANGE_USD`/
`_ASSUMPTION` are constants in `capacity.py` (not template literals), printed beside this
run's own AUM ceiling range with the "NOT the output of this run" framing and the 50-name
assumption stated. Confirmed present, correctly formatted (`$95,000,000-$335,000,000...
under an assumed 50-name book (1/50 position_frac)`) in the rendered `eligible` fixture.

## Non-blocking items (all 8) — spot-checked, all present

4. Unscored-names caveat now names the run's `data_semantics_version` and states which
   of the two meanings (pre-/post-M04b) applies — confirmed via
   `test_unscored_names_caveat_states_data_semantics_version` and by reading
   `_unscored_names_caveat` (context.py:320-334), which branches on a real version set
   rather than a single static sentence.
5. `_num`/`_pct` special-case `math.isinf` to `"unbounded (n/a)"` before the general
   NaN path — confirmed in the `rejected` fixture (`min track-record length unbounded
   (n/a)`, gate value `unbounded (n/a)`). Correctly scoped: the gate's own `reason`
   prose (built by the read-only `report_card.py`) still says "inf" — disclosed as
   out of scope in HANDOFF.3.md, and that's the right call given the packet's own
   "read-only interface" framing for `ReportCard`.
6. The fourth fixture (`build_eligible_with_walk_forward`) fully populates
   `backtest_config`, and its rendered output carries the correct `next_open` sentence
   ("next session's open; returns are measured open-to-open on an adjusted basis") —
   closing the coverage gap the gate flagged (behaviour was already correct; only the
   fixture/test coverage was missing).
7. Plot failures are now visible, not silent. `test_plot_failure_is_visible_not_silent`
   monkeypatches `plots.plot_equity_curves` to raise and asserts both a rendered
   "plot unavailable: ValueError: ..." string in both formats AND a logged warning — I
   ran this test in isolation (not just as part of the full suite) to confirm it
   exercises the real code path rather than asserting something tautological. It does.
8. `--config` now flows the Monte Carlo seed through end to end —
   `test_report_passes_the_validation_config_for_the_monte_carlo_seed` monkeypatches
   `render_report` and asserts the loaded config's `bootstrap.monte_carlo_seed` matches
   a YAML-supplied value (42), run in isolation and passing.
9. `_synthesize_report_card_from_basic` now selects the untrusted-fraction flag by
   content (`"SEPARATE selection effects" in f`) rather than `flags[0]` — confirmed at
   render.py:110-114.
10. `VERDICT_LEGEND` (context.py:114-121, static Markup) states plainly that a verdict
    is not evidence of edge and explains hard/soft-gate capping — confirmed present in
    the walk-forward fixture's rendered markdown.
11. Deduped coverage-bound sentence, plain `·`/`-` separators in markdown (no
    `&middot;`/`&mdash;` entities), rolling tables now truncate to first/last 5 rows
    (`_ROLLING_TABLE_HEAD_TAIL`, context.py:44/475-489) — confirmed by inspection.

Everything the gate found sound in cycle 1 (autoescape design, plot semantics, carried-
note coverage in sections 3/4/6, execution-mode truthfulness) was untouched this round
and remains correct — I did not re-litigate it, per the gate's own recommendation.

## Reduced test-only bootstrap sizes (item 5 of my brief)

`tests/_report_fixtures.py:config()` uses `b=60`/`monte_carlo_n_paths=40`/`block_len=2.0`,
explicitly commented "deliberately small - these fixtures only need a report card to
exist and render, not a well-calibrated statistical test." `configs/validation.yaml`'s
shipped production defaults are `b: 200`, `monte_carlo_n_paths: 500`, `block_len: 6.0` —
confirmed materially different, so the reduced suite-time numbers are not masking a
production-config change.

No blockers found this cycle.
