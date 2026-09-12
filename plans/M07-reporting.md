# M07 — Reporting: single-file HTML report + markdown twin, plots, `quantlab report`

Goal: Turn a `BacktestResult` + `ReportCard` into one self-contained HTML file (inline
CSS, base64 PNG plots, no external assets) and a markdown twin with identical content,
so a result can be read by a human, attached to a CV, or diffed in git. The report is
the honesty surface: every caveat, bound, and convention the gates carried forward must
be stated next to the number it qualifies, not in an appendix.

## In scope (create these)
- src/quantlab/reporting/__init__.py
- src/quantlab/reporting/plots.py — port `plot_equity_curves`, `plot_drawdown`,
  `plot_universe_size` from the old repo's src/evaluation/plots.py (matplotlib, Agg
  backend forced, no display), returning `bytes` PNG rather than showing; add
  `plot_rolling_sharpe`, `plot_subperiod_bars`, `plot_sensitivity_heatmap` (1-D or 2-D
  grid; base point marked; edge/NaN points annotated), `plot_monte_carlo_fan`
  (5/50/95 percentile paths), `plot_walk_forward_weights` (chosen weight per step).
  Follow the dataviz conventions: one colour system, benchmark always the same neutral
  colour, strategy the same accent, gross dashed / net solid as the old repo did.
