"""Unit tests for src/quantlab/cli.py's `validate` one-liner (quant-gate
VERDICT.md cycle-1 finding 4: a nonzero extreme-return count must appear in
the one-liner, with the long/short breakdown), plus (new for M06) an
end-to-end `quantlab validate --full` smoke test (acceptance criterion 9)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from typer.testing import CliRunner

from quantlab.backtest.result import QualityFlags
from quantlab.cli import _validate_one_liner, app
from quantlab.validation import metrics
from tests._validation_fixtures import make_backtest_result


def _summary() -> metrics.MetricsSummary:
    dates = pd.date_range("2020-01-31", periods=6, freq="ME")
    net_returns = pd.Series([0.01, -0.02, 0.03, 0.01, -0.01, 0.02], index=dates)
    result = make_backtest_result(net_returns=net_returns)
    return metrics.summary(result)


def test_one_liner_omits_extreme_returns_when_zero():
    line = _validate_one_liner(_summary(), QualityFlags())
    assert "extreme_returns" not in line


def test_one_liner_includes_extreme_returns_long_and_short_when_nonzero():
    qf = QualityFlags(extreme_returns=3, extreme_returns_long=2, extreme_returns_short=1)
    line = _validate_one_liner(_summary(), qf)
    assert "extreme_returns_long=2" in line
    assert "extreme_returns_short=1" in line


def test_one_liner_includes_extreme_returns_when_only_short_nonzero():
    qf = QualityFlags(extreme_returns=1, extreme_returns_long=0, extreme_returns_short=1)
    line = _validate_one_liner(_summary(), qf)
    assert "extreme_returns_long=0" in line
    assert "extreme_returns_short=1" in line


def test_one_liner_still_reports_core_metrics():
    line = _validate_one_liner(_summary(), QualityFlags())
    for token in ("net CAGR=", "Sharpe=", "Sortino=", "Calmar=", "maxDD=", "hit_rate="):
        assert token in line


# --- `quantlab validate --full` end-to-end (acceptance criterion 9) --------


def _write_platform_yaml(tmp_path):
    reports_dir = tmp_path / "reports"
    cache_dir = tmp_path / "cache"
    path = tmp_path / "platform.yaml"
    path.write_text(
        f"""
cache_dir: {cache_dir.as_posix()}
reports_dir: {reports_dir.as_posix()}
providers:
  prices: dummy
  constituents: dummy
  fundamentals: dummy
