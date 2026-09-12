REVIEW: APPROVE

Iteration 2 verification (fresh, against the tree as handed off — confirmed
untouched by my own checks, `git diff --stat` identical before and after):
`uv run pytest tests/ -q` exit 0, 680 dots, ~53s wall time. `uv run ruff check .` —
all checks passed. `uv run ruff format --check .` — 107 files already formatted.
`uv run quantlab report --help` — works.

## Verification of the three REVIEW.md blockers

1. **Autoescape.** `render.py` now has `_html_environment()` (autoescape=True) and
   `_markdown_environment()` (autoescape=False); `cli.py`'s `_report_card_markdown`
   uses the markdown one. In `context.py`, exactly the five carried-note constants
   (`COVERAGE_BOUND_DEFINITION`, `SEPARATE_SELECTION_EFFECTS_NOTE`,
   `ROLLING_PORTED_CONVENTION_NOTE`, `WALK_FORWARD_NO_EMBARGO_NOTE`,
   `WALK_FORWARD_TRAINING_SHARPES_UNAVAILABLE_NOTE`) plus `EXECUTION_MODE_NOTES`'
   two values and the two new informational notes (below) are `markupsafe.Markup(...)`
   — every one wraps a fixed hand-written literal, none touches `result.provenance`,
   `report_card`, or any f-string with dynamic content. Gate `reason` stays a plain
   `str` (`_format_gate`, context.py:167-184), so it's escaped like any other
   external-adjacent value. Confirmed empirically: the `Backtest config` cell in the
   rendered `eligible` fixture now shows `{&#39;end&#39;: &#39;2019-12-31&#39;, ...}`
   — real dynamic provenance data is genuinely being escaped in the shipped HTML, not
   just in a synthetic test. `test_html_escapes_a_malicious_ticker_in_a_gate_reason_and_stays_well_formed`
   (test_render.py:141) injects `<b>&x` into a gate reason: renders as
   `&lt;b&gt;&amp;x` in HTML, page still closes `</html>`, and the same payload stays
   raw in the markdown twin — a direct, correct reproduction of the finding-1 exploit.
2. **M06 informational lines.** `MIN_PSR_INFORMATIONAL_NOTE` /
   `MONTE_CARLO_NULL_INFORMATIONAL_NOTE` (both Markup, both static) are attached via
   `_GATE_INFORMATIONAL_NOTES` keyed by gate name and rendered as a `note` field
   alongside (not concatenated into) `reason` in both templates
   (`report.html.j2:132`, `report.md.j2:70`). Confirmed present, verbatim, and on the
   correct gates (`probabilistic_sharpe_ratio`, `monte_carlo_drawdown`) in all three
   rendered fixtures' HTML and markdown.
3. **N deduplicated vs. raw vs. dirty.** `_gates_section` now reads
   `report_card["provenance"]["n_trials_raw"]`/`dirty_trial_count`
   (context.py:365-366); both templates print
   `N trials (distinct): **N** (raw key count: R, D dirty)`. Confirmed present in all
   three fixtures' HTML and markdown (e.g. eligible: `**5** (raw key count: 5, 5
   dirty)`).

## Other checks requested

- Apostrophe rewordings (`_measured_size_note`'s "not measured" branch,
  `_execution_section`'s `_NOT_RECORDED`) did not touch any of the acceptance-
  criterion-3 verbatim carried strings — those five stayed byte-identical (now
  Markup) and their own tests still assert the original wording. The two reworded
  strings are internal fallback/gate-detail text, not carried-note constants; their
  own tests (`test_report_context.py:425`, `test_render.py:105`) were updated to the
  new wording and the full suite passes.
- `git diff --stat` on `src/` is unchanged from before my checks
  (`cli.py`, `validation/reality_check.py` only) — nothing else was touched this
  round, matching HANDOFF.2.md's process note.

## One non-blocking nit (not required by any acceptance criterion)

`context.py`'s `_provenance_section` still has one un-Markup'd literal with an
apostrophe: `"n/a (not recorded in this run's provenance)"` (the `cache_dir`
fallback). Under the new default it will render as `run&#39;s` in the HTML
provenance appendix while staying `run's` in the markdown — cosmetically
inconsistent between the two, but no test asserts this string verbatim across both
formats and it isn't one of the packet's carried/acceptance-criterion strings, so
it doesn't block. Worth a one-line cleanup (reword or wrap) whenever this file is
next touched.
