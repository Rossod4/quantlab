"""Tests for `paper/drift.py` (`quantlab paper drift`, M09 carried from the
M08 verdict). Offline: no backtest is run and no broker is touched - only a
hand-built journal and fake providers, mirroring tests/test_runner.py's own
fixture style."""

from __future__ import annotations

import pandas as pd
import pytest
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


def _priced_providers(tmp_path, *, decision_close, fill_open, drop_fill_session=False):
    """A panel whose decision-day close, fill-session open and everything else
    are all DIFFERENT, so the two gaps cannot be confused."""
    sessions = trading_days("2024-01-01", "2024-02-01")
    frame = pd.DataFrame(
        {
            "ticker": "AAA",
            "open": 90.0,
            "high": 120.0,
            "low": 80.0,
            "close": 95.0,
            "adj_close": 95.0,
            "volume": 1000,
        },
        index=sessions,
    )
    frame.loc[pd.Timestamp("2024-01-10"), "close"] = decision_close
    frame.loc[pd.Timestamp("2024-01-11"), "open"] = fill_open
    if drop_fill_session:
        frame = frame.drop(pd.Timestamp("2024-01-11"))
    return BacktestProviders(
        price=_FakePriceProvider(frame),
        constituents=_FakeConstituentsProvider(),
        fundamentals=_NoOpFundamentalsProvider(),
        corporate_actions=_EmptyActionsProvider(),
        cache_dir=tmp_path / "cache",
    )


def _fill_record(strategy, fill_price=103.5, assumed_fill_session="2024-01-11"):
    return _trading_record(
        "2024-01-10",
        {"AAA": 1.0},
        results=[
            {"kind": "Fill", "client_order_id": "x", "ticker": "AAA", "price": fill_price, "qty": 5}
        ],
        price_asof_by_ticker={"AAA": "2024-01-10"},
        assumed_fill_session=assumed_fill_session,
        strategy_id=strategy.strategy_id,
    )


def test_timing_and_execution_gaps_are_separated_in_bps(tmp_path):
    """Decision close 100, fill-session open 103, fill 103.5: the overnight
    convention offset is +300 bps and the real slippage is only +48.5 bps -
    one blended 'fill vs close' figure (350 bps) would mislabel the former as
    drift."""
    strategy = _strategy({"AAA": 1.0})
    append_journal(tmp_path, _fill_record(strategy))

    report = compute_drift(
        tmp_path, strategy, _priced_providers(tmp_path, decision_close=100.0, fill_open=103.0)
    )

    rec = report.records[0]
    assert rec.timing_gap_bps["AAA"] == pytest.approx(300.0)
    assert rec.execution_gap_bps["AAA"] == pytest.approx((103.5 - 103.0) / 103.0 * 10_000.0)
    assert rec.gaps_not_computed == {}
    assert rec.assumed_fill_session == "2024-01-11"


def test_assumed_fill_session_selects_which_open_is_used(tmp_path):
    strategy = _strategy({"AAA": 1.0})
    providers = _priced_providers(tmp_path, decision_close=100.0, fill_open=103.0)
    # fill-session 2024-01-12's open is the flat 90.0 of the panel
    append_journal(tmp_path, _fill_record(strategy, assumed_fill_session="2024-01-12"))

    rec = compute_drift(tmp_path, strategy, providers).records[0]

    assert rec.timing_gap_bps["AAA"] == pytest.approx((90.0 - 100.0) / 100.0 * 10_000.0)


def test_missing_fill_session_open_is_not_computed_never_zero(tmp_path):
    strategy = _strategy({"AAA": 1.0})
    append_journal(tmp_path, _fill_record(strategy))
    providers = _priced_providers(
        tmp_path, decision_close=100.0, fill_open=103.0, drop_fill_session=True
    )

    rec = compute_drift(tmp_path, strategy, providers).records[0]

    assert rec.timing_gap_bps == {} and rec.execution_gap_bps == {}
    assert "fill-session open" in rec.gaps_not_computed["AAA"]


def test_a_record_without_an_assumed_fill_session_reports_no_gap(tmp_path):
    strategy = _strategy({"AAA": 1.0})
    append_journal(tmp_path, _fill_record(strategy, assumed_fill_session=None))

    rec = compute_drift(
        tmp_path, strategy, _priced_providers(tmp_path, decision_close=100.0, fill_open=103.0)
    ).records[0]

    assert rec.timing_gap_bps == {} and rec.execution_gap_bps == {}
    assert "assumed_fill_session" in rec.gaps_not_computed["AAA"]


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

    assert report.records[0].timing_gap_bps == {}
    assert report.records[0].execution_gap_bps == {}


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


# -- look-ahead guard: the recompute context is bound to the JOURNALED asof --
#
# `compute_drift` rebuilds each journaled decision with
# `build_decision_context(asof=<journaled asof>)`. A recompute bound even one
# day later would let the strategy read data the live decision never had and
# make drift look better than it is. Mutation check (recorded in
# plans/state/M09/HANDOFF.2.md): `asof=_asof + pd.Timedelta(days=30)` in
# drift.py's `_context_factory` makes both tests below fail.

