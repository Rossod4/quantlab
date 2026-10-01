"""Tests for `paper/drift.py` (`quantlab paper drift`, M09 carried from the
M08 verdict). Offline: no backtest is run and no broker is touched - only a
hand-built journal and fake providers, mirroring tests/test_runner.py's own
fixture style."""

from __future__ import annotations

import pandas as pd
from pydantic import BaseModel, ConfigDict

from quantlab.backtest.engine import BacktestProviders
from quantlab.core.calendar import trading_days
from quantlab.core.types import TargetWeights
from quantlab.data.interfaces import (
    ConstituentsProvider,
    CorporateActionsProvider,
    FundamentalsProvider,
    PriceProvider,
)
from quantlab.data.requirements import DataRequirements
from quantlab.paper.drift import compute_drift
from quantlab.paper.journal import JournalRecord, append_journal
from quantlab.strategies.base import Strategy
from quantlab.strategies.registry import register_strategy


class _FakePriceProvider(PriceProvider):
    def __init__(self, panel: pd.DataFrame):
        self._panel = panel

    def get_prices(self, tickers, start, end) -> pd.DataFrame:
        panel = self._panel[self._panel["ticker"].isin(tickers)]
        return panel[(panel.index >= pd.Timestamp(start)) & (panel.index <= pd.Timestamp(end))]


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


class _DriftFixedWeightParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    weights: dict[str, float] = {}


@register_strategy("drift-test-fixed-weight")
class _DriftFixedWeightStrategy(Strategy):
    """Ignores `ctx` - always returns `params.weights`, so any disagreement
    in a test comes entirely from what was hand-journaled, not from any real
    signal logic drifting."""

    @classmethod
    def params_model(cls) -> type[BaseModel]:
        return _DriftFixedWeightParams

    def requires(self) -> DataRequirements:
        return DataRequirements()

    def generate_targets(self, ctx, date) -> TargetWeights:
        return TargetWeights(
            asof=date, weights=dict(self._params.weights), strategy_id=self.strategy_id
        )


def _panel(tickers_and_prices: dict[str, float]) -> pd.DataFrame:
    sessions = trading_days("2024-01-01", "2024-02-01")
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


def _providers(prices: dict[str, float], tmp_path) -> BacktestProviders:
    return BacktestProviders(
        price=_FakePriceProvider(_panel(prices)),
        constituents=_FakeConstituentsProvider(),
        fundamentals=_NoOpFundamentalsProvider(),
        corporate_actions=_EmptyActionsProvider(),
        cache_dir=tmp_path / "cache",
    )


def _strategy(weights: dict[str, float]) -> _DriftFixedWeightStrategy:
    return _DriftFixedWeightStrategy({"weights": weights})


def _trading_record(
    asof: str,
    weights: dict[str, float],
    *,
    results: list[dict] | None = None,
    price_asof_by_ticker: dict[str, str] | None = None,
    assumed_fill_session: str | None = None,
    strategy_id: str = "test",
) -> JournalRecord:
    return JournalRecord(
        asof=asof,
        strategy_id=strategy_id,
        data_semantics_version="m09",
        quantlab_git_sha="deadbeef",
        dirty=False,
        targets={"asof": asof, "weights": weights, "strategy_id": strategy_id},
        planned_orders=[],
        results=results or [],
        account_before={"cash": 1000.0, "equity": 1000.0, "positions": {}},
        account_after={"cash": 1000.0, "equity": 1000.0, "positions": {}},
        reconcile_report=None,
        promoting_report_card=None,
        refused_reason=None,
        price_asof_by_ticker=price_asof_by_ticker or {},
        assumed_fill_session=assumed_fill_session,
    )


def test_perfect_agreement_when_journal_matches_the_current_strategy(tmp_path):
    strategy = _strategy({"AAA": 1.0})
    append_journal(
        tmp_path,
        _trading_record("2024-01-10", {"AAA": 1.0}, strategy_id=strategy.strategy_id),
    )
    providers = _providers({"AAA": 100.0}, tmp_path)

    report = compute_drift(tmp_path, strategy, providers)

    assert len(report.records) == 1
    rec = report.records[0]
    assert rec.error is None
    assert rec.target_weight_agreement == 1.0
    assert rec.max_abs_weight_diff == 0.0
    assert rec.tickers_only_in_journal == []
    assert rec.tickers_only_in_recomputed == []


def test_disagreement_is_measured_not_hidden(tmp_path):
    # The strategy TODAY would put 100% in BBB; the journal recorded 100% in
    # AAA (e.g. the universe/signal has since changed).
    strategy = _strategy({"BBB": 1.0})
    append_journal(
        tmp_path,
        _trading_record("2024-01-10", {"AAA": 1.0}, strategy_id=strategy.strategy_id),
    )
    providers = _providers({"AAA": 100.0, "BBB": 50.0}, tmp_path)

    report = compute_drift(tmp_path, strategy, providers)

    rec = report.records[0]
    assert rec.target_weight_agreement == 0.0  # fully disjoint books
    assert rec.max_abs_weight_diff == 1.0
    assert rec.tickers_only_in_journal == ["AAA"]
    assert rec.tickers_only_in_recomputed == ["BBB"]


