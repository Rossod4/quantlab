"""CLI wiring tests for `quantlab paper {run,status,journal}`."""

from __future__ import annotations

import pandas as pd
from pydantic import BaseModel, ConfigDict
from typer.testing import CliRunner

from quantlab.backtest.engine import BacktestProviders
from quantlab.cli import app
from quantlab.core.calendar import trading_days
from quantlab.core.types import TargetWeights
from quantlab.data.interfaces import (
    ConstituentsProvider,
    CorporateActionsProvider,
    FundamentalsProvider,
    PriceProvider,
)
from quantlab.data.requirements import DataRequirements
from quantlab.strategies.base import Strategy
from quantlab.strategies.registry import register_strategy


class _FakePriceProvider(PriceProvider):
    def __init__(self, panel: pd.DataFrame):
        self._panel = panel

    def get_prices(self, tickers, start, end) -> pd.DataFrame:
        return self._panel[self._panel["ticker"].isin(tickers)].copy()


class _FakeConstituentsProvider(ConstituentsProvider):
    def membership(self, asof) -> list[str]:
        return []

    def membership_history(self, start, end) -> pd.DataFrame:
        return pd.DataFrame({"tickers": [[]]}, index=pd.DatetimeIndex([start]))


class _NoOpFundamentalsProvider(FundamentalsProvider):
    def get_pit_fundamentals(self, ticker, asof) -> dict:
        return {}


class _EmptyActionsProvider(CorporateActionsProvider):
    def get_actions(self, ticker, start, end) -> pd.DataFrame:
        df = pd.DataFrame(columns=["ticker", "action_type", "value"])
        df.index = pd.DatetimeIndex([], name="date")
        return df


class _CliFixedWeightParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    weights: dict[str, float] = {}


@register_strategy("paper-cli-fixed-weight")
class _CliFixedWeightStrategy(Strategy):
    @classmethod
    def params_model(cls):
        return _CliFixedWeightParams

    def requires(self) -> DataRequirements:
        return DataRequirements()

    def generate_targets(self, ctx, date) -> TargetWeights:
        return TargetWeights(
            asof=date, weights=dict(self._params.weights), strategy_id=self.strategy_id
        )


def _price_panel() -> pd.DataFrame:
    sessions = trading_days("2023-06-01", "2024-01-20")
    return pd.DataFrame(
        {
            "ticker": ["AAA"] * len(sessions),
            "open": [100.0] * len(sessions),
            "high": [100.0] * len(sessions),
            "low": [100.0] * len(sessions),
            "close": [100.0] * len(sessions),
            "adj_close": [100.0] * len(sessions),
            "volume": [1000] * len(sessions),
        },
        index=sessions,
    )


def _write_platform_yaml(tmp_path) -> str:
    reports_dir = tmp_path / "reports"
    cache_dir = tmp_path / "cache"
    path = tmp_path / "platform.yaml"
    path.write_text(
        f"""
cache_dir: {cache_dir.as_posix()}
reports_dir: {reports_dir.as_posix()}
providers:
  prices: yfinance
  constituents: sp500_community
  fundamentals: edgar
benchmark: AAA
""",
        encoding="utf-8",
    )
    return str(path)


def _write_strategy_yaml(tmp_path) -> str:
    path = tmp_path / "strategy.yaml"
    path.write_text(
        "strategy: paper-cli-fixed-weight\nparams:\n  weights:\n    AAA: 1.0\n", encoding="utf-8"
    )
    return str(path)


def test_paper_help_lists_subcommands():
    runner = CliRunner()
    result = runner.invoke(app, ["paper", "--help"])

    assert result.exit_code == 0
    assert "run" in result.output
    assert "status" in result.output
    assert "journal" in result.output
    assert "rebaseline" in result.output


def test_paper_run_dry_run_never_calls_submit(monkeypatch, tmp_path):
    providers = BacktestProviders(
        price=_FakePriceProvider(_price_panel()),
        constituents=_FakeConstituentsProvider(),
        fundamentals=_NoOpFundamentalsProvider(),
        corporate_actions=_EmptyActionsProvider(),
        cache_dir=tmp_path / "cache",
    )
    monkeypatch.setattr(
        "quantlab.backtest.engine.build_backtest_providers", lambda _config: providers
    )

    platform_path = _write_platform_yaml(tmp_path)
    strategy_path = _write_strategy_yaml(tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "paper",
            "run",
            "--strategy",
            strategy_path,
            "--broker",
            "mock",
            "--platform",
            platform_path,
            "--dry-run",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "dry-run" in result.output
    assert "BUY" in result.output or "no orders" in result.output


def test_paper_status_and_journal_on_an_empty_journal(tmp_path):
    platform_path = _write_platform_yaml(tmp_path)
    strategy_path = _write_strategy_yaml(tmp_path)
    runner = CliRunner()

    status_result = runner.invoke(
        app, ["paper", "status", "--strategy", strategy_path, "--platform", platform_path]
    )
    journal_result = runner.invoke(
        app, ["paper", "journal", "--strategy", strategy_path, "--platform", platform_path]
    )

    assert status_result.exit_code == 0
    assert "no journal entries yet" in status_result.output
    assert journal_result.exit_code == 0
    assert "no journal entries yet" in journal_result.output


def test_paper_rebaseline_writes_a_loud_journal_record(monkeypatch, tmp_path):
    providers = BacktestProviders(
        price=_FakePriceProvider(_price_panel()),
        constituents=_FakeConstituentsProvider(),
        fundamentals=_NoOpFundamentalsProvider(),
        corporate_actions=_EmptyActionsProvider(),
        cache_dir=tmp_path / "cache",
    )
    monkeypatch.setattr("quantlab.paper.runner.build_backtest_providers", lambda _config: providers)

    platform_path = _write_platform_yaml(tmp_path)
    strategy_path = _write_strategy_yaml(tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "paper",
            "rebaseline",
            "--strategy",
            strategy_path,
            "--broker",
            "mock",
            "--platform",
            platform_path,
            "--reason",
            "test rebaseline",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "re-baselined" in result.output
    assert "test rebaseline" in result.output

    from quantlab.core.config import load_platform_config
    from quantlab.paper.journal import read_journal
    from quantlab.strategies.registry import load_strategy

    platform_config = load_platform_config(platform_path)
    strategy_id = load_strategy(strategy_path).strategy_id
    records = read_journal(platform_config.reports_dir, strategy_id)
    assert len(records) == 1
    assert records[0]["kind"] == "rebaseline"
    assert "test rebaseline" in records[0]["known_caveats"][0]