_OBSERVED_ASOFS: list[pd.Timestamp] = []


class _DriftSpyParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tag: str = ""


@register_strategy("drift-test-asof-spy")
class _DriftAsofSpyStrategy(Strategy):
    @classmethod
    def params_model(cls) -> type[BaseModel]:
        return _DriftSpyParams

    def requires(self) -> DataRequirements:
        return DataRequirements()

    def generate_targets(self, ctx, date) -> TargetWeights:
        _OBSERVED_ASOFS.append(ctx.asof)
        return TargetWeights(asof=date, weights={}, strategy_id=self.strategy_id)


def _journal_two_asofs(tmp_path, strategy_id: str) -> list[pd.Timestamp]:
    asofs = ["2024-01-10", "2024-01-18"]
    for asof in asofs:
        append_journal(tmp_path, _trading_record(asof, {"AAA": 1.0}, strategy_id=strategy_id))
    return [pd.Timestamp(a) for a in asofs]


def test_drift_recompute_context_is_bound_to_each_journaled_asof(tmp_path):
    from quantlab.strategies.registry import load_strategy

    strategy = load_strategy({"strategy": "drift-test-asof-spy"})
    expected = _journal_two_asofs(tmp_path, strategy.strategy_id)
    _OBSERVED_ASOFS.clear()

    compute_drift(tmp_path, strategy, _providers({"AAA": 100.0}, tmp_path))

    assert _OBSERVED_ASOFS == expected


def test_drift_recompute_blend_children_contexts_are_bound_to_the_journaled_asof(tmp_path):
    from quantlab.strategies.registry import load_strategy

    strategy = load_strategy(
        {
            "strategy": "blend",
            "params": {
                "children": [
                    {"strategy": "drift-test-asof-spy", "params": {"tag": "a"}, "weight": 0.5},
                    {"strategy": "drift-test-asof-spy", "params": {"tag": "b"}, "weight": 0.5},
                ]
            },
        }
    )
    expected = _journal_two_asofs(tmp_path, strategy.strategy_id)
    _OBSERVED_ASOFS.clear()

    compute_drift(tmp_path, strategy, _providers({"AAA": 100.0}, tmp_path))

    assert _OBSERVED_ASOFS == [e for e in expected for _ in range(2)]


class _SplitActionsProvider(CorporateActionsProvider):
    def __init__(self, ex_date: str, stale: bool = False):
        self._ex_date = ex_date
        self._stale = stale

    def get_actions(self, ticker, start, end) -> pd.DataFrame:
        if self._stale:
            raise RuntimeError("actions cache stale")
        frame = pd.DataFrame(
            {"ticker": [ticker], "action_type": ["split"], "value": [2.0]},
            index=pd.DatetimeIndex([self._ex_date], name="date"),
        )
        return frame[frame.index <= pd.Timestamp(end)]


def _providers_with_actions(tmp_path, actions) -> BacktestProviders:
    base = _priced_providers(tmp_path, decision_close=100.0, fill_open=103.0)
    return BacktestProviders(
        price=base.price,
        constituents=base.constituents,
        fundamentals=base.fundamentals,
        corporate_actions=actions,
        cache_dir=base.cache_dir,
    )


def test_a_split_between_decision_close_and_fill_open_is_flagged_not_a_timing_gap(tmp_path):
    strategy = _strategy({"AAA": 1.0})
    append_journal(tmp_path, _fill_record(strategy))  # decision 2024-01-10, fill session 01-11

    rec = compute_drift(
        tmp_path, strategy, _providers_with_actions(tmp_path, _SplitActionsProvider("2024-01-11"))
    ).records[0]

    assert rec.timing_gap_bps == {} and rec.execution_gap_bps == {}
    assert "split ex-dated between" in rec.gaps_not_computed["AAA"]


def test_a_split_outside_the_two_sessions_does_not_block_the_gaps(tmp_path):
    strategy = _strategy({"AAA": 1.0})
    append_journal(tmp_path, _fill_record(strategy))

    rec = compute_drift(
        tmp_path, strategy, _providers_with_actions(tmp_path, _SplitActionsProvider("2024-01-10"))
    ).records[0]  # ex-date ON the decision date is before the fill session's open

    assert rec.timing_gap_bps["AAA"] == pytest.approx(300.0)


def test_unreadable_actions_means_the_gap_is_not_computed(tmp_path):
    strategy = _strategy({"AAA": 1.0})
    append_journal(tmp_path, _fill_record(strategy))

    rec = compute_drift(
        tmp_path,
        strategy,
        _providers_with_actions(tmp_path, _SplitActionsProvider("2024-01-11", stale=True)),
    ).records[0]

    assert rec.timing_gap_bps == {}
    assert "cannot rule out a split" in rec.gaps_not_computed["AAA"]
