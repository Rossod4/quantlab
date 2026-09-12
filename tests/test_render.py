"""Unit tests for src/quantlab/reporting/render.py (work packet acceptance
criteria 2, 3, 4): rendering the three M06 fixture verdicts (REJECTED,
RESEARCH_ONLY, ELIGIBLE_FOR_PAPER) produces a self-contained HTML report
(no external `src=`/`href=` to http(s), under 5 MB) and a markdown twin with
numeric parity, and every carried-note statement from packet sections 3, 5
and 6 appears verbatim.
"""

from __future__ import annotations

import re

import pytest

from quantlab.reporting import context as context_module
from quantlab.reporting.render import render_report
from tests._report_fixtures import (
    build_eligible,
    build_eligible_with_walk_forward,
    build_rejected,
    build_research_only,
    save_result_and_card,
)

_EXTERNAL_REF_RE = re.compile(r'(?:src|href)\s*=\s*["\']https?://', re.IGNORECASE)
_NUMBER_RE = re.compile(r"-?\d[\d,]*\.?\d*%?")
# quant-gate VERDICT.md M07 cycle-1 finding 1: a 4th fixture with a REAL
# walk-forward result (produced by walk_forward_blend, not hand-written)
# plus a fully populated backtest_config (finding 6's next_open coverage),
# so section 5's walk-forward block and section 6's next_open sentence are
# both exercised by the rendering acceptance suite, not only a unit test.
_FIXTURE_NAMES = ["rejected", "research_only", "eligible", "walk_forward"]


@pytest.fixture(scope="module", params=_FIXTURE_NAMES)
def rendered(request, tmp_path_factory):
    # module-scoped and keyed by param: building a report card runs the real
    # bootstrap/PSR/DSR/capacity machinery (~2s each), and this module reuses
    # one render per verdict across every assertion function below rather
    # than rebuilding it per test (repo budget: keep `pytest tests/` under
    # 90s - see plans/M07-reporting.md's verification commands).
    builder = {
        "rejected": build_rejected,
        "research_only": build_research_only,
        "eligible": build_eligible,
        "walk_forward": build_eligible_with_walk_forward,
    }[request.param]
    tmp_path = tmp_path_factory.mktemp(f"render_{request.param}")
    result, card = builder(tmp_path / "build")
    result_dir = save_result_and_card(result, card, tmp_path / "result")
    out_dir = tmp_path / "out"
    written = render_report(result_dir, out_dir)
    html = written["html"].read_text(encoding="utf-8")
    md = written["md"].read_text(encoding="utf-8")
    return {
        "name": request.param,
        "verdict": card.verdict,
        "html_path": written["html"],
        "md_path": written["md"],
        "html": html,
        "md": md,
    }


# --- acceptance criterion 2: self-contained, under 5MB ----------------------


def test_both_files_written_and_under_5mb(rendered):
    assert rendered["html_path"].exists()
    assert rendered["md_path"].exists()
    assert rendered["html_path"].stat().st_size < 5 * 1024 * 1024
    assert rendered["md_path"].stat().st_size < 5 * 1024 * 1024


def test_html_has_zero_external_references(rendered):
    assert not _EXTERNAL_REF_RE.search(rendered["html"]), "HTML report references an external URL"


def test_html_contains_the_verdict(rendered):
    assert rendered["verdict"] in rendered["html"]
    assert rendered["verdict"] in rendered["md"]


# --- acceptance criterion 4: markdown/HTML numeric parity -------------------


def test_markdown_numbers_all_appear_in_html(rendered):
    md_numbers = {
        tok for tok in _NUMBER_RE.findall(rendered["md"]) if any(c.isdigit() for c in tok)
    }
    missing = [n for n in md_numbers if n not in rendered["html"]]
    assert not missing, f"numbers present in markdown but missing from HTML: {missing[:20]}"


# --- acceptance criterion 3: carried-note strings verbatim (sections 3, 5, 6) --


def test_section_3_trust_panel_carried_strings_verbatim(rendered):
    for text in (rendered["html"], rendered["md"]):
        assert context_module.COVERAGE_BOUND_DEFINITION in text
        assert context_module.SEPARATE_SELECTION_EFFECTS_NOTE in text


def test_section_5_rolling_ported_convention_verbatim(rendered):
    for text in (rendered["html"], rendered["md"]):
        assert context_module.ROLLING_PORTED_CONVENTION_NOTE in text