- src/quantlab/reporting/context.py — `build_report_context(result, report_card,
  config) -> dict` — the ONLY place numbers are formatted. Sections, in order:
  1. **Verdict header**: verdict, strategy_id, data_semantics_version, run date, git sha
     (+ "DIRTY TREE" badge if provenance.dirty), and the one-line summary.
  2. **Headline vs benchmark** table: net/gross CAGR, vol, Sharpe, Sortino (with its
     stated convention), max DD, Calmar, hit rate, cost drag, beta / IR / TE each with
     the overlap count beside it (M05 carried) or the "no usable benchmark" line.
  3. **Trust panel** (the bias bounds): coverage bound with its exact definition
     ("worst sampled rebalance-date year, % of point-in-time members with no cached
     history or masked before that date; a ceiling on invisibility, not a return
     impact"), forced exits, extreme_returns_long/short with the direction statement,
     unscored/dropped counts — labelled as SEPARATE selection effects (M04 carried) —
     and every `known_caveats` entry from provenance verbatim.
  4. **Validation badges**: each gate as name / value / threshold / pass-fail / reason;
     PSR, DSR (with N trials and the registry's lower-bound caveat), purged-CV folds,
     RC/SPA p-values, Monte Carlo percentiles and P(worse drawdown), capacity range
     with the spread percentiles, min track-record length.
  5. **Robustness**: rolling table (labelled "ported convention: each window's first
     return is omitted from CAGR and hidden from drawdown" — M05 carried), corrected
     sub-period/regime table, sensitivity surface with no_cliff_score shown ONLY next to
     min_net_sharpe and never described as quality (M05 carried), walk-forward chosen
     weights with the no-embargo explanation and the "ranking agreement under both cost
     conventions: checked / not checked" line (M05 carried).
  6. **Execution conventions**: execution mode and which price the entry is measured at
     (M04 carried: `close` = same-session close; `next_open` = next session's open,
     returns open-to-open on an adjusted basis), cost model and parameters, delisting
     haircut, extreme-return policy, filing lag.
  7. **Provenance appendix**: BacktestConfig dump, strategy params, provider names,
     actions-cache fetched_at range, cache dir, run_seconds, quantlab version.
- src/quantlab/reporting/templates/report.html.j2 and report.md.j2 — jinja2; the two
  templates render the SAME context; a test asserts every numeric value present in the
  markdown appears in the HTML (no drift).
- src/quantlab/reporting/render.py — `render_report(result_dir, out_dir, fmt="both")`:
  loads BacktestResult + report_card.json (+ validation_basic.json), builds context,
  renders both files, embeds PNGs as base64 in HTML and writes them as files beside the
  markdown.
- CLI: `quantlab report --result <dir> [--card <dir>] --out <dir> [--format html|md|both]`.
- tests/test_plots.py (each plot returns a non-empty PNG on a fixture; no display),
  test_report_context.py (every section key present; caveat strings verbatim; dirty
  badge toggles; NaN benchmark path), test_render.py (both files render from the M05/M06
  fixture results; markdown/HTML numeric parity; HTML has zero external `src=`/`href=`
  to http(s)), test_cli_report.py.

## Out of scope
Paper trading (M08). Comparison reports across strategies (M09 may add a one-page
side-by-side). Interactive dashboards — never.

## Context (read these, nothing else)
- This packet; CLAUDE.md; plans/QUANT-NOTES.md (every item addressed to M07)
- src/quantlab/backtest/result.py; src/quantlab/validation/{basic,report_card}.py (as
  merged from M05/M06 — read the actual dataclasses and JSON layouts);
  configs/validation.yaml; src/quantlab/cli.py
- Port source (read-only): C:\Users\arwga\Developer\ClaudeProjects\Trading\
  MomentumValueStrategy\src\evaluation\plots.py

## Interfaces to honor
`BacktestResult`, `ValidationBasic`, `ReportCard` are read-only inputs. jinja2 and
matplotlib are already dependencies; add nothing else.

## Acceptance criteria
1. `uv run pytest` green offline; `ruff check` + `format --check` clean.
2. Rendering the M06 fixture results for all three verdicts produces three HTML + three
   markdown files; each HTML is self-contained (no external references) and under 5 MB.
3. Every carried-note statement listed in sections 3, 5 and 6 appears verbatim (tests
   assert the exact strings).
4. Markdown/HTML numeric parity test passes.
5. `quantlab report --help` works and an end-to-end CLI run on a fixture writes both files.

## Verification commands
- `uv run pytest tests/ -q`; `uv run ruff check`; `uv run ruff format --check`
- `uv run quantlab report --help`

## Carried from the M06 verdict (binding — full text in plans/QUANT-NOTES.md "From M06 verdict")
1. The report must print N trials as a NUMBER, the realised Reality Check trial count K
   and common-period count, a distinct sentence when DSR is NaN because the registry is
   thin, the untrusted-fraction line, the Sharpe (ddof=1, annualised) and Sortino
   (target 0, ddof=0) conventions, and capacity's spread percentiles beside the AUM range.
2. If a walk-forward is quoted, retain and print the per-step training Sharpes (so a NaN
   first-point tie-break is visible), the chosen-weight sequence, and the "ranking
   agreement under both cost conventions: checked / not checked" line.
3. Informational lines the report must carry, verbatim in spirit: "min_psr 0.95 binds only
   below an annualised Sharpe of about 0.47 on a 12-year monthly book" and "the Monte
   Carlo drawdown gate sits at the centre of its own statistic's null" — neither gate is
   evidence of quality; say so next to the badges.
4. Intended capital: `intended_capital_usd` is printed with the capacity ceiling and the
   old repo's own $95M–$335M range for context; at Alex's retail stake the capacity gate
   is trivially passable and the report must say that plainly rather than let a green
   badge imply an edge.
5. The sensitivity flags (nan_points, neighbourhood_size, neighbourhood_truncated) are
   printed beside no_cliff_score, which is never described as quality.
6. Number formatting is the report layer's job: never `repr` a numpy scalar (no
   `np.float64(1.0)`), NaN renders as "n/a (reason)" with the reason from the gate, and
   percentages/ratios use fixed precision. The M06 markdown card's `_report_card_markdown`
   is replaced by the M07 template (keep the JSON as the source of truth).
7. State that DSR is not monotone in the number of trials above the variance floor, beside
   the DSR badge, and print N (deduplicated) and the raw record count side by side.
