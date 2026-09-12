"""Unit tests for the `quantlab report` CLI command (work packet acceptance
criterion 5): `--help` works, and an end-to-end run on a fixture writes both
files."""

from __future__ import annotations

from typer.testing import CliRunner

from quantlab.cli import app
from tests._report_fixtures import build_eligible, save_result_and_card

runner = CliRunner()


def test_report_help_works():
    result = runner.invoke(app, ["report", "--help"])
    assert result.exit_code == 0
    assert "--result" in result.output
    assert "--out" in result.output
    assert "--format" in result.output


def test_report_end_to_end_writes_both_files(tmp_path):
    result, card = build_eligible(tmp_path / "build")
    result_dir = save_result_and_card(result, card, tmp_path / "result")
    out_dir = tmp_path / "out"

    invocation = runner.invoke(app, ["report", "--result", str(result_dir), "--out", str(out_dir)])

    assert invocation.exit_code == 0, invocation.output
    assert (out_dir / "report.html").exists()
    assert (out_dir / "report.md").exists()
    assert "wrote html" in invocation.output
    assert "wrote md" in invocation.output


def test_report_format_html_only(tmp_path):
    result, card = build_eligible(tmp_path / "build")
    result_dir = save_result_and_card(result, card, tmp_path / "result")
    out_dir = tmp_path / "out"

    invocation = runner.invoke(
        app,
        ["report", "--result", str(result_dir), "--out", str(out_dir), "--format", "html"],
    )

    assert invocation.exit_code == 0, invocation.output
    assert (out_dir / "report.html").exists()
    assert not (out_dir / "report.md").exists()


def test_report_rejects_invalid_format(tmp_path):
    result, card = build_eligible(tmp_path / "build")
    result_dir = save_result_and_card(result, card, tmp_path / "result")
    out_dir = tmp_path / "out"

    invocation = runner.invoke(
        app,
        ["report", "--result", str(result_dir), "--out", str(out_dir), "--format", "pdf"],
    )

    assert invocation.exit_code != 0


def test_report_passes_the_validation_config_for_the_monte_carlo_seed(tmp_path, monkeypatch):
    # quant-gate VERDICT.md M07 cycle-1 finding 11: `quantlab report` used to
    # never pass a `config` through, so `_monte_carlo_seed(None)` silently
    # defaulted to 1 regardless of `configs/validation.yaml`'s own
    # `bootstrap.monte_carlo_seed` - the fan plot could silently draw a
    # DIFFERENT sample than the one behind the quoted percentiles.
    import quantlab.reporting.render as render_module

    result, card = build_eligible(tmp_path / "build")
    result_dir = save_result_and_card(result, card, tmp_path / "result")
    out_dir = tmp_path / "out"

    config_path = tmp_path / "validation.yaml"
    config_path.write_text("bootstrap:\n  monte_carlo_seed: 42\nthresholds: {}\n", encoding="utf-8")

    captured: dict[str, object] = {}
    real_render_report = render_module.render_report

    def _spy(*args, **kwargs):
        captured["config"] = kwargs.get("config")
        return real_render_report(*args, **kwargs)

    monkeypatch.setattr(render_module, "render_report", _spy)

    invocation = runner.invoke(
        app,
        [
            "report",
            "--result",
            str(result_dir),
            "--out",
            str(out_dir),
            "--config",
            str(config_path),
        ],
    )

    assert invocation.exit_code == 0, invocation.output
    assert captured["config"] is not None
    assert captured["config"].bootstrap.monte_carlo_seed == 42


def test_report_with_explicit_card_dir(tmp_path):
    result, card = build_eligible(tmp_path / "build")
    result_dir = tmp_path / "result"
    result.save(result_dir)
    card_dir = save_result_and_card(result, card, tmp_path / "card")
    out_dir = tmp_path / "out"

    invocation = runner.invoke(
        app,
        [
            "report",
            "--result",
            str(result_dir),
            "--card",
            str(card_dir),
            "--out",
            str(out_dir),
        ],
    )

    assert invocation.exit_code == 0, invocation.output
    html = (out_dir / "report.html").read_text(encoding="utf-8")
    assert "ELIGIBLE_FOR_PAPER" in html