def test_section_6_execution_mode_note_present(rendered):
    # every fixture except "walk_forward" leaves execution unset, so the
    # honest "not recorded" note must appear verbatim; "walk_forward"
    # (quant-gate VERDICT.md M07 cycle-1 finding 6) is the one fixture with a
    # fully populated backtest_config, and must show the REAL next_open
    # sentence instead - never both, never neither.
    if rendered["name"] == "walk_forward":
        for text in (rendered["html"], rendered["md"]):
            assert "next_open = next session's open" in text
            assert "open-to-open" in text
            assert "execution mode not recorded" not in text
    else:
        for text in (rendered["html"], rendered["md"]):
            assert "execution mode not recorded in the backtest_config for this run." in text


def test_section_5_sensitivity_pairing_present_only_when_sensitivity_ran(rendered):
    # only "eligible" and "walk_forward" supply a sensitivity grid
    # (tests/_report_fixtures.py); the other two must NOT show a fabricated
    # pairing sentence for a grid that never ran. Keyed by fixture NAME, not
    # by the resulting verdict string - "walk_forward" also supplies a
    # walk-forward result, which can independently fail its own soft gate
    # and cap the verdict below ELIGIBLE_FOR_PAPER without changing whether
    # sensitivity ran.
    if rendered["name"] in ("eligible", "walk_forward"):
        for text in (rendered["html"], rendered["md"]):
            assert "never evidence of quality by itself" in text
            assert "gated ALONGSIDE no_cliff_score" in text
    else:
        assert "never evidence of quality by itself" not in rendered["md"]


# --- quant-gate REVIEW.md iteration-2 findings ------------------------------


def test_section_4_min_psr_and_monte_carlo_informational_notes_verbatim(rendered):
    for text in (rendered["html"], rendered["md"]):
        assert (
            "min_psr 0.95 binds only below an annualised Sharpe of about 0.47 on a 12-year "
            "monthly book" in text
        )
        assert (
            "the Monte Carlo drawdown gate sits at the centre of its own statistic's null" in text
        )
        assert "neither is evidence of quality" in text


def test_section_4_n_trials_raw_and_dirty_count_shown_beside_deduplicated_n(rendered):
    for text in (rendered["html"], rendered["md"]):
        assert "raw key count:" in text
        assert "dirty)" in text


def test_html_escapes_a_malicious_ticker_in_a_gate_reason_and_stays_well_formed():
    # quant-gate REVIEW.md finding 1: a ticker symbol (or any other
    # externally-sourced string) reaching a gate's `reason` must render
    # ESCAPED in the HTML report and leave the page structurally intact,
    # never break out into raw markup - while the markdown twin (no
    # HTML-injection surface) keeps it verbatim, and the platform-internal
    # carried-note constants elsewhere in the SAME context are unaffected.
    from quantlab.reporting import render as render_module
    from tests.test_report_context import _report_card, _result

    payload = "<b>&x"
    card = _report_card()
    card["gates"][0] = dict(card["gates"][0])
    card["gates"][0]["reason"] += f" Excluded ticker(s): {payload}"
    context = context_module.build_report_context(_result(), card, None)

    html_context = dict(context)
    html_context["plots"] = {}
    html_context["plot_errors"] = {}
    html = render_module._html_environment().get_template("report.html.j2").render(**html_context)

    md_context = dict(context)
    md_context["plot_files"] = {}
    md_context["plot_errors"] = {}
    md = render_module._markdown_environment().get_template("report.md.j2").render(**md_context)

    assert payload not in html
    assert "&lt;b&gt;&amp;x" in html
    assert html.rstrip().endswith("</html>")

    assert payload in md

    assert context_module.COVERAGE_BOUND_DEFINITION in html
    assert context_module.COVERAGE_BOUND_DEFINITION in md


# --- quant-gate VERDICT.md iteration-3 findings -----------------------------


