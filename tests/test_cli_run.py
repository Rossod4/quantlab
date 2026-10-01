"""Unit tests for the `quantlab run` CLI command (M09 work packet): one
command chains backtest -> validate --full -> report into one directory,
with an exit code reflecting the verdict.

The end-to-end fixture uses a trivial, deterministically-registered test
strategy (mirrors tests/test_engine.py's own `_EqualWeightStrategy` pattern)
run through the REAL `build_backtest_providers` path (real provider
classes, warm offline caches - no network) rather than a hand-built
`BacktestResult`, so this test exercises the actual CLI wiring: config
loading, the engine, validate --full, the trials registry, and
`quantlab report`'s rendering, all through one command."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from pydantic import BaseModel, ConfigDict
from typer.testing import CliRunner

import quantlab.data.corporate_actions as corporate_actions_module
from quantlab.cli import _VERDICT_EXIT_CODES, app
from quantlab.core.types import TargetWeights
from quantlab.data.cache import write_cache, write_price_cache_meta
from quantlab.data.providers.sp500_constituents import CACHE_FILENAME as _SP500_CACHE_FILENAME
from quantlab.strategies.base import Strategy
from quantlab.strategies.registry import register_strategy

runner = CliRunner()


# --- exit-code mapping (pure, no engine run needed) -------------------------


def test_verdict_exit_codes_match_the_packets_own_convention():
    assert _VERDICT_EXIT_CODES == {
        "ELIGIBLE_FOR_PAPER": 0,
        "RESEARCH_ONLY": 2,
        "REJECTED": 3,
    }


# --- end-to-end fixture ------------------------------------------------------


class _CliRunEqualWeightParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


@register_strategy("cli-run-test-equal-weight")
class _CliRunEqualWeightStrategy(Strategy):
    """Equal-weights the whole point-in-time universe - deliberately trivial
    so this test exercises the CLI/engine/validation/reporting WIRING, not a
    real signal (mirrors tests/test_engine.py's own fixture strategy)."""

    @classmethod
    def params_model(cls) -> type[BaseModel]:
        return _CliRunEqualWeightParams

    def requires(self):
        from quantlab.data.requirements import DataRequirements

        return DataRequirements(price_lookback_days=1, needs_universe=True)

    def generate_targets(self, ctx: Any, date: pd.Timestamp) -> TargetWeights:
        universe = ctx.universe()
        weights = dict.fromkeys(universe, 1.0 / len(universe)) if universe else {}
        return TargetWeights(asof=date, weights=weights, strategy_id=self.strategy_id)


@register_strategy("cli-run-test-fixed-second")
class _CliRunFixedSecondStrategy(Strategy):
    """A second, distinguishable registered strategy - used to prove
    `quantlab run --strategy` actually overrides the backtest config's own
    `strategy_config` rather than being silently ignored."""

    @classmethod
    def params_model(cls) -> type[BaseModel]:
        return _CliRunEqualWeightParams

    def requires(self):
        from quantlab.data.requirements import DataRequirements

        return DataRequirements(price_lookback_days=1, needs_universe=True)

    def generate_targets(self, ctx: Any, date: pd.Timestamp) -> TargetWeights:
        universe = ctx.universe()
        weights = dict.fromkeys(universe, 1.0 / len(universe)) if universe else {}
        return TargetWeights(asof=date, weights=weights, strategy_id=self.strategy_id)


def _fake_no_actions(ticker: str) -> pd.DataFrame:
    empty = pd.DataFrame(columns=["ticker", "action_type", "value"])
    empty.index = pd.DatetimeIndex([], name="date")
    return empty


def _write_warm_prices(cache_dir: Path, ticker: str, dates: pd.DatetimeIndex, seed: int) -> None:
    import numpy as np

    rng = np.random.default_rng(seed)
    returns = rng.normal(loc=0.0005, scale=0.01, size=len(dates))
    # `.to_numpy()`: a plain Series built from `returns` carries a default
    # RangeIndex, and building the DataFrame below with a DIFFERENT
    # (DatetimeIndex) index would silently ALIGN it - every row NaN, since
    # no RangeIndex label matches any date label.
    closes = (100.0 * (1.0 + pd.Series(returns)).cumprod()).to_numpy()
    frame = pd.DataFrame(
        {
            "Open": closes,
            "High": closes * 1.001,
            "Low": closes * 0.999,
            "Close": closes,
            "Adj Close": closes,
            "Volume": 1_000_000.0,
        },
        index=dates,
    )
    from quantlab.data.cache import price_cache_path

    path = price_cache_path(ticker, cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path)
    write_price_cache_meta(ticker, dates[0], dates[-1], cache_dir)


def _write_platform_yaml(tmp_path: Path, cache_dir: Path, reports_dir: Path) -> Path:
    path = tmp_path / "platform.yaml"
    path.write_text(
        f"""
cache_dir: {cache_dir.as_posix()}
reports_dir: {reports_dir.as_posix()}
providers:
  prices: yfinance
  constituents: sp500_community
  fundamentals: edgar
benchmark: SPY
""",
        encoding="utf-8",
    )
    return path


def _write_strategy_yaml(tmp_path: Path, name: str, filename: str = "strategy.yaml") -> Path:
    path = tmp_path / filename
    path.write_text(f"strategy: {name}\nparams: {{}}\n", encoding="utf-8")
    return path


def _write_backtest_yaml(tmp_path: Path, strategy_path: Path, start: str, end: str) -> Path:
    path = tmp_path / "backtest.yaml"
    path.write_text(
        f"""
start: {start}
end: {end}
strategy_config: {strategy_path.resolve().as_posix()}
rebalance_freq: month_end
execution: close
cost_model: flat_bps
one_way_cost_bps: 10.0
""",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def _cli_run_fixture(tmp_path, monkeypatch):
    from quantlab.core.calendar import trading_days

    cache_dir = tmp_path / "cache"
    reports_dir = tmp_path / "reports"
    # Real NYSE trading SESSIONS (not a plain business-day range): the
    # engine's own windowing (`PITDataContext._sliced_price_panel`) slices
    # against `core.calendar.trading_days`, and a synthetic panel built on a
    # different day-of-week convention leaves gaps that surface as NaN fill
    # prices at a rebalance date. Starts well before, and ends well after,
    # the backtest's own 2015-01-01..2016-12-31 window: `backtest/engine.py`'s
    # `PricePanelStore` warms up `_LAST_PRICE_SEARCH_LOOKBACK_DAYS=400`
    # trading sessions BEFORE `config.start` (the forced-exit search window)
    # and pads 10 CALENDAR days past `config.end` - a warm cache not
    # covering both ends would make `has_sufficient_price_cache` judge the
    # cache insufficient and fall back to a real, network-touching
    # `_download_batch` call for the gap.
    dates = trading_days("2012-01-01", "2017-02-15")
    for i, ticker in enumerate(["AAA", "BBB", "SPY"]):
        _write_warm_prices(cache_dir, ticker, dates, seed=i)
    table = pd.DataFrame({"tickers": [["AAA", "BBB"]]}, index=pd.DatetimeIndex(["2010-01-01"]))
    write_cache(table, cache_dir / _SP500_CACHE_FILENAME)
    write_cache(pd.DataFrame(columns=["ticker", "cik"]), cache_dir / "sec_ticker_cik_map.parquet")
    monkeypatch.setattr(corporate_actions_module, "_download_actions", _fake_no_actions)

    platform_path = _write_platform_yaml(tmp_path, cache_dir, reports_dir)
    strategy_path = _write_strategy_yaml(tmp_path, "cli-run-test-equal-weight")
    backtest_path = _write_backtest_yaml(tmp_path, strategy_path, "2015-01-01", "2016-12-31")
    return {
        "tmp_path": tmp_path,
        "platform_path": platform_path,
        "strategy_path": strategy_path,
        "backtest_path": backtest_path,
        "reports_dir": reports_dir,
    }


def test_run_help_works():
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    assert "--backtest" in result.output
    assert "--strategy" in result.output
    assert "--out" in result.output


@pytest.mark.slow  # M09 packet item 13: full backtest+validate+report fixture pipeline
def test_run_end_to_end_writes_all_three_artefacts_and_matching_exit_code(_cli_run_fixture):
    import json

    fx = _cli_run_fixture
    out_dir = fx["tmp_path"] / "out"

    invocation = runner.invoke(
        app,
        [
            "run",
            "--backtest",
            str(fx["backtest_path"]),
            "--out",
            str(out_dir),
            "--platform",
            str(fx["platform_path"]),
        ],
    )

    assert invocation.output  # non-empty regardless of outcome, for debugging
    assert (out_dir / "net_returns.parquet").exists()
    assert (out_dir / "provenance.json").exists()
    assert (out_dir / "validation_basic.json").exists()
    assert (out_dir / "report_card.json").exists()
    assert (out_dir / "report_card.md").exists()
    assert (out_dir / "report.html").exists()
    assert (out_dir / "report.md").exists()

    payload = json.loads((out_dir / "report_card.json").read_text())
    verdict = payload["verdict"]
    assert verdict in _VERDICT_EXIT_CODES
    assert invocation.exit_code == _VERDICT_EXIT_CODES[verdict], invocation.output
    assert f"verdict: {verdict}" in invocation.output

    # The trials registry was updated by this run (acceptance criterion:
    # "the trials registry updated").
    assert (fx["reports_dir"] / "trials" / "trials.jsonl").exists()


@pytest.mark.slow  # M09 packet item 13: full backtest+validate+report fixture pipeline
def test_run_strategy_override_replaces_the_backtest_configs_own_strategy(_cli_run_fixture):
    import json

    fx = _cli_run_fixture
    override_strategy_path = _write_strategy_yaml(
        fx["tmp_path"], "cli-run-test-fixed-second", filename="override.yaml"
    )
    out_dir = fx["tmp_path"] / "out_override"

    runner.invoke(
        app,
        [
            "run",
            "--backtest",
            str(fx["backtest_path"]),
            "--strategy",
            str(override_strategy_path),
            "--out",
            str(out_dir),
            "--platform",
            str(fx["platform_path"]),
        ],
    )

    provenance = json.loads((out_dir / "provenance.json").read_text())
    assert provenance["strategy_id"].startswith("cli-run-test-fixed-second-")
    assert provenance["backtest_config"]["strategy_config"] == str(override_strategy_path.resolve())
