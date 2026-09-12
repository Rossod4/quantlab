"""Tests for `paper/runner.py`. Fakes mirror tests/test_engine.py's own
(no network, offline, deterministic - CLAUDE.md invariant #5).
`build_backtest_providers` is monkeypatched to return a fixed
`BacktestProviders` built from fakes, exactly like tests/test_engine.py
constructs one directly rather than exercising the real vendor providers."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from pydantic import BaseModel, ConfigDict

from quantlab.backtest.context import DecisionProviders, build_decision_context
from quantlab.backtest.engine import BacktestProviders
from quantlab.core.calendar import trading_days
from quantlab.core.config import PlatformConfig, ProvidersConfig
from quantlab.core.errors import (
    ActionsFetchError,
    BacktestAbortError,
    PromotionGateError,
    StaleActionsCacheError,
)
from quantlab.core.errors import ReconcileError as ReconcileErrorType
from quantlab.core.semantics import DATA_SEMANTICS_VERSION
from quantlab.core.types import Position, TargetWeights
from quantlab.data.interfaces import (
    ConstituentsProvider,
    CorporateActionsProvider,
    FundamentalsProvider,
    PriceProvider,
)
from quantlab.data.requirements import DataRequirements
from quantlab.paper.broker import BrokerCapabilities
from quantlab.paper.journal import JournalRecord, append_journal, read_journal
from quantlab.paper.mock import MockBroker
from quantlab.paper.runner import (
    PaperRunConfig,
    _generate_targets_with_actions_refresh,
    accept_broker_state,
    run_once,
)
from quantlab.strategies.base import Strategy
from quantlab.strategies.registry import register_strategy

# -- fakes --------------------------------------------------------------------


class _FakePriceProvider(PriceProvider):
    def __init__(self, panel: pd.DataFrame):
        self._panel = panel

    def get_prices(self, tickers: list[str], start: object, end: object) -> pd.DataFrame:
        return self._panel[self._panel["ticker"].isin(tickers)].copy()


class _FakeConstituentsProvider(ConstituentsProvider):
    def __init__(self, tickers: list[str]):
        self._tickers = tickers

    def membership(self, asof: object) -> list[str]:
        return list(self._tickers)

    def membership_history(self, start: object, end: object) -> pd.DataFrame:
        return pd.DataFrame({"tickers": [list(self._tickers)]}, index=pd.DatetimeIndex([start]))


class _NoOpFundamentalsProvider(FundamentalsProvider):
    def get_pit_fundamentals(self, ticker: str, asof: object) -> dict:
        return {}


def _empty_actions() -> pd.DataFrame:
    df = pd.DataFrame(columns=["ticker", "action_type", "value"])
    df.index = pd.DatetimeIndex([], name="date")
    return df


class _EmptyActionsProvider(CorporateActionsProvider):
    def get_actions(self, ticker: str, start: object, end: object) -> pd.DataFrame:
        return _empty_actions()


class _ActionsHistoryProvider(CorporateActionsProvider):
    """A real (bounded, filterable) per-ticker actions history, plus a set
    of tickers whose `get_actions` always raises `StaleActionsCacheError` -
    the fixture for both finding 1 (dividend/split reconcile roll-forward)
    and finding 2 (per-ticker data-degradation drops)."""

    def __init__(
        self,
        actions_by_ticker: dict[str, pd.DataFrame] | None = None,
        failing_tickers: set[str] | None = None,
    ):
        self._actions = actions_by_ticker or {}
        self._failing = failing_tickers or set()

    def get_actions(self, ticker: str, start: object, end: object) -> pd.DataFrame:
        if ticker in self._failing:
            raise StaleActionsCacheError(f"{ticker}: forced failure for testing")
        df = self._actions.get(ticker)
        if df is None or df.empty:
            return _empty_actions()
        start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
        return df.loc[(df.index >= start_ts) & (df.index <= end_ts)].copy()


def _price_panel(tickers_and_prices: dict[str, float]) -> pd.DataFrame:
    sessions = trading_days("2023-06-01", "2024-01-20")
    if not tickers_and_prices:
        empty = pd.DataFrame(
            columns=["ticker", "open", "high", "low", "close", "adj_close", "volume"]
        )
        empty.index = pd.DatetimeIndex([], name="date")
        return empty
    frames = []
    for ticker, price in tickers_and_prices.items():
        frames.append(
            pd.DataFrame(
                {
                    "ticker": [ticker] * len(sessions),
                    "open": [price] * len(sessions),
                    "high": [price] * len(sessions),
                    "low": [price] * len(sessions),
                    "close": [price] * len(sessions),
                    "adj_close": [price] * len(sessions),
                    "volume": [1000] * len(sessions),
                },
                index=sessions,
            )
        )
    return pd.concat(frames).sort_index()


class _FixedWeightParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    weights: dict[str, float] = {}


@register_strategy("paper-runner-fixed-weight")
class _FixedWeightStrategy(Strategy):
    """Ignores `ctx` entirely - just returns `params.weights` - exactly
    enough to exercise the runner's own orchestration without needing any
    real signal logic."""

    @classmethod
    def params_model(cls) -> type[BaseModel]:
        return _FixedWeightParams

    def requires(self) -> DataRequirements:
        return DataRequirements()

    def generate_targets(self, ctx, date) -> TargetWeights:
        return TargetWeights(
            asof=date, weights=dict(self._params.weights), strategy_id=self.strategy_id
        )


@register_strategy("paper-runner-actions-probe")
class _ActionsProbeStrategy(Strategy):
    """Declares `needs_universe`/`needs_actions` and actually calls both
    accessors, so a hostile `CorporateActionsProvider` can trigger
    `StaleActionsCacheError` from inside `generate_targets` - the fixture
    for the actions-cache refresh policy test."""

    @classmethod
    def params_model(cls) -> type[BaseModel]:
        return _FixedWeightParams

    def requires(self) -> DataRequirements:
        return DataRequirements(needs_universe=True, needs_actions=True)

    def generate_targets(self, ctx, date) -> TargetWeights:
        tickers = ctx.universe()
        for ticker in tickers:
            ctx.actions(ticker)
        weights = dict.fromkeys(tickers, 1.0 / len(tickers)) if tickers else {}
        return TargetWeights(asof=date, weights=weights, strategy_id=self.strategy_id)


@register_strategy("paper-runner-equal-weight-universe")
class _EqualWeightUniverseStrategy(Strategy):
    """Equal-weights whatever `ctx.universe()` hands back - declares
    `needs_universe=True` alongside a nonzero `price_lookback_days`, so
    `build_decision_context` wraps `constituents` in the SAME per-ticker
    filtering `backtest/engine.py` uses (quant-gate VERDICT.md M08 cycle-1
    finding 2's own reproduction condition:
    `strategies/momentum.py:200-208`'s exact declaration shape)."""

    @classmethod
    def params_model(cls) -> type[BaseModel]:
        return _FixedWeightParams

    def requires(self) -> DataRequirements:
        return DataRequirements(needs_universe=True, price_lookback_days=1)

    def generate_targets(self, ctx, date) -> TargetWeights:
        tickers = ctx.universe()
        weights = dict.fromkeys(tickers, 1.0 / len(tickers)) if tickers else {}
        return TargetWeights(asof=date, weights=weights, strategy_id=self.strategy_id)


class _UnscoreableParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    should_raise: bool = True


@register_strategy("paper-runner-unscoreable")
class _UnscoreableStrategy(Strategy):
    """Raises `ValueError` unconditionally when `params.should_raise` - the
    fixture for `PaperRunConfig.abort_on_unscoreable`."""

    @classmethod
    def params_model(cls) -> type[BaseModel]:
        return _UnscoreableParams

    def requires(self) -> DataRequirements:
        return DataRequirements()

    def generate_targets(self, ctx, date) -> TargetWeights:
        if self._params.should_raise:
            raise ValueError("disjoint books guard: universe too thin to score")
        return TargetWeights(asof=date, weights={}, strategy_id=self.strategy_id)


class _OverreachParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


@register_strategy("paper-runner-blend-overreach-child")
class _RunnerOverreachChildStrategy(Strategy):
    """Declares `price_lookback_days=1` but actually asks for 5 - the
    fixture for finding 5 (blend per-child context guard)."""

    @classmethod
    def params_model(cls) -> type[BaseModel]:
        return _OverreachParams

    def requires(self) -> DataRequirements:
        return DataRequirements(price_lookback_days=1)

    def generate_targets(self, ctx, date) -> TargetWeights:
        ctx.prices(["AAA"], 5)  # deliberately over-reaches its own declared 1
        return TargetWeights(asof=date, weights={}, strategy_id=self.strategy_id)


@register_strategy("paper-runner-unscored-reporter")
class _UnscoredReportingStrategy(Strategy):
    """Always reports `BBB` as unscored - the fixture for verifying
    `TargetWeights.unscored` reaches the journal (finding 2)."""

    @classmethod
    def params_model(cls) -> type[BaseModel]:
        return _OverreachParams

    def requires(self) -> DataRequirements:
        return DataRequirements()

    def generate_targets(self, ctx, date) -> TargetWeights:
        return TargetWeights(
            asof=date,
            weights={"AAA": 1.0},
            strategy_id=self.strategy_id,
            unscored={"BBB": "missing lookback price"},
        )


@register_strategy("paper-runner-blend-declare-only-child")
class _RunnerDeclareOnlyChildStrategy(Strategy):
    """A companion child declaring a BIGGER lookback than the overreaching
    child - its union with the overreaching child's own declaration is what
    would silently mask the bug if the blend fell back to a shared context."""

    @classmethod
    def params_model(cls) -> type[BaseModel]:
        return _OverreachParams

    def requires(self) -> DataRequirements:
        return DataRequirements(price_lookback_days=10)

    def generate_targets(self, ctx, date) -> TargetWeights:
        return TargetWeights(asof=date, weights={}, strategy_id=self.strategy_id)


def _platform_config(tmp_path) -> PlatformConfig:
    return PlatformConfig(
        cache_dir=tmp_path / "cache",
        reports_dir=tmp_path / "reports",
        providers=ProvidersConfig(
            prices="yfinance", constituents="sp500_community", fundamentals="edgar"
        ),
        benchmark="BENCH",
    )


def _write_report_card(reports_dir, strategy_id: str, verdict: str) -> None:
    out = reports_dir / "validate" / strategy_id
    out.mkdir(parents=True, exist_ok=True)
    data = {
        "verdict": verdict,
        "provenance": {
            "strategy_id": strategy_id,
            "data_semantics_version": DATA_SEMANTICS_VERSION,
        },
        "known_caveats": ["some caveat from the promoting report card"],
    }
    (out / "report_card.json").write_text(json.dumps(data))


@pytest.fixture(autouse=True)
def _fixed_today(monkeypatch):
    """Every test in this file runs as-of a fixed "today" so `resolve_asof`'s
    default is deterministic (CLAUDE.md invariant #5)."""
    monkeypatch.setattr("quantlab.paper.runner._today", lambda: pd.Timestamp("2024-01-16"))


@pytest.fixture(autouse=True)
def _no_real_actions_refresh(monkeypatch):
    """`run_once`'s new PROACTIVE actions-cache refresh (quant-gate
    VERDICT.2.md M08 cycle-2 finding 1) reads real `fetched_at` sidecar
    files from `platform_config.cache_dir` - none of THIS file's fixtures
    ever write one, so every `needs_universe=True` strategy (or a broker
    holding any position) looks "stale" to it on every test. Without this
    fixture that would call the REAL `refresh_actions_cache` - a live
    network attempt - on nearly every test in this file, violating CLAUDE.md
    invariant #5 (offline, deterministic tests) and making the suite slow.
    Default to a safe no-op spy; a test that specifically exercises refresh
    behavior re-monkeypatches this same name in its own body, which simply
    overrides this default for that test."""
    monkeypatch.setattr(
        "quantlab.paper.runner.refresh_actions_cache", lambda ticker, cache_dir: None
    )


def _fake_providers(
    prices: dict[str, float], tmp_path, tickers_for_universe: list[str] | None = None
):
    return BacktestProviders(
        price=_FakePriceProvider(_price_panel(prices)),
        constituents=_FakeConstituentsProvider(tickers_for_universe or []),
        fundamentals=_NoOpFundamentalsProvider(),
        corporate_actions=_EmptyActionsProvider(),
        cache_dir=tmp_path / "cache",
    )


def _mock_broker(prices: dict[str, float], cash: float = 100_000.0) -> MockBroker:
    return MockBroker(
        capabilities_=BrokerCapabilities(
            fractional_shares=True, shorting=False, extended_hours=False
        ),
        prices=prices,
        cash=cash,
        asof="2024-01-12",
    )


def _context_factory_for(
    providers: BacktestProviders, asof: pd.Timestamp, max_dropped_fraction=0.05
):
    """Mirrors `run_once`'s own `context_factory` closure, for tests that
    exercise `_generate_targets_with_actions_refresh` or the shared
    `build_decision_context` path directly without going through the full
    `run_once`."""
    decision_providers = DecisionProviders(
        price=providers.price,
        constituents=providers.constituents,
        fundamentals=providers.fundamentals,
        corporate_actions=providers.corporate_actions,
    )

    def _factory(reqs: DataRequirements):
        return build_decision_context(
            asof=asof,
            requirements=reqs,
            providers=decision_providers,
            max_dropped_fraction=max_dropped_fraction,
            on_drop=lambda ticker, exc: None,
        )

    return _factory


def test_two_consecutive_runs_the_second_leaves_the_account_unchanged(monkeypatch, tmp_path):
    platform_config = _platform_config(tmp_path)
    strategy_config = {"strategy": "paper-runner-fixed-weight", "params": {"weights": {"AAA": 1.0}}}
    from quantlab.strategies.registry import load_strategy

    strategy_id = load_strategy(strategy_config).strategy_id
    _write_report_card(platform_config.reports_dir, strategy_id, "ELIGIBLE_FOR_PAPER")

    providers = _fake_providers({"AAA": 100.0, "BENCH": 50.0}, tmp_path)
    monkeypatch.setattr("quantlab.paper.runner.build_backtest_providers", lambda _: providers)

    broker = _mock_broker({"AAA": 100.0})

    record1 = run_once(strategy_config, platform_config, broker)
    account_after_1 = broker.account()
    record2 = run_once(strategy_config, platform_config, broker)
    account_after_2 = broker.account()

    assert record1.refused_reason is None
    assert record2.refused_reason is None
    assert account_after_1.cash == account_after_2.cash
    assert account_after_1.equity == account_after_2.equity
    assert account_after_1.positions.keys() == account_after_2.positions.keys()
    for ticker, pos in account_after_1.positions.items():
        assert pos.qty == account_after_2.positions[ticker].qty


def test_planted_mismatch_refuses_to_trade(monkeypatch, tmp_path):
    platform_config = _platform_config(tmp_path)
    strategy_config = {"strategy": "paper-runner-fixed-weight", "params": {"weights": {"AAA": 1.0}}}
    from quantlab.strategies.registry import load_strategy

    strategy_id = load_strategy(strategy_config).strategy_id
    _write_report_card(platform_config.reports_dir, strategy_id, "ELIGIBLE_FOR_PAPER")

    providers = _fake_providers({"AAA": 100.0, "BENCH": 50.0}, tmp_path)
    monkeypatch.setattr("quantlab.paper.runner.build_backtest_providers", lambda _: providers)

    broker = _mock_broker({"AAA": 100.0})
    run_once(strategy_config, platform_config, broker)

    # Plant an external interference: someone manually changed the paper
    # account's cash outside this platform.
    broker.cash += 5_000.0

    with pytest.raises(ReconcileErrorType):
        run_once(strategy_config, platform_config, broker)

    records = read_journal(platform_config.reports_dir, strategy_id)
    assert records[-1]["refused_reason"] is not None
    assert records[-1]["planned_orders"] == []


def test_promotion_gate_refuses_a_rejected_strategy(monkeypatch, tmp_path):
    platform_config = _platform_config(tmp_path)
    strategy_config = {"strategy": "paper-runner-fixed-weight", "params": {"weights": {"AAA": 1.0}}}
    from quantlab.strategies.registry import load_strategy

    strategy_id = load_strategy(strategy_config).strategy_id
    _write_report_card(platform_config.reports_dir, strategy_id, "REJECTED")

    providers = _fake_providers({"AAA": 100.0, "BENCH": 50.0}, tmp_path)
    monkeypatch.setattr("quantlab.paper.runner.build_backtest_providers", lambda _: providers)

    broker = _mock_broker({"AAA": 100.0})

    with pytest.raises(PromotionGateError):
        run_once(strategy_config, platform_config, broker)

    records = read_journal(platform_config.reports_dir, strategy_id)
    assert len(records) == 1
    assert records[0]["refused_reason"] is not None
    assert records[0]["planned_orders"] == []


def test_promotion_gate_refuses_when_no_report_card_exists_at_all(monkeypatch, tmp_path):
    platform_config = _platform_config(tmp_path)
    strategy_config = {"strategy": "paper-runner-fixed-weight", "params": {"weights": {"AAA": 1.0}}}

    providers = _fake_providers({"AAA": 100.0, "BENCH": 50.0}, tmp_path)
    monkeypatch.setattr("quantlab.paper.runner.build_backtest_providers", lambda _: providers)

    broker = _mock_broker({"AAA": 100.0})

    with pytest.raises(PromotionGateError):
        run_once(strategy_config, platform_config, broker)


def test_force_research_bypasses_the_gate_and_flags_the_journal(monkeypatch, tmp_path):
    platform_config = _platform_config(tmp_path)
    strategy_config = {"strategy": "paper-runner-fixed-weight", "params": {"weights": {"AAA": 1.0}}}
    from quantlab.strategies.registry import load_strategy

    strategy_id = load_strategy(strategy_config).strategy_id
    # Deliberately NO report card at all.

    providers = _fake_providers({"AAA": 100.0, "BENCH": 50.0}, tmp_path)
    monkeypatch.setattr("quantlab.paper.runner.build_backtest_providers", lambda _: providers)

    broker = _mock_broker({"AAA": 100.0})

    record = run_once(strategy_config, platform_config, broker, force_research=True)

    assert record.refused_reason is None
    assert record.force_research is True
    assert any("FORCE-RESEARCH" in c for c in record.known_caveats)

    records = read_journal(platform_config.reports_dir, strategy_id)
    assert records[-1]["force_research"] is True


def test_resolve_asof_clamps_to_the_price_caches_actual_last_bar(tmp_path):
    """A provider that HONESTLY respects the requested [start, end] window
    (unlike `_FakePriceProvider` above, which ignores it) - here, one whose
    cache genuinely lags three sessions behind `today`."""
    from quantlab.paper.runner import resolve_asof

    class _LaggingPriceProvider(PriceProvider):
        def __init__(self, panel: pd.DataFrame, cutoff: pd.Timestamp):
            self._panel = panel
            self._cutoff = cutoff

        def get_prices(self, tickers, start, end) -> pd.DataFrame:
            sub = self._panel[self._panel["ticker"].isin(tickers)]
            return sub.loc[sub.index <= min(pd.Timestamp(end), self._cutoff)]

    today = pd.Timestamp("2024-01-16")
    cutoff = pd.Timestamp("2024-01-08")  # well behind today's safety ceiling (2024-01-12)
    providers = BacktestProviders(
        price=_LaggingPriceProvider(_price_panel({"BENCH": 50.0}), cutoff),
        constituents=_FakeConstituentsProvider([]),
        fundamentals=_NoOpFundamentalsProvider(),
        corporate_actions=_EmptyActionsProvider(),
        cache_dir=tmp_path / "cache",
    )

    effective = resolve_asof(today, None, providers, "BENCH")

    assert effective <= cutoff


def test_stale_actions_cache_triggers_a_universe_wide_refresh_and_retries(monkeypatch, tmp_path):
    refreshed_tickers: list[str] = []

    def _fake_refresh_actions_cache(ticker: str, cache_dir) -> None:
        refreshed_tickers.append(ticker)

    monkeypatch.setattr("quantlab.paper.runner.refresh_actions_cache", _fake_refresh_actions_cache)

    class _StaleOnceActionsProvider(CorporateActionsProvider):
        def get_actions(self, ticker: str, start: object, end: object) -> pd.DataFrame:
            if ticker not in refreshed_tickers:
                raise StaleActionsCacheError(f"{ticker}: forced stale for testing")
            return _empty_actions()

    providers = BacktestProviders(
        price=_FakePriceProvider(_price_panel({})),
        constituents=_FakeConstituentsProvider(["AAA"]),
        fundamentals=_NoOpFundamentalsProvider(),
        corporate_actions=_StaleOnceActionsProvider(),
        cache_dir=tmp_path / "cache",
    )
    strategy_config = {"strategy": "paper-runner-actions-probe", "params": {}}
    from quantlab.strategies.registry import load_strategy

    strategy = load_strategy(strategy_config)

    targets, refreshed = _generate_targets_with_actions_refresh(
        strategy,
        _context_factory_for(providers, pd.Timestamp("2024-01-12")),
        providers,
        pd.Timestamp("2024-01-12"),
        tmp_path / "cache",
    )

    assert refreshed == ["AAA"]
    assert targets.weights == {"AAA": 1.0}


def test_a_second_stale_actions_failure_after_the_retry_propagates_uncaught_and_is_journaled(
    monkeypatch, tmp_path
):
    """The refresh policy (proactive pre-check PLUS a reactive
    catch-and-retry second line - runner.py's module docstring) exists to
    clear ORDINARY schedule staleness, not to paper over a persistently
    broken actions cache/provider - a provider that ALWAYS raises
    `StaleActionsCacheError`, surviving both the proactive attempt and the
    one reactive retry, must propagate uncaught from `run_once` (never
    loop, never silently swallow it), and the refusal must still be
    journaled first, naming the error class, before it propagates."""

    class _AlwaysStaleActionsProvider(CorporateActionsProvider):
        def get_actions(self, ticker: str, start: object, end: object) -> pd.DataFrame:
            raise StaleActionsCacheError(f"{ticker}: permanently stale for testing")

    refresh_calls: list[str] = []
    monkeypatch.setattr(
        "quantlab.paper.runner.refresh_actions_cache",
        lambda ticker, cache_dir: refresh_calls.append(ticker),
    )

    providers = BacktestProviders(
        price=_FakePriceProvider(_price_panel({})),
        constituents=_FakeConstituentsProvider(["AAA"]),
        fundamentals=_NoOpFundamentalsProvider(),
        corporate_actions=_AlwaysStaleActionsProvider(),
        cache_dir=tmp_path / "cache",
    )
    monkeypatch.setattr("quantlab.paper.runner.build_backtest_providers", lambda _config: providers)

    platform_config = _platform_config(tmp_path)
    strategy_config = {"strategy": "paper-runner-actions-probe", "params": {}}
    from quantlab.strategies.registry import load_strategy

    strategy_id = load_strategy(strategy_config).strategy_id
    _write_report_card(platform_config.reports_dir, strategy_id, "ELIGIBLE_FOR_PAPER")

    broker = _mock_broker({"AAA": 100.0})

    with pytest.raises(StaleActionsCacheError):
        run_once(strategy_config, platform_config, broker)

    # Attempted exactly once by the proactive pre-check and once more by
    # the reactive retry (not a loop) before giving up.
    assert refresh_calls == ["AAA", "AAA"]

    records = read_journal(platform_config.reports_dir, strategy_id)
    assert len(records) == 1
    assert records[0]["planned_orders"] == []
    assert records[0]["refused_reason"] is not None
    assert "StaleActionsCacheError" in records[0]["refused_reason"]


# -- quant-gate VERDICT.md M08 cycle-1 finding 2: shared decision context --
# -- and its two data-degradation guards -----------------------------------


def _many_tickers(n: int) -> list[str]:
    return [f"T{i:03d}" for i in range(n)]


def test_one_unclearable_ticker_below_threshold_drops_and_continues_trading(monkeypatch, tmp_path):
    """Reproduces the gate's own 40-name-universe probe: one ticker (2.5%,
    under the 5% default) fails its actions probe and is dropped BEFORE the
    strategy ever sees `ctx.universe()` - the strategy rebalances into the
    other 39 at 1/39 each, matching the engine's own behavior exactly, and
    the drop is journaled rather than silently absorbed."""
    tickers = _many_tickers(40)
    prices = dict.fromkeys(tickers, 100.0)
    prices["BENCH"] = 50.0
    providers = BacktestProviders(
        price=_FakePriceProvider(_price_panel(prices)),
        constituents=_FakeConstituentsProvider(tickers),
        fundamentals=_NoOpFundamentalsProvider(),
        corporate_actions=_ActionsHistoryProvider(failing_tickers={tickers[0]}),
        cache_dir=tmp_path / "cache",
    )
    monkeypatch.setattr("quantlab.paper.runner.build_backtest_providers", lambda _config: providers)

    platform_config = _platform_config(tmp_path)
    strategy_config = {"strategy": "paper-runner-equal-weight-universe", "params": {}}
    from quantlab.strategies.registry import load_strategy

    strategy_id = load_strategy(strategy_config).strategy_id
    _write_report_card(platform_config.reports_dir, strategy_id, "ELIGIBLE_FOR_PAPER")

    broker = _mock_broker(prices)

    record = run_once(strategy_config, platform_config, broker)

    assert record.refused_reason is None
    assert record.dropped_tickers == [tickers[0]]
    assert record.dropped_fraction == pytest.approx(1 / 40)
    weights = record.targets["weights"]
    assert tickers[0] not in weights
    assert len(weights) == 39
    for w in weights.values():
        assert w == pytest.approx(1 / 39)


def test_data_degradation_above_threshold_aborts_and_refuses(monkeypatch, tmp_path):
    """A half-completed data sync (25% of the universe unclearable, above
    the 5% default `max_dropped_fraction`) refuses to trade rather than
    sizing a concentrated book on whatever happened to have data - the
    engine's OWN guard, now shared by the paper path."""
    tickers = _many_tickers(40)
    failing = set(tickers[:10])
    prices = dict.fromkeys(tickers, 100.0)
    prices["BENCH"] = 50.0
    providers = BacktestProviders(
        price=_FakePriceProvider(_price_panel(prices)),
        constituents=_FakeConstituentsProvider(tickers),
        fundamentals=_NoOpFundamentalsProvider(),
        corporate_actions=_ActionsHistoryProvider(failing_tickers=failing),
        cache_dir=tmp_path / "cache",
    )
    monkeypatch.setattr("quantlab.paper.runner.build_backtest_providers", lambda _config: providers)

    platform_config = _platform_config(tmp_path)
    strategy_config = {"strategy": "paper-runner-equal-weight-universe", "params": {}}
    from quantlab.strategies.registry import load_strategy

    strategy_id = load_strategy(strategy_config).strategy_id
    _write_report_card(platform_config.reports_dir, strategy_id, "ELIGIBLE_FOR_PAPER")

    broker = _mock_broker(prices)

    with pytest.raises(BacktestAbortError):
        run_once(strategy_config, platform_config, broker)

    records = read_journal(platform_config.reports_dir, strategy_id)
    assert records[-1]["refused_reason"] is not None
    assert "data degraded" in records[-1]["refused_reason"]
    assert records[-1]["planned_orders"] == []
    assert len(records[-1]["dropped_tickers"]) == 10


def test_unscored_tickers_reach_the_journal(monkeypatch, tmp_path):
    providers = _fake_providers({"AAA": 100.0, "BENCH": 50.0}, tmp_path)
    monkeypatch.setattr("quantlab.paper.runner.build_backtest_providers", lambda _config: providers)

    platform_config = _platform_config(tmp_path)
    strategy_config = {"strategy": "paper-runner-unscored-reporter", "params": {}}
    from quantlab.strategies.registry import load_strategy

    strategy_id = load_strategy(strategy_config).strategy_id
    _write_report_card(platform_config.reports_dir, strategy_id, "ELIGIBLE_FOR_PAPER")

    broker = _mock_broker({"AAA": 100.0})
    record = run_once(strategy_config, platform_config, broker)

    assert record.refused_reason is None
    assert record.unscored_tickers == {"BBB": "missing lookback price"}


def test_abort_on_unscoreable_true_refuses_and_journals(monkeypatch, tmp_path):
    providers = _fake_providers({"AAA": 100.0, "BENCH": 50.0}, tmp_path)
    monkeypatch.setattr("quantlab.paper.runner.build_backtest_providers", lambda _config: providers)

    platform_config = _platform_config(tmp_path)
    strategy_config = {"strategy": "paper-runner-unscoreable", "params": {}}
    from quantlab.strategies.registry import load_strategy

    strategy_id = load_strategy(strategy_config).strategy_id
    _write_report_card(platform_config.reports_dir, strategy_id, "ELIGIBLE_FOR_PAPER")

    broker = _mock_broker({"AAA": 100.0})

    with pytest.raises(ValueError, match="disjoint books"):
        run_once(strategy_config, platform_config, broker)

    records = read_journal(platform_config.reports_dir, strategy_id)
    assert records[-1]["refused_reason"] is not None
    assert records[-1]["planned_orders"] == []


def test_abort_on_unscoreable_false_holds_prior_positions_without_refusing(monkeypatch, tmp_path):
    providers = _fake_providers({"AAA": 100.0, "BENCH": 50.0}, tmp_path)
    monkeypatch.setattr("quantlab.paper.runner.build_backtest_providers", lambda _config: providers)

    platform_config = _platform_config(tmp_path)
    strategy_config = {"strategy": "paper-runner-unscoreable", "params": {}}
    from quantlab.strategies.registry import load_strategy

    strategy_id = load_strategy(strategy_config).strategy_id
    _write_report_card(platform_config.reports_dir, strategy_id, "ELIGIBLE_FOR_PAPER")

    broker = _mock_broker({"AAA": 100.0})

    record = run_once(
        strategy_config,
        platform_config,
        broker,
        paper_config=PaperRunConfig(abort_on_unscoreable=False),
    )

    assert record.refused_reason is None
    assert record.planned_orders == []
    assert any("unscoreable" in c for c in record.known_caveats)


# -- quant-gate VERDICT.md M08 cycle-1 finding 3: forced exit on a -----------
# -- delisted/unpriceable holding --------------------------------------------


def test_delisted_holding_is_force_exited_journaled_and_never_crashes(monkeypatch, tmp_path):
    providers = _fake_providers({"AAA": 100.0, "BENCH": 50.0}, tmp_path)  # no "DEAD" price at all
    monkeypatch.setattr("quantlab.paper.runner.build_backtest_providers", lambda _config: providers)

    platform_config = _platform_config(tmp_path)
    strategy_config = {"strategy": "paper-runner-fixed-weight", "params": {"weights": {"AAA": 1.0}}}
    from quantlab.strategies.registry import load_strategy

    strategy_id = load_strategy(strategy_config).strategy_id
    _write_report_card(platform_config.reports_dir, strategy_id, "ELIGIBLE_FOR_PAPER")

    broker = _mock_broker({"AAA": 100.0})
    broker.positions["DEAD"] = Position(ticker="DEAD", qty=50.0, avg_cost=20.0)

    record = run_once(strategy_config, platform_config, broker)

    assert record.refused_reason is None
    assert record.forced_exits == {"DEAD": "forced exit: no price / delisted"}
    dead_orders = [o for o in record.planned_orders if o["ticker"] == "DEAD"]
    assert len(dead_orders) == 1
    assert dead_orders[0]["side"] == "SELL"
    assert dead_orders[0]["qty"] == pytest.approx(50.0)
    dead_results = [r for r in record.results if r.get("ticker") == "DEAD"]
    assert len(dead_results) == 1
    # MockBroker has no price for DEAD either - a real broker would likely
    # reject an order in a genuinely delisted symbol too. The point proven
    # here is that this never crashes and is always journaled honestly,
    # never silently dropped and never mistaken for a successful fill.
    assert dead_results[0]["status"] == "REJECTED"


# -- quant-gate VERDICT.md M08 cycle-1 finding 4: partial fills are ---------
# -- topped up across runs, never replayed as a fresh fill ------------------


def test_partial_fill_is_topped_up_across_runs_via_cancel_and_fresh_attempt_id(
    monkeypatch, tmp_path
):
    providers = _fake_providers({"AAA": 100.0, "BENCH": 50.0}, tmp_path)
    monkeypatch.setattr("quantlab.paper.runner.build_backtest_providers", lambda _config: providers)

    platform_config = _platform_config(tmp_path)
    strategy_config = {"strategy": "paper-runner-fixed-weight", "params": {"weights": {"AAA": 1.0}}}
    from quantlab.strategies.registry import load_strategy

    strategy_id = load_strategy(strategy_config).strategy_id
    _write_report_card(platform_config.reports_dir, strategy_id, "ELIGIBLE_FOR_PAPER")

    broker = MockBroker(
        capabilities_=BrokerCapabilities(True, False, False),
        prices={"AAA": 100.0},
        cash=100_000.0,
        asof="2024-01-12",
        partial_fill_fraction={"AAA": 0.25},
    )

    record1 = run_once(strategy_config, platform_config, broker)
    qty1 = broker.positions["AAA"].qty
    assert qty1 == pytest.approx(990.0 * 0.25)
    id1 = record1.planned_orders[0]["client_order_id"]
    assert "status" not in record1.results[0]  # a genuine Fill, not an ack
    # finding 4: "after submit, call open_orders(); journal resting
    # remainders" - visible in THIS run's own record, not only retroactively
    # via the next run's canceled_orders.
    assert record1.resting_orders == [{"client_order_id": id1, "ticker": "AAA", "qty": 742.5}]

    record2 = run_once(strategy_config, platform_config, broker)
    qty2 = broker.positions["AAA"].qty
    assert qty2 == pytest.approx(qty1 + 742.5 * 0.25)
    id2 = record2.planned_orders[0]["client_order_id"]
    assert id2 != id1
    assert record2.canceled_orders == [{"client_order_id": id1, "ticker": "AAA", "qty": 742.5}]
    assert "status" not in record2.results[0]  # a genuine fill, not a replay

    record3 = run_once(strategy_config, platform_config, broker)
    qty3 = broker.positions["AAA"].qty
    assert qty3 == pytest.approx(qty2 + 556.875 * 0.25)
    id3 = record3.planned_orders[0]["client_order_id"]
    assert id3 not in (id1, id2)
    assert "status" not in record3.results[0]


# -- quant-gate VERDICT.md M08 cycle-1 finding 5: blend per-child context ---
# -- guard survives the paper path -------------------------------------------


def test_blend_child_overreach_raises_via_run_once_set_context_factory(monkeypatch, tmp_path):
    from quantlab.core.errors import UndeclaredDataError

    blend_config = {
        "strategy": "blend",
        "params": {
            "children": [
                {"strategy": "paper-runner-blend-declare-only-child", "params": {}, "weight": 0.5},
                {"strategy": "paper-runner-blend-overreach-child", "params": {}, "weight": 0.5},
            ]
        },
    }
    providers = _fake_providers({"AAA": 100.0, "BENCH": 50.0}, tmp_path)
    monkeypatch.setattr("quantlab.paper.runner.build_backtest_providers", lambda _config: providers)

    platform_config = _platform_config(tmp_path)
    from quantlab.strategies.registry import load_strategy

    strategy_id = load_strategy(blend_config).strategy_id
    _write_report_card(platform_config.reports_dir, strategy_id, "ELIGIBLE_FOR_PAPER")

    broker = _mock_broker({"AAA": 100.0})

    with pytest.raises(UndeclaredDataError):
        run_once(blend_config, platform_config, broker)

    # quant-gate REVIEW.2.md: this exact path used to crash with ZERO
    # journal records - the structural outer catch (finding 1, cycle 2)
    # must still journal it, naming the stage and exception class.
    records = read_journal(platform_config.reports_dir, strategy_id)
    assert len(records) == 1
    assert records[0]["refused_reason"] is not None
    assert "stage='targets'" in records[0]["refused_reason"]
    assert "UndeclaredDataError" in records[0]["refused_reason"]
    assert records[0]["planned_orders"] == []


# -- quant-gate VERDICT.2.md M08 cycle-2 finding 1: the exactly-one-record --
# -- journal guarantee is STRUCTURAL, not enumerated per exception type -----


class _UnexpectedTestError(RuntimeError):
    """An exception class none of `run_once`'s specific inner handlers
    anticipate - the fixture for proving the outer structural catch-all,
    not any one enumerated `except` clause, is what closes the gap."""


@pytest.mark.parametrize("stage_name", ["context", "targets", "reconcile", "plan", "submit"])
def test_unexpected_exception_at_each_stage_is_journaled_exactly_once(
    monkeypatch, tmp_path, stage_name
):
    platform_config = _platform_config(tmp_path)
    strategy_config = {
        "strategy": "paper-runner-fixed-weight",
        "params": {"weights": {"AAA": 1.0}},
    }
    from quantlab.strategies.registry import load_strategy

    strategy_id = load_strategy(strategy_config).strategy_id
    _write_report_card(platform_config.reports_dir, strategy_id, "ELIGIBLE_FOR_PAPER")

    providers = _fake_providers({"AAA": 100.0, "BENCH": 50.0}, tmp_path)
    broker = _mock_broker({"AAA": 100.0})
    expected_record_count = 1

    if stage_name == "context":

        class _BrokenContextStrategy(Strategy):
            @classmethod
            def params_model(cls):
                return _FixedWeightParams

            def requires(self):
                return DataRequirements()

            def set_context_factory(self, factory):
                raise _UnexpectedTestError("boom in set_context_factory")

            def generate_targets(self, ctx, date):
                return TargetWeights(asof=date, weights={}, strategy_id=self.strategy_id)

        register_strategy("paper-runner-broken-context")(_BrokenContextStrategy)
        strategy_config = {"strategy": "paper-runner-broken-context", "params": {}}
        strategy_id = load_strategy(strategy_config).strategy_id
        _write_report_card(platform_config.reports_dir, strategy_id, "ELIGIBLE_FOR_PAPER")

    elif stage_name == "targets":

        class _BrokenTargetsStrategy(Strategy):
            @classmethod
            def params_model(cls):
                return _FixedWeightParams

            def requires(self):
                return DataRequirements()

            def generate_targets(self, ctx, date):
                raise _UnexpectedTestError("boom in generate_targets")

        register_strategy("paper-runner-broken-targets")(_BrokenTargetsStrategy)
        strategy_config = {"strategy": "paper-runner-broken-targets", "params": {}}
        strategy_id = load_strategy(strategy_config).strategy_id
        _write_report_card(platform_config.reports_dir, strategy_id, "ELIGIBLE_FOR_PAPER")

    elif stage_name == "reconcile":
        # Pre-seed a "prior traded run" directly (bypassing run_once) so the
        # reconcile block actually executes, then make the actions provider
        # raise something the reconcile block's own except clause does not
        # anticipate.
        expected_record_count = 2
        prior = JournalRecord(
            asof="2024-01-11",
            strategy_id=strategy_id,
            data_semantics_version=DATA_SEMANTICS_VERSION,
            quantlab_git_sha="deadbeef",
            dirty=False,
            targets={
                "asof": "2024-01-11",
                "weights": {"AAA": 1.0},
                "strategy_id": strategy_id,
            },
            planned_orders=[],
            results=[],
            account_before={
                "cash": 1000.0,
                "equity": 100_000.0,
                "positions": {"AAA": {"ticker": "AAA", "qty": 990.0, "avg_cost": 100.0}},
            },
            account_after={
                "cash": 1000.0,
                "equity": 100_000.0,
                "positions": {"AAA": {"ticker": "AAA", "qty": 990.0, "avg_cost": 100.0}},
            },
            reconcile_report=None,
            promoting_report_card=None,
            refused_reason=None,
        )
        append_journal(platform_config.reports_dir, prior)
        broker.positions["AAA"] = Position(ticker="AAA", qty=990.0, avg_cost=100.0)
        broker.cash = 1000.0

        class _BrokenReconcileActionsProvider(CorporateActionsProvider):
            def get_actions(self, ticker: str, start: object, end: object) -> pd.DataFrame:
                raise _UnexpectedTestError("boom in get_actions during reconcile")

        providers = BacktestProviders(
            price=_FakePriceProvider(_price_panel({"AAA": 100.0, "BENCH": 50.0})),
            constituents=_FakeConstituentsProvider([]),
            fundamentals=_NoOpFundamentalsProvider(),
            corporate_actions=_BrokenReconcileActionsProvider(),
            cache_dir=tmp_path / "cache",
        )

    elif stage_name == "plan":

        def _broken_plan_orders(*args, **kwargs):
            raise _UnexpectedTestError("boom in plan_orders")

        monkeypatch.setattr("quantlab.paper.runner.plan_orders", _broken_plan_orders)

    elif stage_name == "submit":

        def _broken_submit(orders):
            raise _UnexpectedTestError("boom in submit")

        broker.submit = _broken_submit

    monkeypatch.setattr("quantlab.paper.runner.build_backtest_providers", lambda _config: providers)

    with pytest.raises(_UnexpectedTestError):
        run_once(strategy_config, platform_config, broker)

    records = read_journal(platform_config.reports_dir, strategy_id)
    assert len(records) == expected_record_count
    last = records[-1]
    assert last["refused_reason"] is not None
    assert f"stage={stage_name!r}" in last["refused_reason"]
    assert "_UnexpectedTestError" in last["refused_reason"]
    if stage_name == "submit":
        # quant-gate VERDICT.2.md M08 cycle-2 non-blocking item: planning
        # succeeded (only submission failed), so the intended book IS
        # recorded rather than lost.
        assert last["planned_orders"] != []
    else:
        assert last["planned_orders"] == []


def test_a_failing_broker_account_still_leaves_exactly_one_record(monkeypatch, tmp_path):
    """Quant-gate VERDICT.2.md M08 cycle-2 finding 2: `_refuse` itself calls
    `broker.account()` to fill in the record - if THAT is what fails (an
    unreachable/unauthenticated broker, the single most likely real-world
    failure mode), the refusal writer must not also crash. `account_before`/
    `account_after` become an explicit `{"unavailable": ...}` marker rather
    than a real snapshot, and the run still leaves exactly one record naming
    the stage and cause."""

    class _BrokenAccountBroker(MockBroker):
        def account(self):
            raise _UnexpectedTestError("boom in account()")

    providers = _fake_providers({"AAA": 100.0, "BENCH": 50.0}, tmp_path)
    monkeypatch.setattr("quantlab.paper.runner.build_backtest_providers", lambda _config: providers)

    platform_config = _platform_config(tmp_path)
    strategy_config = {
        "strategy": "paper-runner-broken-targets",
        "params": {},
    }

    class _BrokenTargetsStrategy(Strategy):
        @classmethod
        def params_model(cls):
            return _FixedWeightParams

        def requires(self):
            return DataRequirements()

        def generate_targets(self, ctx, date):
            raise _UnexpectedTestError("boom in generate_targets")

    register_strategy("paper-runner-broken-targets")(_BrokenTargetsStrategy)
    from quantlab.strategies.registry import load_strategy

    strategy_id = load_strategy(strategy_config).strategy_id
    _write_report_card(platform_config.reports_dir, strategy_id, "ELIGIBLE_FOR_PAPER")

    broker = _BrokenAccountBroker(
        capabilities_=BrokerCapabilities(True, False, False), prices={"AAA": 100.0}, cash=100_000.0
    )

    with pytest.raises(_UnexpectedTestError):
        run_once(strategy_config, platform_config, broker)

    records = read_journal(platform_config.reports_dir, strategy_id)
    assert len(records) == 1
    record = records[0]
    assert record["refused_reason"] is not None
    assert "stage='targets'" in record["refused_reason"]
    assert "ALSO: broker.account() failed" in record["refused_reason"]
    assert record["account_before"] == {"unavailable": "_UnexpectedTestError: boom in account()"}
    assert record["account_after"] == {"unavailable": "_UnexpectedTestError: boom in account()"}


# -- quant-gate VERDICT.2.md M08 cycle-2 finding 1: the actions-cache -------
# -- refresh policy must be PROACTIVE, not merely reactive, so it actually --
# -- runs for a SHIPPED declaration shape (needs_universe + price lookback) -


def _write_actions_meta(cache_dir, ticker: str, fetched_at: str) -> None:
    from quantlab.data.cache import write_json_meta

    write_json_meta(Path(cache_dir) / "actions" / f"{ticker}.meta.json", {"fetched_at": fetched_at})


class _StaleUntilRefreshedActionsProvider(CorporateActionsProvider):
    """Raises `StaleActionsCacheError` for any ticker not (yet) in
    `.refreshed` - paired with a `refresh_actions_cache` spy that adds a
    ticker to `.refreshed` when "refreshing" it, so this fake models the
    real production contract (stale until refreshed, fine after) without
    any real disk/network I/O."""

    def __init__(self, always_fine: set[str] | None = None):
        self.always_fine = always_fine or set()
        self.refreshed: set[str] = set()

    def get_actions(self, ticker: str, start: object, end: object) -> pd.DataFrame:
        if ticker in self.always_fine or ticker in self.refreshed:
            return _empty_actions()
        raise StaleActionsCacheError(f"{ticker}: stale until refreshed")


def test_proactive_refresh_clears_a_wholly_stale_universe_for_a_shipped_shape(
    monkeypatch, tmp_path
):
    """(a) from quant-gate VERDICT.2.md finding 1's required remedy: the
    NORMAL monthly state (every universe ticker's actions cache stale,
    `momentum_12_1.yaml`'s own declaration shape) must be cleared
    PROACTIVELY, before the shared filter ever gets a chance to see (and
    silently drop) the staleness - `refresh_actions_cache` called once per
    ticker, the run proceeds, and NO `BacktestAbortError`."""
    tickers = _many_tickers(5)
    prices = dict.fromkeys(tickers, 100.0)
    prices["BENCH"] = 50.0
    # No sidecar files at all -> every ticker's fetched_at reads as missing
    # -> every ticker looks stale to the proactive check.
    action_provider = _StaleUntilRefreshedActionsProvider()
    refresh_calls: list[str] = []

    def _spy_refresh(ticker: str, cache_dir) -> None:
        refresh_calls.append(ticker)
        action_provider.refreshed.add(ticker)

    monkeypatch.setattr("quantlab.paper.runner.refresh_actions_cache", _spy_refresh)

    providers = BacktestProviders(
        price=_FakePriceProvider(_price_panel(prices)),
        constituents=_FakeConstituentsProvider(tickers),
        fundamentals=_NoOpFundamentalsProvider(),
        corporate_actions=action_provider,
        cache_dir=tmp_path / "cache",
    )
    monkeypatch.setattr("quantlab.paper.runner.build_backtest_providers", lambda _config: providers)

    platform_config = _platform_config(tmp_path)
    strategy_config = {"strategy": "paper-runner-equal-weight-universe", "params": {}}
    from quantlab.strategies.registry import load_strategy

    strategy_id = load_strategy(strategy_config).strategy_id
    _write_report_card(platform_config.reports_dir, strategy_id, "ELIGIBLE_FOR_PAPER")

    broker = _mock_broker(prices)

    record = run_once(strategy_config, platform_config, broker)

    assert record.refused_reason is None
    assert sorted(refresh_calls) == sorted(tickers)
    assert record.dropped_tickers == []
    assert set(record.targets["weights"]) == set(tickers)
    assert set(record.refreshed_actions_tickers) == set(tickers)


def test_proactive_refresh_refreshes_and_includes_the_one_stale_ticker_under_threshold(
    monkeypatch, tmp_path
):
    """(b) from quant-gate VERDICT.2.md finding 1's required remedy: with
    39 of 40 tickers ALREADY fresh (a real sidecar file dated after `asof`)
    and only one missing its sidecar, the proactive pass must refresh ONLY
    that one - it is then INCLUDED in the traded book, never dropped, and
    never mistaken for a data-availability failure."""
    tickers = _many_tickers(40)
    stale_ticker = tickers[0]
    prices = dict.fromkeys(tickers, 100.0)
    prices["BENCH"] = 50.0

    cache_dir = tmp_path / "cache"
    for ticker in tickers:
        if ticker != stale_ticker:
            _write_actions_meta(cache_dir, ticker, "2024-06-01")  # well after asof

    action_provider = _StaleUntilRefreshedActionsProvider(always_fine=set(tickers) - {stale_ticker})
    refresh_calls: list[str] = []

    def _spy_refresh(ticker: str, cd) -> None:
        refresh_calls.append(ticker)
        action_provider.refreshed.add(ticker)

    monkeypatch.setattr("quantlab.paper.runner.refresh_actions_cache", _spy_refresh)

    providers = BacktestProviders(
        price=_FakePriceProvider(_price_panel(prices)),
        constituents=_FakeConstituentsProvider(tickers),
        fundamentals=_NoOpFundamentalsProvider(),
        corporate_actions=action_provider,
        cache_dir=cache_dir,
    )
    monkeypatch.setattr("quantlab.paper.runner.build_backtest_providers", lambda _config: providers)

    platform_config = _platform_config(tmp_path)
    strategy_config = {"strategy": "paper-runner-equal-weight-universe", "params": {}}
    from quantlab.strategies.registry import load_strategy

    strategy_id = load_strategy(strategy_config).strategy_id
    _write_report_card(platform_config.reports_dir, strategy_id, "ELIGIBLE_FOR_PAPER")

    broker = _mock_broker(prices)

    record = run_once(strategy_config, platform_config, broker)

    assert record.refused_reason is None
    assert refresh_calls == [stale_ticker]
    assert record.dropped_tickers == []
    assert stale_ticker in record.targets["weights"]
    assert set(record.targets["weights"]) == set(tickers)
    assert record.refreshed_actions_tickers == [stale_ticker]


def test_proactive_refresh_failure_for_one_ticker_still_drops_it_via_the_shared_filter(
    monkeypatch, tmp_path
):
    """(c) from quant-gate VERDICT.2.md finding 1's required remedy: when
    the refresh ITSELF fails for one ticker (a genuine, not merely stale,
    data failure), that ticker is dropped via the shared filter exactly
    like any other data-availability failure - counted, journaled, and the
    run proceeds under `max_dropped_fraction`."""
    tickers = _many_tickers(40)
    unfetchable_ticker = tickers[0]
    prices = dict.fromkeys(tickers, 100.0)
    prices["BENCH"] = 50.0

    action_provider = _StaleUntilRefreshedActionsProvider()  # every ticker starts stale
    refresh_calls: list[str] = []

    def _spy_refresh(ticker: str, cache_dir) -> None:
        refresh_calls.append(ticker)
        if ticker == unfetchable_ticker:
            raise ActionsFetchError(f"{ticker}: refresh failed for testing")
        action_provider.refreshed.add(ticker)

    monkeypatch.setattr("quantlab.paper.runner.refresh_actions_cache", _spy_refresh)

    providers = BacktestProviders(
        price=_FakePriceProvider(_price_panel(prices)),
        constituents=_FakeConstituentsProvider(tickers),
        fundamentals=_NoOpFundamentalsProvider(),
        corporate_actions=action_provider,
        cache_dir=tmp_path / "cache",
    )
    monkeypatch.setattr("quantlab.paper.runner.build_backtest_providers", lambda _config: providers)

    platform_config = _platform_config(tmp_path)
    strategy_config = {"strategy": "paper-runner-equal-weight-universe", "params": {}}
    from quantlab.strategies.registry import load_strategy

    strategy_id = load_strategy(strategy_config).strategy_id
    _write_report_card(platform_config.reports_dir, strategy_id, "ELIGIBLE_FOR_PAPER")

    broker = _mock_broker(prices)

    record = run_once(strategy_config, platform_config, broker)

    assert record.refused_reason is None
    assert unfetchable_ticker in refresh_calls
    assert record.dropped_tickers == [unfetchable_ticker]
    assert record.dropped_fraction == pytest.approx(1 / 40)
    assert unfetchable_ticker not in record.targets["weights"]
    assert len(record.targets["weights"]) == 39


# -- quant-gate VERDICT.md M08 cycle-1 finding 1: reconciliation survives ---
# -- an ordinary corporate action, and an explicit re-baseline exists -------


def _wide_price_panel(tickers_and_prices: dict[str, float]) -> pd.DataFrame:
    sessions = trading_days("2023-06-01", "2024-03-31")
    frames = [
        pd.DataFrame(
            {
                "ticker": [t] * len(sessions),
                "open": [p] * len(sessions),
                "high": [p] * len(sessions),
                "low": [p] * len(sessions),
                "close": [p] * len(sessions),
                "adj_close": [p] * len(sessions),
                "volume": [1000] * len(sessions),
            },
            index=sessions,
        )
        for t, p in tickers_and_prices.items()
    ]
    return pd.concat(frames).sort_index()


def test_dividend_between_runs_is_explained_and_does_not_brick_the_schedule(monkeypatch, tmp_path):
    """Reproduces the gate's own four-run finding: a dividend credited by
    the broker between two scheduled runs must be EXPLAINED by
    `roll_forward_expected`, not read as a permanent, unrecoverable
    mismatch."""
    from quantlab.core.calendar import next_trading_day

    platform_config = _platform_config(tmp_path)
    strategy_config = {"strategy": "paper-runner-fixed-weight", "params": {"weights": {"AAA": 1.0}}}
    from quantlab.strategies.registry import load_strategy

    strategy_id = load_strategy(strategy_config).strategy_id
    _write_report_card(platform_config.reports_dir, strategy_id, "ELIGIBLE_FOR_PAPER")

    dividend_actions = pd.DataFrame(
        {"ticker": ["AAA"], "action_type": ["dividend"], "value": [0.25]},
        index=pd.DatetimeIndex(["2023-12-15"]),
    )
    providers = BacktestProviders(
        price=_FakePriceProvider(_wide_price_panel({"AAA": 100.0, "BENCH": 50.0})),
        constituents=_FakeConstituentsProvider([]),
        fundamentals=_NoOpFundamentalsProvider(),
        corporate_actions=_ActionsHistoryProvider({"AAA": dividend_actions}),
        cache_dir=tmp_path / "cache",
    )
    monkeypatch.setattr("quantlab.paper.runner.build_backtest_providers", lambda _config: providers)

    broker = _mock_broker({"AAA": 100.0})

    def _run_at(asof_str: str):
        asof_ts = pd.Timestamp(asof_str)
        monkeypatch.setattr("quantlab.paper.runner._today", lambda: next_trading_day(asof_ts))
        return run_once(strategy_config, platform_config, broker, asof=asof_str)

    record1 = _run_at("2023-11-30")
    assert record1.refused_reason is None
    qty = broker.positions["AAA"].qty
    broker.cash += qty * 0.25  # the broker's own real-world dividend credit

    record2 = _run_at("2023-12-29")
    assert record2.refused_reason is None, record2.refused_reason
    assert record2.reconcile_report is not None
    assert record2.reconcile_report["ok"] is True
    applied = record2.reconcile_report["applied_adjustments"]
    assert len(applied) == 1
    assert applied[0]["action_type"] == "dividend"
    assert applied[0]["cash_credit"] == pytest.approx(qty * 0.25)

    record3 = _run_at("2024-01-31")
    assert record3.refused_reason is None

    record4 = _run_at("2024-02-29")
    assert record4.refused_reason is None


def test_unexplained_mismatch_still_refuses_even_with_roll_forward(monkeypatch, tmp_path):
    """A mismatch `roll_forward_expected` cannot explain (no matching
    action) must still refuse - the fix is "explain the ordinary case",
    not "loosen the check"."""
    platform_config = _platform_config(tmp_path)
    strategy_config = {"strategy": "paper-runner-fixed-weight", "params": {"weights": {"AAA": 1.0}}}
    from quantlab.strategies.registry import load_strategy

    strategy_id = load_strategy(strategy_config).strategy_id
    _write_report_card(platform_config.reports_dir, strategy_id, "ELIGIBLE_FOR_PAPER")

    providers = _fake_providers({"AAA": 100.0, "BENCH": 50.0}, tmp_path)
    monkeypatch.setattr("quantlab.paper.runner.build_backtest_providers", lambda _config: providers)

    broker = _mock_broker({"AAA": 100.0})
    run_once(strategy_config, platform_config, broker)

    broker.cash += 5_000.0  # unexplained - no corresponding action exists

    with pytest.raises(ReconcileErrorType):
        run_once(strategy_config, platform_config, broker)

    records = read_journal(platform_config.reports_dir, strategy_id)
    assert records[-1]["refused_reason"] is not None


def test_accept_broker_state_rebaseline_records_a_loud_diff_and_unblocks_the_schedule(
    monkeypatch, tmp_path
):
    platform_config = _platform_config(tmp_path)
    strategy_config = {"strategy": "paper-runner-fixed-weight", "params": {"weights": {"AAA": 1.0}}}
    from quantlab.strategies.registry import load_strategy

    strategy_id = load_strategy(strategy_config).strategy_id
    _write_report_card(platform_config.reports_dir, strategy_id, "ELIGIBLE_FOR_PAPER")

    providers = _fake_providers({"AAA": 100.0, "BENCH": 50.0}, tmp_path)
    monkeypatch.setattr("quantlab.paper.runner.build_backtest_providers", lambda _config: providers)

    broker = _mock_broker({"AAA": 100.0})
    run_once(strategy_config, platform_config, broker)

    broker.cash += 9_999.0  # an unexplainable mismatch (e.g. a manual transfer)

    record = accept_broker_state(
        strategy_config, platform_config, broker, reason="manual transfer, verified with broker"
    )

    assert record.kind == "rebaseline"
    assert record.refused_reason is None
    assert "MANUAL RE-BASELINE" in record.known_caveats[0]
    assert record.reconcile_report is not None
    assert record.reconcile_report["cash_diff"] == pytest.approx(9_999.0)

    records = read_journal(platform_config.reports_dir, strategy_id)
    assert records[-1]["kind"] == "rebaseline"

    # The NEXT ordinary run reconciles cleanly against the rebaseline.
    record_next = run_once(strategy_config, platform_config, broker)
    assert record_next.refused_reason is None