def test_walk_forward_comparison_table_has_real_numbers_not_na(rendered):
    # quant-gate VERDICT.md M07 cycle-1 finding 1 (BLOCKER): the comparison
    # table used to render every cell "n/a (not available)" under a
    # transposed axis read. Only the "walk_forward" fixture supplies a real
    # WalkForwardResult, so this checks it specifically.
    if rendered["name"] != "walk_forward":
        return
    for text in (rendered["html"], rendered["md"]):
        assert "Walk-Forward" in text  # the walk-forward portfolio's own row
        assert "Fixed 100% momentum/0% value" in text  # a fixed grid-point row
    # a well-formed comparison row never reads "n/a (not available)" - the
    # metrics are real numbers on this fixture's own synthetic returns.
    row_region_start = rendered["md"].index("Grid point | CAGR")
    row_region = rendered["md"][row_region_start : row_region_start + 2000]
    assert "n/a (not available)" not in row_region


def test_walk_forward_chosen_weight_table_renders_real_weights(rendered):
    # quant-gate VERDICT.md M07 cycle-1 finding 2 (BLOCKER): the chosen-weight
    # sequence must be TEXT (a table), not only a PNG - diffable in git.
    if rendered["name"] != "walk_forward":
        return
    for text in (rendered["html"], rendered["md"]):
        assert "Chosen weight per step" in text
        assert "momentum" in text and "value" in text


def test_sensitivity_surface_table_renders_base_point(rendered):
    # quant-gate VERDICT.md M07 cycle-1 finding 2 (BLOCKER): the sensitivity
    # surface (axes, base point, edge/NaN flags) must exist as TEXT too.
    if rendered["name"] not in ("eligible", "walk_forward"):
        return
    for text in (rendered["html"], rendered["md"]):
        assert "base point" in text.lower()
        assert "lookback_months=12" in text


def test_capacity_old_repo_reference_range_present(rendered):
    # quant-gate VERDICT.md M07 cycle-1 finding 3 (BLOCKER): the old repo's
    # $95M-$335M capacity estimate must appear beside THIS run's own AUM
    # ceiling, for scale, sourced from a named constant.
    if rendered["name"] not in ("eligible", "walk_forward"):
        return
    for text in (rendered["html"], rendered["md"]):
        assert "$95,000,000" in text
        assert "$335,000,000" in text
        assert "50-name book" in text
        assert "NOT the output of this run" in text


def test_infinity_never_renders_bare(rendered):
    # quant-gate VERDICT.md M07 cycle-1 finding 5: the REJECTED fixture (weak
    # strategy vs. a strong benchmark) drives min_track_record_length to
    # +inf. context.py's OWN formatting (the gates.min_trl summary line and
    # the gate table's Value column - the two things this layer controls;
    # report_card.py's own prose REASON string is a read-only upstream
    # input and is out of scope here) must never print a bare "inf".
    if rendered["name"] != "rejected":
        return
    assert "min track-record length unbounded (n/a)" in rendered["md"]
    assert "min track-record length unbounded (n/a)" in rendered["html"]

    row = next(
        line
        for line in rendered["md"].splitlines()
        if line.startswith("| min_track_record_length |")
    )
    cells = [c.strip() for c in row.strip("|").split("|")]
    value_cell = cells[2]
    threshold_cell = cells[3]
    assert value_cell == "unbounded (n/a)", value_cell
    assert threshold_cell != "inf"


def test_verdict_legend_present(rendered):
    # quant-gate VERDICT.md M07 cycle-1 finding 10.
    for text in (rendered["html"], rendered["md"]):
        assert "A verdict is not evidence of edge" in text
        assert "ELIGIBLE_FOR_PAPER: every hard and soft gate passed" in text


def test_coverage_bound_sentence_appears_exactly_once(rendered):
    # quant-gate VERDICT.md M07 cycle-1 finding 12 (cosmetic): `validate_
    # basic`'s own coverage/selection sentence (unique anchor: "worst
    # sampled year's uncached/masked universe fraction" - distinct wording
    # from context.py's OWN `COVERAGE_BOUND_DEFINITION` constant, which also
    # legitimately contains the phrase "SEPARATE selection effects") used to
    # print twice: once in the trust panel, once again under Robustness ->
    # Flags. (Anchor has no apostrophe - the HTML render legitimately
    # escapes plain, non-Markup text, e.g. "year's" -> "year&#39;s".)
    for text in (rendered["html"], rendered["md"]):
        assert text.count("uncached/masked universe fraction") == 1