def test_fill_vs_model_price_gap_is_computed_in_bps(tmp_path):
    strategy = _strategy({"AAA": 1.0})
    # The raw close on 2024-01-10 is 100.0 (flat panel); the recorded fill
    # was at 101.5 - a 150 bps gap (next-session-open slippage vs. the
    # decision-time close the runner sized against).
    append_journal(
        tmp_path,
        _trading_record(
            "2024-01-10",
            {"AAA": 1.0},
            results=[
                {"kind": "Fill", "client_order_id": "x", "ticker": "AAA", "price": 101.5, "qty": 5}
            ],
            price_asof_by_ticker={"AAA": "2024-01-10"},
            assumed_fill_session="2024-01-11",
            strategy_id=strategy.strategy_id,
        ),
    )
    providers = _providers({"AAA": 100.0}, tmp_path)

    report = compute_drift(tmp_path, strategy, providers)

    rec = report.records[0]
    assert rec.fill_vs_model_price_gap_bps["AAA"] == 150.0
    assert rec.assumed_fill_session == "2024-01-11"


def test_order_ack_without_a_price_is_not_treated_as_a_fill(tmp_path):
    strategy = _strategy({"AAA": 1.0})
    append_journal(
        tmp_path,
        _trading_record(
            "2024-01-10",
            {"AAA": 1.0},
            results=[
                {"kind": "OrderAck", "client_order_id": "x", "ticker": "AAA", "status": "ACCEPTED"}
            ],
            price_asof_by_ticker={"AAA": "2024-01-10"},
            strategy_id=strategy.strategy_id,
        ),
    )
    providers = _providers({"AAA": 100.0}, tmp_path)

    report = compute_drift(tmp_path, strategy, providers)

    assert report.records[0].fill_vs_model_price_gap_bps == {}


def test_price_asof_lag_sessions_counts_trading_sessions_behind_asof(tmp_path):
    strategy = _strategy({"AAA": 1.0})
    append_journal(
        tmp_path,
        _trading_record(
            "2024-01-10",
            {"AAA": 1.0},
            price_asof_by_ticker={"AAA": "2024-01-08"},  # 2 sessions behind
            strategy_id=strategy.strategy_id,
        ),
    )
    providers = _providers({"AAA": 100.0}, tmp_path)

    report = compute_drift(tmp_path, strategy, providers)

    assert report.records[0].price_asof_lag_sessions["AAA"] == 2


def test_refused_and_rebaseline_records_are_skipped(tmp_path):
    strategy = _strategy({"AAA": 1.0})
    refused = _trading_record("2024-01-05", {}, strategy_id=strategy.strategy_id)
    refused = JournalRecord(**{**refused.__dict__, "refused_reason": "promotion gate refused"})
    append_journal(tmp_path, refused)
    rebaseline = _trading_record("2024-01-06", {"AAA": 1.0}, strategy_id=strategy.strategy_id)
    rebaseline = JournalRecord(**{**rebaseline.__dict__, "kind": "rebaseline"})
    append_journal(tmp_path, rebaseline)
    providers = _providers({"AAA": 100.0}, tmp_path)

    report = compute_drift(tmp_path, strategy, providers)

    assert report.records == []


def test_no_journal_entries_yet_returns_an_empty_report(tmp_path):
    strategy = _strategy({"AAA": 1.0})
    providers = _providers({"AAA": 100.0}, tmp_path)

    report = compute_drift(tmp_path, strategy, providers)

    assert report.strategy_id == strategy.strategy_id
    assert report.records == []


def test_recompute_failure_is_reported_per_record_not_fatal(tmp_path, monkeypatch):
    strategy = _strategy({"AAA": 1.0})
    append_journal(
        tmp_path,
        _trading_record("2024-01-10", {"AAA": 1.0}, strategy_id=strategy.strategy_id),
    )
    providers = _providers({"AAA": 100.0}, tmp_path)

    def _boom(self, ctx, date):
        raise ValueError("boom")

    monkeypatch.setattr(_DriftFixedWeightStrategy, "generate_targets", _boom)

    report = compute_drift(tmp_path, strategy, providers)

    assert len(report.records) == 1
    assert report.records[0].error is not None
    assert "boom" in report.records[0].error


def test_max_records_keeps_only_the_most_recent(tmp_path):
    strategy = _strategy({"AAA": 1.0})
    for day in ("2024-01-08", "2024-01-09", "2024-01-10"):
        append_journal(
            tmp_path, _trading_record(day, {"AAA": 1.0}, strategy_id=strategy.strategy_id)
        )
    providers = _providers({"AAA": 100.0}, tmp_path)

    report = compute_drift(tmp_path, strategy, providers, max_records=1)

    assert [r.asof for r in report.records] == ["2024-01-10"]


def test_drift_report_to_json_round_trips_shape(tmp_path):
    strategy = _strategy({"AAA": 1.0})
    append_journal(
        tmp_path,
        _trading_record("2024-01-10", {"AAA": 1.0}, strategy_id=strategy.strategy_id),
    )
    providers = _providers({"AAA": 100.0}, tmp_path)

    report = compute_drift(tmp_path, strategy, providers)
    payload = report.to_json()

    assert payload["strategy_id"] == strategy.strategy_id
    assert len(payload["records"]) == 1
    assert payload["records"][0]["asof"] == "2024-01-10"
