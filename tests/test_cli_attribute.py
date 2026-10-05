"""`quantlab attribute` end to end on a fixture run directory (planted betas,
synthetic factor files in the library's own CSV layout - no network), plus the
report's Attribution section."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml
from typer.testing import CliRunner

from quantlab.attribution.build import SECTOR_NOTE, build_attribution
from quantlab.attribution.factors import BASE_URL, FF5_ZIP, MOM_ZIP, KenFrenchProvider
from quantlab.cli import app
from quantlab.reporting.context import _attribution_section

runner = CliRunner()

N_MONTHS = 84  # 2014-01 .. 2020-12
PLANTED_BETA = 1.2
PLANTED_ALPHA = 0.002  # per month


def _factor_texts(seed: int = 5) -> tuple[pd.DataFrame, str, str]:
    """Synthetic factors as decimals, and the same data as the library's two
    CSV files (percent units, annual block, copyright footer)."""
    rng = np.random.default_rng(seed)
    idx = pd.period_range("2014-01", periods=N_MONTHS, freq="M")
    frame = pd.DataFrame(
        {
            "Mkt-RF": rng.normal(0.008, 0.04, N_MONTHS),
            "SMB": rng.normal(0.0, 0.02, N_MONTHS),
            "HML": rng.normal(0.0, 0.02, N_MONTHS),
            "RMW": rng.normal(0.0, 0.015, N_MONTHS),
            "CMA": rng.normal(0.0, 0.015, N_MONTHS),
            "Mom": rng.normal(0.004, 0.03, N_MONTHS),
            "RF": np.full(N_MONTHS, 0.0005),
        },
        index=idx,
    )
    ff5 = ["Fake file.", "", ",Mkt-RF,SMB,HML,RMW,CMA,RF"]
    mom = ["Fake momentum file. It", "", ",Mom"]
    for p, row in frame.iterrows():
        code = p.strftime("%Y%m")
        ff5.append(
            f"{code}, "
            + ", ".join(f"{row[c] * 100:.8f}" for c in ["Mkt-RF", "SMB", "HML", "RMW", "CMA", "RF"])
        )
        mom.append(f"{code}, {row['Mom'] * 100:.8f}")
    ff5 += [
        "",
        " Annual Factors: January-December ",
        ",Mkt-RF,SMB,HML,RMW,CMA,RF",
        "  2014, 1, 1, 1, 1, 1, 1",
    ]
    mom += ["", "Annual Factors:", ",Mom", "  2014, 1"]
    # round-trip the frame through the same rounding the files carry
    for col in frame.columns:
        frame[col] = (frame[col] * 100).round(8) / 100
    return frame, "\n".join(ff5) + "\n", "\n".join(mom) + "\n"


def _zip(name: str, text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, text)
    return buf.getvalue()


def _populate_factor_cache(cache_dir: Path) -> pd.DataFrame:
    frame, ff5_text, mom_text = _factor_texts()
    payload = {
        BASE_URL + FF5_ZIP: _zip("ff5.csv", ff5_text),
        BASE_URL + MOM_ZIP: _zip("m.csv", mom_text),
    }
    KenFrenchProvider(
        cache_dir, mode="refresh", fetch=lambda url: (payload[url], "Mon, 05 Oct 2026")
    ).load()
    return frame


def _write_series(path: Path, s: pd.Series) -> None:
    frame = s.rename("value").to_frame()
    frame.index.name = "date"
    frame.to_parquet(path)


def _make_run(
    root: Path, factors: pd.DataFrame, *, with_holdings: bool = True, freq: str = "month_end"
):
    """A run dir whose strategy is `RF + alpha + 1.2 * Mkt-RF + noise` and
    whose 'SPY' is the market plus a little noise."""
    rng = np.random.default_rng(99)
    run = root / "run"
    run.mkdir()
    dates = pd.DatetimeIndex(factors.index.to_timestamp("M"), name="date")
    mkt = factors["Mkt-RF"].to_numpy()
    rf = factors["RF"].to_numpy()
    net = pd.Series(
        rf + PLANTED_ALPHA + PLANTED_BETA * mkt + rng.normal(0, 0.01, N_MONTHS), index=dates
    )
    bench = pd.Series(rf + mkt + rng.normal(0, 0.002, N_MONTHS), index=dates)
    _write_series(run / "net_returns.parquet", net)
    _write_series(run / "benchmark_returns.parquet", bench)
    _write_series(run / "net_equity.parquet", (1 + net).cumprod())
    _write_series(run / "benchmark_equity.parquet", (1 + bench).cumprod())
    (run / "provenance.json").write_text(
        json.dumps(
            {"strategy_id": "fixture-strategy-0000", "backtest_config": {"rebalance_freq": freq}}
        )
    )
    if with_holdings:
        holdings = {str(d.date()): {"weights": {f"T{i}": 1 / 20 for i in range(20)}} for d in dates}
        (run / "holdings_history.json").write_text(json.dumps(holdings))
    return run, net, bench


@pytest.fixture
def world(tmp_path):
    cache_dir = tmp_path / "cache"
    factors = _populate_factor_cache(cache_dir)
    platform = tmp_path / "platform.yaml"
    platform.write_text(
        yaml.safe_dump(
            {
                "cache_dir": str(cache_dir),
                "reports_dir": str(tmp_path / "reports"),
                "providers": {
                    "prices": "yfinance",
                    "constituents": "sp500_community",
                    "fundamentals": "edgar",
                },
            }
        )
    )
    run, net, bench = _make_run(tmp_path, factors)
    return {
        "tmp": tmp_path,
        "factors": factors,
        "platform": platform,
        "run": run,
        "net": net,
        "bench": bench,
    }


def _invoke(world, *extra, out=None):
    out = out or world["tmp"] / "out"
    args = [
        "attribute",
        "--result",
        str(world["run"]),
        "--out",
        str(out),
        "--platform",
        str(world["platform"]),
        *extra,
    ]
    return runner.invoke(app, args), out


def test_attribute_help_lists_the_options():
    res = runner.invoke(app, ["attribute", "--help"])
    assert res.exit_code == 0
    for opt in ("--result", "--factors", "--out", "--series"):
        assert opt in res.output


def test_attribute_end_to_end_recovers_the_planted_beta_and_closes_the_identity(world):
    res, out = _invoke(world)

    assert res.exit_code == 0, res.output
    att = json.loads((out / "attribution.json").read_text())
    assert (out / "attribution.md").exists()
    assert att["strategy_id"] == "fixture-strategy-0000"
    assert att["sample"]["n_used"] == N_MONTHS and att["sample"]["n_dropped_by_alignment"] == 0
    assert att["capm"]["loadings"]["Mkt-RF"]["coef"] == pytest.approx(PLANTED_BETA, abs=0.05)
    assert att["ff5_mom"]["loadings"]["Mkt-RF"]["coef"] == pytest.approx(PLANTED_BETA, abs=0.05)
    assert att["ff5_mom"]["n"] == N_MONTHS
    d = att["decomposition"]
    parts = d["components"]
    assert sum(parts.values()) == pytest.approx(d["excess_cagr_aligned"], abs=1e-12)
    assert d["beta_vs_benchmark"] == pytest.approx(PLANTED_BETA, abs=0.05)
    assert att["factor_vintage"]["files"][FF5_ZIP]["last_modified"] == "Mon, 05 Oct 2026"
    assert att["sector_exposure"] == SECTOR_NOTE
    assert att["concentration"]["holdings"]["effective_n_mean"] == pytest.approx(20.0)
    assert len(att["rolling_beta_36m"]["series"]) == N_MONTHS - 36 + 1
    assert "net_sharpe_vs_benchmark" in att["gate_note"]


def test_attribute_without_a_holdings_file_says_so_instead_of_failing(world):
    (world["run"] / "holdings_history.json").unlink()

    res, out = _invoke(world)

    assert res.exit_code == 0, res.output
    att = json.loads((out / "attribution.json").read_text())
    assert att["concentration"]["holdings"].startswith("not available")


def test_attribute_series_benchmark_is_the_calibration_run(world):
    res, out = _invoke(world, "--series", "benchmark")

    assert res.exit_code == 0, res.output
    att = json.loads((out / "attribution.json").read_text())
    assert att["strategy_id"] is None and "decomposition" not in att
    assert att["capm"]["loadings"]["Mkt-RF"]["coef"] == pytest.approx(1.0, abs=0.05)
    assert abs(att["capm"]["alpha_annualised_arithmetic"]) < 0.01
    assert att["calibration"]["correlation_with_library_market"] > 0.99
    assert len(att["calibration"]["expected_gap_causes"]) >= 3


def test_attribute_refuses_a_run_dir_without_provenance(world):
    (world["run"] / "provenance.json").unlink()

    res, out = _invoke(world)

    assert res.exit_code == 1
    assert "provenance.json" in res.output
    assert not (out / "attribution.json").exists()


def test_attribute_refuses_a_non_monthly_run(tmp_path):
    cache_dir = tmp_path / "cache"
    factors = _populate_factor_cache(cache_dir)
    run, _, _ = _make_run(tmp_path, factors, freq="weekly")
    platform = tmp_path / "platform.yaml"
    platform.write_text(
        yaml.safe_dump(
            {
                "cache_dir": str(cache_dir),
                "reports_dir": str(tmp_path / "reports"),
                "providers": {
                    "prices": "yfinance",
                    "constituents": "sp500_community",
                    "fundamentals": "edgar",
                },
            }
        )
    )

    res = runner.invoke(
        app,
        [
            "attribute",
            "--result",
            str(run),
            "--out",
            str(tmp_path / "o"),
            "--platform",
            str(platform),
        ],
    )

    assert res.exit_code == 1 and "month_end" in res.output


def test_attribute_with_an_empty_factor_cache_refuses_and_never_downloads(tmp_path, monkeypatch):
    def boom(url):
        raise AssertionError("network touched in cached mode")

    monkeypatch.setattr("quantlab.attribution.factors._http_fetch", boom)
    factors = _factor_texts()[0]
    run, _, _ = _make_run(tmp_path, factors)
    platform = tmp_path / "platform.yaml"
    platform.write_text(
        yaml.safe_dump(
            {
                "cache_dir": str(tmp_path / "empty_cache"),
                "reports_dir": str(tmp_path / "reports"),
                "providers": {
                    "prices": "yfinance",
                    "constituents": "sp500_community",
                    "fundamentals": "edgar",
                },
            }
        )
    )

    res = runner.invoke(
        app,
        [
            "attribute",
            "--result",
            str(run),
            "--out",
            str(tmp_path / "o"),
            "--platform",
            str(platform),
        ],
    )

    assert res.exit_code == 1 and "--factors refresh" in res.output


def test_attribute_rejects_an_unknown_factors_mode(world):
    res, _ = _invoke(world, "--factors", "sometimes")

    assert res.exit_code != 0


def test_attribute_into_the_run_dir_adds_only_the_two_attribution_files(world):
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in world["run"].iterdir()}

    res, _ = _invoke(world, out=world["run"])

    assert res.exit_code == 0, res.output
    after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in world["run"].iterdir()}
    assert set(after) - set(before) == {"attribution.json", "attribution.md"}
    for name, digest in before.items():
        assert after[name] == digest  # nothing the run produced was touched


def test_attribution_is_deterministic(world):
    _, out1 = _invoke(world, out=world["tmp"] / "o1")
    _, out2 = _invoke(world, out=world["tmp"] / "o2")

    assert (out1 / "attribution.json").read_bytes() == (out2 / "attribution.json").read_bytes()
    assert (out1 / "attribution.md").read_bytes() == (out2 / "attribution.md").read_bytes()


def test_a_run_with_too_few_months_in_the_factor_data_is_refused_by_the_builder(world):
    short = world["factors"].iloc[:30]
    data = KenFrenchProvider(world["tmp"] / "cache", mode="cached").load()
    data = type(data)(frame=short, vintage=data.vintage)

    from quantlab.attribution.build import AttributionError

    with pytest.raises(AttributionError, match="overlap"):
        build_attribution(world["run"], data)


def test_builder_counts_months_the_factor_data_does_not_reach(world):
    data = KenFrenchProvider(world["tmp"] / "cache", mode="cached").load()
    truncated = type(data)(frame=world["factors"].iloc[:-5], vintage=data.vintage)

    att = build_attribution(world["run"], truncated)

    assert att["sample"]["n_returns"] == N_MONTHS
    assert att["sample"]["n_used"] == N_MONTHS - 5
    assert att["sample"]["n_dropped_by_alignment"] == 5
    assert att["sample"]["dropped_months"] == [str(p) for p in world["factors"].index[-5:]]


# --- report section ------------------------------------------------------------


def test_report_section_is_built_from_attribution_json_and_absent_without_it(world):
    res, out = _invoke(world)
    att = json.loads((out / "attribution.json").read_text())

    section = _attribution_section(att)

    assert section is not None
    assert section["capm_beta"] == f"{att['capm']['loadings']['Mkt-RF']['coef']:.3f}"
    assert [r["name"] for r in section["loadings"]] == ["Mkt-RF", "SMB", "HML", "RMW", "CMA", "Mom"]
    assert [r["name"] for r in section["components"]][-1] == "Excess CAGR over SPY"
    assert _attribution_section(None) is None
    cal, cal_out = _invoke(world, "--series", "benchmark", out=world["tmp"] / "cal")
    assert _attribution_section(json.loads((cal_out / "attribution.json").read_text())) is None


@pytest.mark.slow  # full backtest+report fixture pipeline (as the other render tests)
def test_report_renders_the_attribution_section_only_when_the_file_exists(world, tmp_path):
    from quantlab.reporting.render import render_report
    from tests._report_fixtures import build_eligible, save_result_and_card

    result, card = build_eligible(tmp_path / "build")
    result_dir = save_result_and_card(result, card, tmp_path / "result")

    render_report(result_dir, tmp_path / "plain", fmt="md")
    plain = (tmp_path / "plain" / "report.md").read_text(encoding="utf-8")
    assert "## Attribution" not in plain

    res, out = _invoke(world)
    (result_dir / "attribution.json").write_text((out / "attribution.json").read_text())
    render_report(result_dir, tmp_path / "with", fmt="both")
    with_md = (tmp_path / "with" / "report.md").read_text(encoding="utf-8")
    with_html = (tmp_path / "with" / "report.html").read_text(encoding="utf-8")

    assert "## Attribution" in with_md and "<h2>Attribution</h2>" in with_html
    # the only difference is the new section
    stripped = (
        with_md.split("## Attribution")[0]
        + "## Provenance appendix"
        + with_md.split("## Provenance appendix")[1]
    )
    assert stripped == plain