def test_markdown_twin_has_no_html_entities(rendered):
    # quant-gate VERDICT.md M07 cycle-1 finding 12 (cosmetic): the markdown
    # twin is plain text and must never rely on HTML-entity decoding.
    for entity in ("&middot;", "&mdash;", "&amp;", "&lt;", "&gt;"):
        assert entity not in rendered["md"], f"markdown twin contains raw HTML entity {entity!r}"


def test_rolling_table_truncated_with_row_count(rendered):
    # quant-gate VERDICT.md M07 cycle-1 finding 12 (cosmetic): a 60-period
    # fixture at a 1y window produces 49 rows - must be truncated with the
    # total stated, not dumped in full.
    if rendered["name"] not in ("eligible", "walk_forward", "research_only"):
        return
    for text in (rendered["html"], rendered["md"]):
        assert "Showing first/last 5 of 49 rows" in text


def test_unscored_names_caveat_states_data_semantics_version(rendered):
    # quant-gate VERDICT.md M07 cycle-1 finding 4: the caveat must name which
    # data_semantics_version the run used and what that implies.
    for text in (rendered["html"], rendered["md"]):
        assert "data_semantics_version (m03b)" in text
        assert "predates M04b" in text


def test_plot_failure_is_visible_not_silent(tmp_path, monkeypatch, caplog):
    # quant-gate VERDICT.md M07 cycle-1 finding 7: a crashed plot must render
    # a visible "plot unavailable: <reason>" and be logged, never just omit
    # the section as if the input were legitimately absent.
    import logging

    from quantlab.reporting import plots

    def _boom(*_args, **_kwargs):
        raise ValueError("synthetic plot failure for testing")

    monkeypatch.setattr(plots, "plot_equity_curves", _boom)

    result, card = build_eligible(tmp_path / "build")
    result_dir = save_result_and_card(result, card, tmp_path / "result")
    with caplog.at_level(logging.WARNING, logger="quantlab.reporting.render"):
        written = render_report(result_dir, tmp_path / "out")
    html = written["html"].read_text(encoding="utf-8")
    md = written["md"].read_text(encoding="utf-8")

    assert "plot unavailable: ValueError: synthetic plot failure for testing" in html
    assert "plot unavailable: ValueError: synthetic plot failure for testing" in md
    assert any(
        "equity_curve" in r.message and "synthetic plot failure" in r.message
        for r in caplog.records
    )


# --- basic-only (no --full report card) fallback ----------------------------


def test_basic_only_fallback_selects_untrusted_line_by_key_not_position(tmp_path):
    # quant-gate VERDICT.md M07 cycle-1 finding 9: the coverage/selection
    # sentence must be found by its own content, not assumed to be flags[0].
    from quantlab.reporting.render import _synthesize_report_card_from_basic

    result, _card = build_eligible(tmp_path / "build")
    basic = {
        "flags": [
            "some unrelated flag that happens to come first",
            "coverage bound 5.0% - this bound and the unscored/dropped counts are "
            "SEPARATE selection effects, not additive into one headline number",
        ],
        "metrics": {},
        "rolling": {},
        "subperiods": {},
        "walk_forward": None,
        "sensitivity": None,
    }
    synthesized = _synthesize_report_card_from_basic(basic, result)
    assert "SEPARATE selection effects" in synthesized["provenance"]["untrusted_fraction_line"]

    # and when NO flag matches, the line is empty rather than mislabeling an
    # arbitrary one.
    basic_no_match = dict(basic, flags=["totally unrelated flag"])
    synthesized_no_match = _synthesize_report_card_from_basic(basic_no_match, result)
    assert synthesized_no_match["provenance"]["untrusted_fraction_line"] == ""


def test_render_falls_back_to_validation_basic_when_no_report_card(tmp_path):
    result, _card = build_eligible(tmp_path / "build")
    result_dir = tmp_path / "result"
    result_dir.mkdir()
    result.save(result_dir)
    # no report_card.json written - only validation_basic.json, mimicking a
    # `quantlab validate` (no --full) run.
    import json

    from quantlab.validation.basic import load_validation_config, validate_basic

    config = load_validation_config("configs/validation.yaml")
    basic = validate_basic(result, None, config)
    (result_dir / "validation_basic.json").write_text(json.dumps(basic.to_json()))

    written = render_report(result_dir, tmp_path / "out")
    html = written["html"].read_text(encoding="utf-8")
    assert "NOT EVALUATED" in html
    assert result.provenance["strategy_id"] in html
