REVIEW: REVISE

Reviewer verification (fresh run against current tree, which moved twice during this
review — see note at bottom): `uv run pytest tests/ -q` exit 0, 670 dots, ~52-56s wall
time (< 90s budget). `uv run ruff check .` — all checks passed. `uv run ruff format
--check .` — 107 files already formatted. `uv run quantlab report --help` — works and
documents `--result`/`--out`/`--card`/`--format` correctly.

## Findings

1. **[BLOCKER]** `src/quantlab/reporting/render.py:48-61` (`_environment`) disables
   Jinja autoescape for `report.html.j2` on the stated rationale that "every value in
   the context comes from this platform's own results/config (never from an untrusted
   external source)." That premise is false. `src/quantlab/validation/report_card.py:891-925`
   interpolates `missing_tickers` — ticker symbols sourced from the price cache /
   vendor data, resolved from held positions, not a platform-internal literal — directly
   into the `capacity` gate's `reason` string (e.g. `"...excluded: ['AAPL', 'XYZ']"`).
   That `reason` reaches `report.html.j2` unescaped via `_gates_section`/`_format_gate`
   in `context.py` and is rendered as `<td>{{ g.reason }}</td>` (`report.html.j2:130`).
   `provenance.strategy_params`/`provenance.backtest_config` (YAML-configured, external
   to the reporting package's own code) are rendered the same way at
   `report.html.j2:224-225`. With autoescape off, a ticker or YAML string containing
   `<` or `&` breaks the HTML structure rather than displaying literally — this is
   exactly the failure mode the packet's self-containment/safety bar (and the
   orchestrator's explicit item-6 question) is asking about. No test exercises this.
   Fix: re-enable autoescape on `report.html.j2`'s environment (a second, autoescape=False
   environment can stay for `report.md.j2`, which has no HTML-injection surface), and
   wrap the literal carried-note constants that need byte-for-byte verbatim matching
   (`COVERAGE_BOUND_DEFINITION`, `SEPARATE_SELECTION_EFFECTS_NOTE`,
   `ROLLING_PORTED_CONVENTION_NOTE`, `WALK_FORWARD_NO_EMBARGO_NOTE`,
   `WALK_FORWARD_TRAINING_SHARPES_UNAVAILABLE_NOTE`, `EXECUTION_MODE_NOTES`) in
   `markupsafe.Markup(...)` at the point they're added to the context, so they render
   unescaped while everything else (gate reasons, ticker lists, caveats built from
   `rc_excluded`/`missing_tickers`, strategy params, file paths) is escaped by default.

2. **[BLOCKER]** Carried M06 verdict item 3 (binding, `plans/M07-reporting.md`'s
   "Carried from the M06 verdict" section, tracked in `plans/QUANT-NOTES.md:978-981`
   as "→ M07 (informational, unchanged from cycle 1)") is not implemented anywhere.
   Neither "min_psr 0.95 binds only below an annualised Sharpe of about 0.47 on a
   12-year monthly book" nor "the Monte Carlo drawdown gate sits at the [approximate]
   centre of its own statistic's null" appears in `report_card.py`'s `psr_reason`
   (`report_card.py:744-747`) or `monte_carlo_drawdown` gate reason
   (`report_card.py:877-879`), in `context.py`, or in either template. Confirmed absent
   by grep across `src/` and in all three rendered fixtures
   (`plans/state/M07/fixtures/*/out/report.md`). Fix: add both sentences to the
   respective gate reasons (or as an adjacent note in `_gates_section`) so they render
   next to the `probabilistic_sharpe_ratio` and `monte_carlo_drawdown` badges.

3. **[BLOCKER, regression]** Carried M06 verdict item 7 ("print N (deduplicated) and
   the raw record count side by side") is not implemented. The M06-era
   `_report_card_markdown` stopgap this milestone replaces (see `git diff
   src/quantlab/cli.py`, removed lines) printed `"N trials: {n_trials} distinct (raw
   key count: {n_trials_raw}, {dirty_trial_count} dirty)"`. `report_card.json`'s
   provenance still carries `n_trials_raw`/`dirty_trial_count`
   (`report_card.py:324,345,460,584`), but `context.py:_gates_section` never reads
   them, and neither `report.html.j2:112` nor `report.md.j2:52` prints anything beyond
   `gates.n_trials` (the deduplicated count only). Confirmed absent in all three
   rendered fixtures. This is a regression against a requirement M07 was explicitly
   built to satisfy, not a new gap. Fix: surface `report_card["provenance"]["n_trials_raw"]`
   (and ideally `dirty_trial_count`, already carried elsewhere) beside `gates.n_trials`
   in both templates.

4. **[Minor, informational only]** `src/quantlab/validation/reality_check.py` was
   modified outside the packet's original "In scope" file list (adds
   `MEASURED_SIZE_AT_SHIPPED_BLOCK_LEN`/`MEASURED_SIZE_BLOCK_LEN`/`NOMINAL_SIZE_BAR` and
   corrects stale docstring numbers). This is disclosed in the current
   `plans/state/M07/HANDOFF.md` ("Modified" list + "Addendum" item 7) and is exactly
   what the orchestrator's addendum asked for (a documented constant in the
   RC/SPA module, not a template literal) — no action needed, noted for completeness
   against item 9's "nothing outside reporting/ + cli.py + tests" framing.

