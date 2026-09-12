# M07 Reporting — HANDOFF.2 (iteration 2: REVISE response)

Responds to `plans/state/M07/REVIEW.md` (REVISE, 3 blockers). All three addressed
in the tree; nothing else was touched while under review this time.

## 1. Autoescape (BLOCKER) — fixed
`render.py` now has two Jinja environments: `_html_environment()` (autoescape=True)
and `_markdown_environment()` (autoescape=False, no HTML-injection surface).
`cli.py`'s `_report_card_markdown` uses `_markdown_environment`. In `context.py`,
the five carried-note constants plus `EXECUTION_MODE_NOTES`' two values are now
`markupsafe.Markup(...)` at declaration (never at a usage site touching dynamic
data) — a comment at the top of that block says why and warns against adding a
non-static entry. Gate `reason` strings stay plain `str` (they can carry a ticker
list via the capacity gate); a new informational `note` field (finding 2) is
Markup-wrapped separately rather than concatenated onto `reason`, so a Markup
value never re-escapes a plain string next to it. Also reworded two internal
f-strings (`_measured_size_note`'s "not measured" branch, `_execution_section`'s
`_NOT_RECORDED`) to drop apostrophes that would otherwise escape under the new
default, rather than wrapping dynamic text in Markup.
Test: `test_html_escapes_a_malicious_ticker_in_a_gate_reason_and_stays_well_formed`
(`<b>&x` in a gate reason renders `&lt;b&gt;&amp;x` in HTML, raw in markdown, page
still closes with `</html>`); all prior verbatim-caveat tests still pass.

## 2. M06 informational lines (BLOCKER) — fixed
Added `MIN_PSR_INFORMATIONAL_NOTE`/`MONTE_CARLO_NULL_INFORMATIONAL_NOTE` (both
Markup) in `context.py`, attached via `_format_gate`'s new `note` field keyed by
gate name (`probabilistic_sharpe_ratio`, `monte_carlo_drawdown`) — both templates'
gate table now render `{{ g.reason }}{% if g.note %} {{ g.note }}{% endif %}`.
Test: `test_section_4_min_psr_and_monte_carlo_informational_notes_verbatim` on all
three fixtures, plus a context-level test pinning the note on the right two gates
only.

## 3. N deduplicated vs. raw vs. dirty (BLOCKER, regression) — fixed
`_gates_section` now also reads `report_card["provenance"]["n_trials_raw"]`/
`dirty_trial_count` (already carried in the JSON, just never surfaced). Both
templates: `N trials (distinct): **N** (raw key count: R, D dirty)`.
Test: `test_section_4_n_trials_raw_and_dirty_count_shown_beside_deduplicated_n`.

## Verification
- `uv run pytest tests/ -q`: **exit 0**, 680 dots, ~53s wall time.
- `uv run ruff check .` / `uv run ruff format --check .`: both clean.
- Regenerated all three `plans/state/M07/fixtures/*/out/` — confirmed by grep:
  `report.md` and `.html` both carry the raw-count line, both informational
  sentences, and the apostrophe in "statistic's null" survives unescaped in HTML
  (Markup working as intended).

## Process note
Acknowledged: the tree should stay untouched between a handoff and its review.
No production or test file was changed this round except in direct response to
the three findings above (plus the one adjacent apostrophe cleanup in finding 1's
own blast radius — same root cause, not a scope drift).