benchmark: SPY
""",
        encoding="utf-8",
    )
    return path


def test_validate_full_runs_end_to_end_on_a_fixture_result_directory(tmp_path):
    dates = pd.date_range("2015-01-31", periods=24, freq="ME")
    net_returns = pd.Series([0.01, -0.005] * 12, index=dates)
    result = make_backtest_result(net_returns=net_returns, strategy_id="momentum-cli0001")

    result_dir = tmp_path / "result"
    result.save(result_dir)

    out_dir = tmp_path / "out"
    platform_path = _write_platform_yaml(tmp_path)

    runner = CliRunner()
    invocation = runner.invoke(
        app,
        [
            "validate",
            "--result",
            str(result_dir),
            "--out",
            str(out_dir),
            "--platform",
            str(platform_path),
            "--full",
        ],
    )

    assert invocation.exit_code == 0, invocation.output
    assert "verdict:" in invocation.output
    assert (out_dir / "validation_basic.json").exists()
    assert (out_dir / "report_card.json").exists()
    assert (out_dir / "report_card.md").exists()

    payload = json.loads((out_dir / "report_card.json").read_text())
    assert payload["verdict"] in {"REJECTED", "RESEARCH_ONLY", "ELIGIBLE_FOR_PAPER"}


# --- capacity price-panel wiring (orchestrator escalation 3) ---------------


def _write_cached_price(ticker: str, cache_dir, start: str, end: str) -> None:
    """Write a warm yfinance-style per-ticker cache (raw Title-case columns
    - see YFinancePriceProvider's own on-disk format) plus its
    requested-range sidecar, so `has_sufficient_price_cache` finds it
    without any network call."""
    from quantlab.data.cache import price_cache_path, write_price_cache_meta

    dates = pd.date_range(start, end, freq="B")
    frame = pd.DataFrame(
        {
            "Open": 100.0,
            "High": 101.0,
            "Low": 99.0,
            "Close": 100.0,
            "Adj Close": 100.0,
            "Volume": 5_000_000.0,
        },
        index=dates,
    )
    path = price_cache_path(ticker, cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path)
    write_price_cache_meta(ticker, start, end, cache_dir)


def _write_platform_yaml_with_yfinance(tmp_path, cache_dir):
    reports_dir = tmp_path / "reports"
    path = tmp_path / "platform.yaml"
    path.write_text(
        f"""
cache_dir: {cache_dir.as_posix()}
reports_dir: {reports_dir.as_posix()}
providers:
  prices: yfinance
  constituents: dummy
  fundamentals: dummy
benchmark: SPY
""",
        encoding="utf-8",
    )
    return path


def _held_result(strategy_id: str, tickers: list[str]) -> object:
    from quantlab.core.types import TargetWeights

    dates = pd.date_range("2015-01-31", periods=24, freq="ME")
    net_returns = pd.Series([0.01, -0.005] * 12, index=dates)
    weight = 1.0 / len(tickers)
    holdings = {
        dates[0]: TargetWeights(
            asof=dates[0], weights=dict.fromkeys(tickers, weight), strategy_id=strategy_id
        )
    }
    return make_backtest_result(
        net_returns=net_returns,
        strategy_id=strategy_id,
        holdings_history=holdings,
        start="2015-01-01",
        end="2016-12-31",
    )


def test_validate_full_capacity_gate_uses_cached_price_panel(tmp_path, monkeypatch):
    import quantlab.data.providers.yfinance_prices as yfinance_prices_module

    def _no_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network download attempted - cache should have been used")

    monkeypatch.setattr(yfinance_prices_module, "_download_batch", _no_network)

    cache_dir = tmp_path / "cache"
    _write_cached_price("AAA", cache_dir, "2015-01-01", "2016-12-31")
    _write_cached_price("BBB", cache_dir, "2015-01-01", "2016-12-31")

    result = _held_result("momentum-capA", ["AAA", "BBB"])
    result_dir = tmp_path / "result"
    result.save(result_dir)

    out_dir = tmp_path / "out"
    platform_path = _write_platform_yaml_with_yfinance(tmp_path, cache_dir)

    runner = CliRunner()
    invocation = runner.invoke(
        app,
        [
            "validate",
            "--result",
            str(result_dir),
            "--out",
            str(out_dir),
            "--platform",
            str(platform_path),
            "--full",
        ],
    )

    assert invocation.exit_code == 0, invocation.output
    payload = json.loads((out_dir / "report_card.json").read_text())
    capacity_gate = next(g for g in payload["gates"] if g["name"] == "capacity_ceiling")
    assert "missing from the price cache" not in capacity_gate["reason"]
    assert payload["capacity"] is not None
    assert payload["capacity"]["n_tickers"] == 2


def test_validate_full_capacity_gate_names_missing_tickers(tmp_path, monkeypatch):
    import quantlab.data.providers.yfinance_prices as yfinance_prices_module

    # BBB is deliberately never cached, so the provider will try to fetch
    # it - fail that attempt (never touch the real network) exactly like
    # a genuine "not found" (e.g. a delisted/unknown ticker) would.
    def _fail(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("simulated fetch failure - no network in tests")

    monkeypatch.setattr(yfinance_prices_module, "_download_batch", _fail)

    cache_dir = tmp_path / "cache"
    _write_cached_price("AAA", cache_dir, "2015-01-01", "2016-12-31")

    result = _held_result("momentum-capB", ["AAA", "BBB"])
    result_dir = tmp_path / "result"
    result.save(result_dir)

    out_dir = tmp_path / "out"
    platform_path = _write_platform_yaml_with_yfinance(tmp_path, cache_dir)

    runner = CliRunner()
    invocation = runner.invoke(
        app,
        [
            "validate",
            "--result",
            str(result_dir),
            "--out",
            str(out_dir),
            "--platform",
            str(platform_path),
            "--full",
        ],
    )

    assert invocation.exit_code == 0, invocation.output
    payload = json.loads((out_dir / "report_card.json").read_text())
    capacity_gate = next(g for g in payload["gates"] if g["name"] == "capacity_ceiling")
    assert "BBB" in capacity_gate["reason"]


# --- verdict reachability through the real CLI (quant-gate VERDICT.md M06
# cycle-1 finding 5) - a PINNED verdict on a fixture built to earn it, not
# merely "one of three". -----------------------------------------------------

_REAL_VALIDATION_CONFIG = Path(__file__).resolve().parents[1] / "configs" / "validation.yaml"


def _strong_alternating(hi: float, lo: float, n: int = 60) -> pd.Series:
    values = [hi if i % 2 == 0 else lo for i in range(n)]
    return pd.Series(values, index=pd.date_range("2015-01-31", periods=n, freq="ME"))


def _register_eligible_background_trials(registry, family: str = "momentum") -> None:
    pairs = [(0.02, -0.02), (0.03, -0.01), (0.01, -0.03), (0.04, -0.02)]
    for i, (hi, lo) in enumerate(pairs):
        result = make_backtest_result(
            net_returns=_strong_alternating(hi, lo), strategy_id=f"{family}-bg{i:04d}"
        )
        registry.record_backtest(result, family=family)


def test_validate_full_reaches_eligible_for_paper_through_the_cli(tmp_path, monkeypatch):
    import quantlab.cli as cli_module
    import quantlab.data.providers.yfinance_prices as yfinance_prices_module
    from quantlab.core.types import TargetWeights
    from quantlab.validation.registry import TrialsRegistry

    def _no_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network download attempted - cache should have been used")

    monkeypatch.setattr(yfinance_prices_module, "_download_batch", _no_network)

    # Fake sensitivity runner (quant-gate VERDICT.md M06 cycle-1 finding 5's
    # own test requirement): a flat, comfortably-high-Sharpe surface for
    # every grid point, monkeypatched over the REAL engine-backed factory.
    strong_returns = _strong_alternating(0.05, 0.01)

    def _fake_runner_factory(_platform_config):
        def runner(_strategy_config, _params, _backtest_config):
            return SimpleNamespace(net_returns=strong_returns)

        return runner

    monkeypatch.setattr(cli_module, "_make_sensitivity_runner", _fake_runner_factory)

    cache_dir = tmp_path / "cache"
    for ticker in ("AAA", "BBB", "CCC"):
        _write_cached_price(ticker, cache_dir, "2015-01-01", "2019-12-31")

    weights = {"AAA": 1 / 3, "BBB": 1 / 3, "CCC": 1 / 3}
    holdings = {
        strong_returns.index[0]: TargetWeights(
            asof=strong_returns.index[0], weights=weights, strategy_id="momentum-e11e1b1e"
        )
    }
    result = make_backtest_result(
        net_returns=strong_returns,
        benchmark_returns=_strong_alternating(0.001, -0.001),
        strategy_id="momentum-e11e1b1e",
        holdings_history=holdings,
        start="2015-01-01",
        end="2019-12-31",
        strategy_config="configs/strategies/momentum.yaml",
    )
    result_dir = tmp_path / "result"
    result.save(result_dir)

    out_dir = tmp_path / "out"
    platform_path = _write_platform_yaml_with_yfinance(tmp_path, cache_dir)

    from quantlab.core.config import load_platform_config

    registry = TrialsRegistry(load_platform_config(platform_path).reports_dir)
    _register_eligible_background_trials(registry)

    runner = CliRunner()
    invocation = runner.invoke(
        app,
        [
            "validate",
            "--result",
            str(result_dir),
            "--out",
            str(out_dir),
            "--platform",
            str(platform_path),
            "--config",
            str(_REAL_VALIDATION_CONFIG),
            "--full",
        ],
    )

    assert invocation.exit_code == 0, invocation.output
    payload = json.loads((out_dir / "report_card.json").read_text())
    failing = [g for g in payload["gates"] if not g["passed"]]
    assert failing == [], failing
    assert payload["verdict"] == "ELIGIBLE_FOR_PAPER"


def test_validate_full_reaches_rejected_through_the_cli(tmp_path, monkeypatch):
    import quantlab.data.providers.yfinance_prices as yfinance_prices_module
    from quantlab.validation.registry import TrialsRegistry

    def _no_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network download attempted - cache should have been used")

    monkeypatch.setattr(yfinance_prices_module, "_download_batch", _no_network)

    weak_returns = _strong_alternating(0.001, -0.001)
    strong_benchmark = _strong_alternating(0.05, 0.01)
    result = make_backtest_result(
        net_returns=weak_returns,
        benchmark_returns=strong_benchmark,
        strategy_id="momentum-deadweak1",
        start="2015-01-01",
        end="2019-12-31",
    )
    result_dir = tmp_path / "result"
    result.save(result_dir)

    out_dir = tmp_path / "out"
    platform_path = _write_platform_yaml_with_yfinance(tmp_path, tmp_path / "cache")

    from quantlab.core.config import load_platform_config

    # No sibling trials at all - registers only this one headline, so N=1
    # and DSR is NaN (a hard fail) on top of the benchmark hard fail.
    TrialsRegistry(load_platform_config(platform_path).reports_dir)

    runner = CliRunner()
    invocation = runner.invoke(
        app,
        [
            "validate",
            "--result",
            str(result_dir),
            "--out",
            str(out_dir),
            "--platform",
            str(platform_path),
            "--config",
            str(_REAL_VALIDATION_CONFIG),
            "--no-sensitivity",
            "--full",
        ],
    )

    assert invocation.exit_code == 0, invocation.output
    payload = json.loads((out_dir / "report_card.json").read_text())
    assert payload["verdict"] == "REJECTED"


# --- walk-forward child rebalance-frequency mismatch (quant-gate VERDICT.md
# M06 cycle-1 addendum) -------------------------------------------------------


def test_check_child_rebalance_frequencies_raises_on_mismatch(tmp_path):
    import quantlab.cli as cli_module

    monthly = make_backtest_result(
        net_returns=pd.Series(
            [0.01] * 12, index=pd.date_range("2020-01-31", periods=12, freq="ME")
        ),
        rebalance_freq="month_end",
    )
    daily = make_backtest_result(
        net_returns=pd.Series([0.01] * 12, index=pd.date_range("2020-01-02", periods=12, freq="B")),
        rebalance_freq="daily",
    )
    dirs = [tmp_path / "momentum", tmp_path / "value"]

    with pytest.raises(ValueError, match="different rebalance frequencies"):
        cli_module._check_child_rebalance_frequencies([monthly, daily], dirs)


def test_check_child_rebalance_frequencies_passes_when_all_match(tmp_path):
    import quantlab.cli as cli_module

    a = make_backtest_result(
        net_returns=pd.Series(
            [0.01] * 12, index=pd.date_range("2020-01-31", periods=12, freq="ME")
        ),
        rebalance_freq="month_end",
    )
    b = make_backtest_result(
        net_returns=pd.Series(
            [0.02] * 12, index=pd.date_range("2020-01-31", periods=12, freq="ME")
        ),
        rebalance_freq="month_end",
    )
    dirs = [tmp_path / "momentum", tmp_path / "value"]

    cli_module._check_child_rebalance_frequencies([a, b], dirs)  # must not raise


def test_build_walk_forward_result_degrades_gracefully_on_frequency_mismatch(tmp_path):
    import quantlab.cli as cli_module
    from quantlab.validation.basic import ValidationConfig

    monthly = make_backtest_result(
        net_returns=pd.Series(
            [0.01, -0.01] * 40, index=pd.date_range("2015-01-31", periods=80, freq="ME")
        ),
        strategy_id="momentum-child01",
    )
    daily = make_backtest_result(
        net_returns=pd.Series(
            [0.001, -0.001] * 40, index=pd.date_range("2015-01-02", periods=80, freq="B")
        ),
        rebalance_freq="daily",
        strategy_id="value_composite-child01",
    )
    momentum_dir = tmp_path / "momentum"
    value_dir = tmp_path / "value"
    monthly.save(momentum_dir)
    daily.save(value_dir)

    headline = make_backtest_result(
        net_returns=pd.Series(
            [0.01, -0.005] * 40, index=pd.date_range("2015-01-31", periods=80, freq="ME")
        ),
        strategy_id="blend-headline1",
    )

    result = cli_module._build_walk_forward_result(
        headline, [momentum_dir, value_dir], ValidationConfig()
    )
    assert result is None  # degraded, not a crash, not a nonsense blend