## Answers to the orchestrator's numbered checklist

1. Caveat coverage — everything checked was present and verbatim EXCEPT the two
   items in finding 2 above (min_psr Sharpe-0.47 line; MC-drawdown-null line), which
   are missing entirely. Coverage bound definition, separate-selection-effects note,
   extreme-return direction statements, known_caveats verbatim, rolling first-return-
   blind convention, no_cliff_score paired only with min_net_sharpe, walk-forward
   no-embargo explanation + "ranking agreement ... not checked" line, execution
   conventions, Sharpe/Sortino conventions, DSR non-monotonicity note, capacity
   trivial-pass note, K, benchmark source, and dirty badge are all present and correct.
   N deduplicated vs. raw is NOT both present (finding 3 — only deduplicated N shown).
2. RC/SPA measured over-sizing (~0.117/~0.118 at the 0.10 bar) — present, sourced from
   `reality_check.py`'s documented `MEASURED_SIZE_AT_SHIPPED_BLOCK_LEN` constant (not a
   template string), block-length-gated so it's never misattached to a different run.
   Confirmed via `context.py:_measured_size_note` and `test_report_context.py`'s
   `test_rc_spa_measured_size_shown_at_the_shipped_block_len` /
   `test_rc_spa_measured_size_absent_note_at_a_different_block_len`.
3. Self-containment — zero external `src=`/`href=` (tested, and confirmed by inspecting
   all three rendered HTML files); base64 PNGs confirmed (`img class="plot" ...
   src="data:image/png;base64,..."`); all three HTML files well under 5 MB (280-350 KB).
   Markdown/HTML numeric-parity test (`test_markdown_numbers_all_appear_in_html`) is
   real: it regex-extracts every numeric token from the rendered markdown and asserts
   each appears somewhere in the rendered HTML string — a genuine drift check, not a
   tautology.
4. Number formatting — no `repr`'d numpy scalars, no bare `nan` (verified by
   `test_gate_values_are_never_a_repr_and_always_fixed_precision`,
   `test_no_value_is_ever_a_bare_nan_string`, and by construction: every leaf goes
   through `_num`/`_pct`/`_money`/`_int_or_na`, all of which check `math.isnan` and
   never call `repr`/`!r`). Fixed precision confirmed.
5. Plots — `matplotlib.use("Agg")` called before `pyplot` import
   (`plots.py:41-47`, and `test_matplotlib_backend_is_agg` asserts it); every plot
   function tested for non-empty PNG bytes; semantics checked against
   `..\MomentumValueStrategy\src\evaluation\plots.py` — gross dashed / net solid /
   benchmark neutral grey match the old repo's own convention (old repo didn't
   consistently color benchmark grey, but the packet asked for ONE color system, which
   this delivers); sensitivity heatmap marks the base point with a star and annotates
   NaN/edge points in both the 1-D and 2-D cases (`plots.py:200-272`).
6. Autoescape — see finding 1. This is a REVISE: a genuine externally-sourced-content
   path (ticker symbols in a gate reason; YAML strategy params/backtest config in the
   provenance appendix) renders unescaped in the HTML output.
7. Walk-forward training Sharpes — `WALK_FORWARD_TRAINING_SHARPES_UNAVAILABLE_NOTE`
   states plainly they are not retained and does not fabricate a figure; rendered in
   both templates and asserted verbatim by `test_walk_forward_section_carries_no_embargo_and_ranking_lines`
   and `test_render.py`.
8. CLI end-to-end — `quantlab report --result ... --out ...` writes both files
   (`test_report_end_to_end_writes_both_files`), and `_report_card_markdown` in
   `cli.py` now delegates to `report.md.j2` via `build_report_context` +
   `_environment()` rather than the old `{gate.value!r}` stopgap.
9. Scope / suite time — suite is ~52-56s, under the 90s budget. `src/quantlab/cli.py`
   and `src/quantlab/validation/reality_check.py` are the only production files changed
   outside `reporting/`; see finding 4 (accepted, disclosed, minimal).

## Note on review conditions

The tree was represented as frozen but changed twice during this review (an
`encoding="utf-8"` fix to `cli.py`'s three `--full` file writes, landing alongside the
`reality_check.py` addendum change, raised the passing test count from 668 to 670
dots). Findings above were verified against the latest state as of this review. None of
the three findings are affected by that change — the autoescape gap, the missing
min_psr/MC-null informational lines, and the missing raw-trial-count are present in
both the earlier and current tree states.
