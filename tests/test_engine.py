"""Tests for backtest/engine.py - see the module's own docstring for the
design this exercises. Fakes implement the same ABCs as
tests/test_momentum_strategy.py and tests/canaries/test_lookahead.py (no
network, offline, deterministic - CLAUDE.md invariant #5)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from pydantic import BaseModel, ConfigDict

from quantlab.backtest.config import BacktestConfig
from quantlab.backtest.engine import (
    BacktestAbortError,
    BacktestProviders,
    _drop_terminal_partial_period,
    _is_genuine_period_boundary,
    run_backtest,
)
from quantlab.core.calendar import trading_days
from quantlab.core.errors import StaleActionsCacheError
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


class _EmptyActionsProvider(CorporateActionsProvider):
    def get_actions(self, ticker: str, start: object, end: object) -> pd.DataFrame:
        df = pd.DataFrame(columns=["ticker", "action_type", "value"])
        df.index = pd.DatetimeIndex([], name="date")
        return df


class _HostileActionsProvider(CorporateActionsProvider):
    """Fails for a fixed set of tickers, always - the fixture for acceptance
    criterion 8 (a hostile actions provider failing for one ticker)."""

    def __init__(self, failing_tickers: set[str]):
        self._failing = failing_tickers

    def get_actions(self, ticker: str, start: object, end: object) -> pd.DataFrame:
        if ticker in self._failing:
            raise StaleActionsCacheError(f"{ticker}: forced failure for testing")
        df = pd.DataFrame(columns=["ticker", "action_type", "value"])
        df.index = pd.DatetimeIndex([], name="date")
        return df


class _EqualWeightParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    exclude: tuple[str, ...] = ()


@register_strategy("engine-test-equal-weight")
class _EqualWeightStrategy(Strategy):
    """Equal-weights the full point-in-time universe (minus `params.exclude`,
    to exercise the unscored-name diff) - deliberately trivial so engine
    tests exercise the ENGINE, not a real signal."""

    @classmethod
    def params_model(cls) -> type[BaseModel]:
        return _EqualWeightParams

    def requires(self) -> DataRequirements:
        return DataRequirements(price_lookback_days=1, needs_universe=True)

    def generate_targets(self, ctx: Any, date: pd.Timestamp) -> TargetWeights:
        tickers = [t for t in ctx.universe() if t not in self._params.exclude]
        weights = dict.fromkeys(tickers, 1.0 / len(tickers)) if tickers else {}
        return TargetWeights(asof=date, weights=weights, strategy_id=self.strategy_id)


class _FixedWeightParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    weights: dict[str, float]


@register_strategy("engine-test-fixed-weight")
class _FixedWeightStrategy(Strategy):
    """Always returns the SAME fixed (possibly negative/short) weights,
    ignoring `ctx` entirely - for tests needing precise, controllable
    long/short positions (quant-gate VERDICT.md finding 4)."""

    @classmethod
    def params_model(cls) -> type[BaseModel]:
        return _FixedWeightParams

    def requires(self) -> DataRequirements:
        return DataRequirements(price_lookback_days=1)

    def generate_targets(self, ctx: Any, date: pd.Timestamp) -> TargetWeights:
        return TargetWeights(
            asof=date, weights=dict(self._params.weights), strategy_id=self.strategy_id
        )


def _flat_panel(sessions: pd.DatetimeIndex, tickers: dict[str, float]) -> pd.DataFrame:
    """One row per (session, ticker), FLAT close price per ticker (no
    return) - a neutral baseline fixtures override specific rows on."""
    frames = []
    for ticker, price in tickers.items():
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


def _config(**overrides) -> BacktestConfig:
    defaults = {
        "start": "2020-01-01",
        "end": "2020-05-31",
        "strategy_config": "unused.yaml",
        "rebalance_freq": "month_end",
        "execution": "close",
        "cost_model": "flat_bps",
        "one_way_cost_bps": 0.0,
        "benchmark": "BENCH",
        "abort_on_unscoreable": True,
    }
    defaults.update(overrides)
    return BacktestConfig(**defaults)


def _providers(panel: pd.DataFrame, tickers: list[str], actions=None) -> BacktestProviders:
    return BacktestProviders(
        price=_FakePriceProvider(panel),
        constituents=_FakeConstituentsProvider(tickers),
        fundamentals=_NoOpFundamentalsProvider(),
        corporate_actions=actions or _EmptyActionsProvider(),
        # A directory that never exists on disk - price_availability_from_cache
        # and the actions-fetched_at provenance lookup both degrade to
        # "no cached data" for a missing path, which is exactly right for
        # these offline, no-real-cache tests.
        cache_dir=Path("__no_such_quantlab_test_cache__"),
    )


# -- rebalance-date hygiene (acceptance criterion 5) -------------------------


def test_genuine_month_end_boundary_is_not_dropped():
    assert _is_genuine_period_boundary(pd.Timestamp("2020-01-31"), "month_end") is True


def test_non_boundary_terminal_day_is_not_a_genuine_boundary():
    # 2020-06-15 is a Monday, not a month-end.
    assert _is_genuine_period_boundary(pd.Timestamp("2020-06-15"), "month_end") is False


def test_drop_terminal_partial_period_removes_a_spurious_non_boundary_final_date():
    dates = trading_days("2020-01-01", "2020-06-15")
    from quantlab.core.calendar import rebalance_dates

    reb = rebalance_dates("2020-01-01", "2020-06-15", "month_end")
    assert reb[-1] == pd.Timestamp("2020-06-15")  # the spurious entry, pre-fix

    cleaned = _drop_terminal_partial_period(reb, "month_end")

    assert cleaned[-1] == pd.Timestamp("2020-05-29")  # last genuine month-end
    assert pd.Timestamp("2020-06-15") not in cleaned
    del dates  # unused, kept for clarity that the calendar import works


def test_drop_terminal_partial_period_keeps_a_genuine_final_boundary():
    from quantlab.core.calendar import rebalance_dates

    reb = rebalance_dates("2020-01-01", "2020-05-31", "month_end")
    cleaned = _drop_terminal_partial_period(reb, "month_end")
    assert cleaned[-1] == reb[-1] == pd.Timestamp("2020-05-29")


# -- end-to-end runs ----------------------------------------------------------


def test_run_backtest_basic_shape_and_equity_starts_at_one():
    sessions = trading_days("2019-06-01", "2020-05-31")
    panel = _flat_panel(sessions, {"AAA": 10.0, "BBB": 20.0, "BENCH": 100.0})
    providers = _providers(panel, ["AAA", "BBB"])
    strategy = _EqualWeightStrategy()
    config = _config()

    result = run_backtest(strategy, config, providers)

    assert result.net_equity.iloc[0] == pytest.approx(1.0)
    assert result.gross_equity.iloc[0] == pytest.approx(1.0)
    # Flat prices, zero cost -> every period return is exactly zero.
    assert (result.net_returns.abs() < 1e-9).all()
    assert (result.gross_returns.abs() < 1e-9).all()
    assert result.provenance["strategy_id"] == strategy.strategy_id
    assert result.provenance["data_semantics_version"] == "m03b"


def test_benchmark_first_return_date_matches_strategy_first_return_date():
    sessions = trading_days("2019-06-01", "2020-05-31")
    panel = _flat_panel(sessions, {"AAA": 10.0, "BENCH": 100.0})
    providers = _providers(panel, ["AAA"])
    result = run_backtest(_EqualWeightStrategy(), _config(), providers)

    assert result.benchmark_returns.index[0] == result.net_returns.index[0]
    assert result.benchmark_returns.index[-1] == result.net_returns.index[-1]


def test_forced_exit_books_at_last_close_with_haircut_and_counts_it():
    sessions = trading_days("2019-06-01", "2020-05-31")
    panel = _flat_panel(sessions, {"AAA": 10.0, "BBB": 20.0, "BENCH": 100.0})
    # AAA stops trading after the Feb-2020 rebalance (its series ends before
    # the March period-end) - a forced exit, not a silent drop.
    feb_end = pd.Timestamp("2020-02-28")
    panel = panel[~((panel["ticker"] == "AAA") & (panel.index > feb_end))]
    providers = _providers(panel, ["AAA", "BBB"])

    result = run_backtest(_EqualWeightStrategy(), _config(end="2020-04-30"), providers)

    assert result.quality_flags.forced_exits >= 1
    assert result.quality_flags.missing_forward_prices == result.quality_flags.forced_exits


def test_extreme_return_guard_excludes_name_and_renormalizes_book():
    """REVIEW.md finding 1 (blocker, fixed in iteration 2): the guard must
    EXCLUDE a flagged name from the period's return and RENORMALIZE the
    surviving book (old repo `compute_holding_period_return` semantics -
    the equal-weight divisor shrinks from N to N-k), NOT cap its
    contribution at 0% while keeping its original weight - the two differ
    whenever the guard fires and a survivor has a nonzero return.

    AAA/BBB start equal-weighted (0.5 each). Over the Feb->Mar holding
    period, AAA spikes >300% (extreme - excluded) while BBB gains a clean
    +10% (the return the guard must NOT dilute). A cap-at-0%-keep-weight
    policy would report `0.5*0% + 0.5*10% = 5%`; the correct exclude-and-
    renormalize policy reports `1.0*10% = 10%` - BBB's own return, at the
    book's FULL weight, once AAA is dropped and the divisor shrinks 2 -> 1.
    """
    sessions = trading_days("2019-06-01", "2020-05-31")
    panel = _flat_panel(sessions, {"AAA": 10.0, "BBB": 20.0, "BENCH": 100.0})

    feb_end = pd.Timestamp("2020-02-28")
    mar_end = pd.Timestamp("2020-03-31")
    after_feb = panel.index > feb_end
    # AAA: an extreme (>300%) spike that holds from just after Feb's
    # rebalance through March's.
    panel.loc[(panel["ticker"] == "AAA") & after_feb, "close"] = 1000.0
    panel.loc[(panel["ticker"] == "AAA") & after_feb, "adj_close"] = 1000.0
    # BBB: a genuine +10% gain over the same window.
    panel.loc[(panel["ticker"] == "BBB") & after_feb, "close"] = 22.0
    panel.loc[(panel["ticker"] == "BBB") & after_feb, "adj_close"] = 22.0

    providers = _providers(panel, ["AAA", "BBB"])
    result = run_backtest(
        _EqualWeightStrategy(), _config(end="2020-04-30", one_way_cost_bps=0.0), providers
    )

    assert result.quality_flags.extreme_returns >= 1
    assert result.gross_returns.loc[mar_end] == pytest.approx(0.10, abs=1e-9)


def test_unscored_ticker_is_recorded_when_strategy_drops_a_declared_name():
    sessions = trading_days("2019-06-01", "2020-05-31")
    panel = _flat_panel(sessions, {"AAA": 10.0, "BBB": 20.0, "BENCH": 100.0})
    providers = _providers(panel, ["AAA", "BBB"])
    strategy = _EqualWeightStrategy({"exclude": ["BBB"]})

    result = run_backtest(strategy, _config(), providers)

    assert any("BBB" in names for names in result.quality_flags.unscored_by_date.values())


def test_per_ticker_data_failure_is_dropped_and_recorded():
    sessions = trading_days("2019-06-01", "2020-05-31")
    panel = _flat_panel(sessions, {"AAA": 10.0, "BBB": 20.0, "BENCH": 100.0})
    providers = _providers(panel, ["AAA", "BBB"], actions=_HostileActionsProvider({"BBB"}))

    result = run_backtest(_EqualWeightStrategy(), _config(max_dropped_fraction=0.9), providers)

    assert any("BBB" in names for names in result.quality_flags.dropped_tickers_by_date.values())
    # A dropped ticker never reaches the strategy's universe, so it is
    # never "unscored" - it is dropped BEFORE generate_targets sees it.
    assert not any("BBB" in names for names in result.quality_flags.unscored_by_date.values())


def test_hostile_actions_provider_during_a_literal_value_strategy_rebalance():
    """REVIEW.md finding 6 (minor): the M03b carried item names the literal
    scenario "a hostile actions provider that fails for one ticker during a
    value-strategy rebalance" - `test_per_ticker_data_failure_is_dropped_and_recorded`
    above already proves the underlying mechanism
    (`_FilteringConstituentsProvider`, gated on `needs_universe and
    (price_lookback_days > 0 or fundamental_fields)`) is strategy-agnostic,
    but this confirms it holds for the literal named strategy, not a proxy
    - `ValueStrategy.requires()` declares `fundamental_fields`, which is
    exactly the condition that activates the wrapping."""
    from quantlab.strategies.value import ValueStrategy

    sessions = trading_days("2019-06-01", "2020-05-31")
    panel = _flat_panel(sessions, {"AAA": 10.0, "BBB": 20.0, "BENCH": 100.0})
    providers = _providers(panel, ["AAA", "BBB"], actions=_HostileActionsProvider({"BBB"}))

    result = run_backtest(ValueStrategy(), _config(max_dropped_fraction=0.9), providers)

    assert any("BBB" in names for names in result.quality_flags.dropped_tickers_by_date.values())


def test_per_ticker_data_failure_above_max_dropped_fraction_aborts():
    sessions = trading_days("2019-06-01", "2020-05-31")
    panel = _flat_panel(sessions, {"AAA": 10.0, "BBB": 20.0, "BENCH": 100.0})
    providers = _providers(panel, ["AAA", "BBB"], actions=_HostileActionsProvider({"AAA", "BBB"}))

    with pytest.raises(BacktestAbortError):
        run_backtest(_EqualWeightStrategy(), _config(max_dropped_fraction=0.05), providers)


def test_benchmark_failure_aborts_the_run():
    sessions = trading_days("2019-06-01", "2020-05-31")
    panel = _flat_panel(sessions, {"AAA": 10.0})  # no BENCH data at all
    providers = _providers(panel, ["AAA"])

    with pytest.raises(BacktestAbortError):
        run_backtest(_EqualWeightStrategy(), _config(), providers)


def test_unscoreable_date_aborts_by_default():
    sessions = trading_days("2019-06-01", "2020-05-31")
    panel = _flat_panel(sessions, {"AAA": 10.0, "BENCH": 100.0})
    providers = _providers(panel, ["AAA"])

    class _AlwaysRaisesParams(BaseModel):
        model_config = ConfigDict(frozen=True, extra="forbid")

    @register_strategy("engine-test-always-raises")
    class _AlwaysRaisesStrategy(Strategy):
        @classmethod
        def params_model(cls) -> type[BaseModel]:
            return _AlwaysRaisesParams

        def requires(self) -> DataRequirements:
            return DataRequirements(needs_universe=True)

        def generate_targets(self, ctx, date):
            raise ValueError("universe too thin")

    with pytest.raises(BacktestAbortError):
        run_backtest(_AlwaysRaisesStrategy(), _config(abort_on_unscoreable=True), providers)


def test_unscoreable_date_records_and_holds_prior_when_configured():
    sessions = trading_days("2019-06-01", "2020-05-31")
    panel = _flat_panel(sessions, {"AAA": 10.0, "BENCH": 100.0})
    providers = _providers(panel, ["AAA"])

    calls = {"n": 0}

    class _RaisesOnceParams(BaseModel):
        model_config = ConfigDict(frozen=True, extra="forbid")

    @register_strategy("engine-test-raises-once")
    class _RaisesOnceStrategy(Strategy):
        @classmethod
        def params_model(cls) -> type[BaseModel]:
            return _RaisesOnceParams

        def requires(self) -> DataRequirements:
            return DataRequirements(price_lookback_days=1, needs_universe=True)

        def generate_targets(self, ctx, date):
            calls["n"] += 1
            if calls["n"] == 2:
                raise ValueError("universe too thin")
            tickers = ctx.universe()
            weights = dict.fromkeys(tickers, 1.0 / len(tickers))
            return TargetWeights(asof=date, weights=weights, strategy_id=self.strategy_id)

    result = run_backtest(_RaisesOnceStrategy(), _config(abort_on_unscoreable=False), providers)

    assert len(result.quality_flags.unscoreable_dates) == 1


def test_coverage_report_is_sampled_at_rebalance_dates():
    sessions = trading_days("2019-06-01", "2020-05-31")
    panel = _flat_panel(sessions, {"AAA": 10.0, "BENCH": 100.0})
    providers = _providers(panel, ["AAA"])

    result = run_backtest(_EqualWeightStrategy(), _config(), providers)

    assert result.coverage_report.overall_bound >= 0.0
    # config spans 2020-01-01..2020-05-31, so only 2020 has sample dates.
    assert set(result.coverage_report.by_year.index) == {2020}


def test_coverage_report_surfaces_a_real_masked_truncation_end_to_end(tmp_path):
    """REVIEW.md finding 4 (blocker): acceptance criterion 7 end-to-end -
    a REAL on-disk price cache (parquet + a sidecar whose `requested_end`
    exceeds the last cached bar) must feed all the way through
    `run_backtest` into `coverage_report.masked_tickers` and move
    `overall_bound`. Every OTHER test in this file passes a nonexistent
    `cache_dir`, which never exercises `price_availability_from_cache`'s
    real file-reading path at all - this test uses `tmp_path` instead."""
    from quantlab.data.cache import price_cache_path, write_cache, write_price_cache_meta

    sessions = trading_days("2019-06-01", "2020-05-31")
    panel = _flat_panel(sessions, {"AAA": 10.0, "BENCH": 100.0})
    providers = BacktestProviders(
        price=_FakePriceProvider(panel),
        constituents=_FakeConstituentsProvider(["AAA"]),
        fundamentals=_NoOpFundamentalsProvider(),
        corporate_actions=_EmptyActionsProvider(),
        cache_dir=tmp_path,
    )

    # AAA's REAL on-disk cache stopped in 2019, but its sidecar metadata
    # claims coverage was REQUESTED through 2025 - the frozen-truncation
    # hazard plans/QUANT-NOTES.md's M01 note describes. This is entirely
    # separate from the in-memory `panel` above (which drives the
    # simulated backtest itself) - `cache_dir` is only consulted for
    # survivorship bookkeeping, mirroring how a real run's price provider
    # and its on-disk cache are the same files but a different read path.
    cached_bars = pd.DataFrame(
        {
            "ticker": ["AAA"],
            "open": [10.0],
            "high": [10.0],
            "low": [10.0],
            "close": [10.0],
            "adj_close": [10.0],
            "volume": [1000],
        },
        index=pd.DatetimeIndex(["2019-12-31"], name="date"),
    )
    write_cache(cached_bars, price_cache_path("AAA", tmp_path))
    write_price_cache_meta("AAA", "2015-01-01", "2025-12-31", tmp_path)

    result = run_backtest(_EqualWeightStrategy(), _config(), providers)

    assert any("AAA" in names for names in result.coverage_report.masked_tickers.values())
    assert result.coverage_report.overall_bound > 0.0


def test_next_open_execution_produces_a_different_result_than_close():
    # A few extra trading days past the last rebalance: `next_open` mode's
    # final fill date is the SESSION AFTER the last rebalance date, which
    # can fall past the fixture's nominal end.
    sessions = trading_days("2019-06-01", "2020-06-10")
    panel = _flat_panel(sessions, {"AAA": 10.0, "BENCH": 100.0})
    # An overnight gap right after the first rebalance: AAA's open jumps to
    # 11.0 the session after 2020-01-31 while its close stays at 10.0 that
    # day (a real, hand-computable gap).
    from quantlab.core.calendar import next_trading_day

    gap_date = next_trading_day(pd.Timestamp("2020-01-31"))
    panel.loc[(panel["ticker"] == "AAA") & (panel.index == gap_date), "open"] = 11.0

    providers_close = _providers(panel, ["AAA"])
    providers_open = _providers(panel, ["AAA"])

    close_config = _config(execution="close")
    open_config = _config(execution="next_open")
    close_result = run_backtest(_EqualWeightStrategy(), close_config, providers_close)
    open_result = run_backtest(_EqualWeightStrategy(), open_config, providers_open)

    # `close` mode fills the first rebalance at 2020-01-31's CLOSE (10.0,
    # untouched by the gap edit); `next_open` mode fills at the NEXT
    # session's OPEN (the gapped 11.0 print) - "different fills... the
    # difference equals the gap" (acceptance criterion 11), checked on the
    # actual recorded fill price (`PortfolioSnapshot.positions[...].avg_cost`),
    # not the return series (which is deliberately `adj_close`-based and so
    # column-invariant - see engine.py's module docstring; a flat-adj_close
    # fixture like this one shows the SAME reported return in both modes).
    first_reb_date = sorted(close_result.holdings_history)[0]
    close_fill = close_result.snapshots[first_reb_date].positions["AAA"].avg_cost
    open_fill = open_result.snapshots[first_reb_date].positions["AAA"].avg_cost

    assert close_fill == pytest.approx(10.0)
    assert open_fill == pytest.approx(11.0)
    assert (open_fill - close_fill) == pytest.approx(1.0)  # the hand-computed gap


def test_save_load_round_trip_on_a_real_run(tmp_path):
    sessions = trading_days("2019-06-01", "2020-05-31")
    panel = _flat_panel(sessions, {"AAA": 10.0, "BBB": 20.0, "BENCH": 100.0})
    providers = _providers(panel, ["AAA", "BBB"])
    result = run_backtest(_EqualWeightStrategy(), _config(), providers)

    result.save(tmp_path)
    from quantlab.backtest.result import BacktestResult

    loaded = BacktestResult.load(tmp_path)
    pd.testing.assert_series_equal(
        loaded.net_equity, result.net_equity, atol=1e-12, check_names=False
    )
    assert loaded.provenance == result.provenance


# ============================================================================
# Quant-gate VERDICT.md (cycle 1, REJECT) regressions - iteration 3
# ============================================================================

# -- finding 1: coverage bound over the UNIVERSE, not held names ------------


def test_coverage_bound_is_over_the_universe_not_just_held_names(tmp_path):
    """quant-gate VERDICT.md finding 1 (blocker): the gate's own
    reproduction - a fully-cached 10-name universe with a strategy holding
    only 3 of them must read `overall_bound == 0.0` (every member has
    complete data on disk), not ~70.0 (an artifact of only building
    `price_availability` from the names actually held)."""
    from quantlab.data.cache import price_cache_path, write_cache, write_price_cache_meta

    universe = [f"T{i}" for i in range(10)]
    sessions = trading_days("2019-06-01", "2020-05-31")
    price_dict = {t: 10.0 + i for i, t in enumerate(universe)}
    price_dict["BENCH"] = 100.0
    panel = _flat_panel(sessions, price_dict)

    providers = BacktestProviders(
        price=_FakePriceProvider(panel),
        constituents=_FakeConstituentsProvider(universe),
        fundamentals=_NoOpFundamentalsProvider(),
        corporate_actions=_EmptyActionsProvider(),
        cache_dir=tmp_path,
    )
    for ticker in universe:
        cached = pd.DataFrame(
            {
                "ticker": [ticker],
                "open": [10.0],
                "high": [10.0],
                "low": [10.0],
                "close": [10.0],
                "adj_close": [10.0],
                "volume": [1000],
            },
            index=pd.DatetimeIndex(["2020-05-29"], name="date"),
        )
        write_cache(cached, price_cache_path(ticker, tmp_path))
        write_price_cache_meta(ticker, "2015-01-01", "2020-05-29", tmp_path)

    strategy = _EqualWeightStrategy({"exclude": tuple(universe[3:])})  # holds only 3 of 10
    result = run_backtest(strategy, _config(), providers)

    assert result.coverage_report.overall_bound == pytest.approx(0.0)


def test_coverage_bound_detects_masked_truncation_for_a_name_never_held(tmp_path):
    """A universe member the strategy never selected, but whose cache is
    masked-truncated, must still move the coverage bound - it was a real,
    visible point-in-time constituent, just not chosen (e.g. a delisted
    name the strategy stopped holding, per the gate's follow-up check)."""
    from quantlab.data.cache import price_cache_path, write_cache, write_price_cache_meta

    universe = ["HELD", "MASKED_UNHELD"]
    sessions = trading_days("2019-06-01", "2020-05-31")
    panel = _flat_panel(sessions, {"HELD": 10.0, "MASKED_UNHELD": 20.0, "BENCH": 100.0})
    providers = BacktestProviders(
        price=_FakePriceProvider(panel),
        constituents=_FakeConstituentsProvider(universe),
        fundamentals=_NoOpFundamentalsProvider(),
        corporate_actions=_EmptyActionsProvider(),
        cache_dir=tmp_path,
    )
    held_cache = pd.DataFrame(
        {
            "ticker": ["HELD"],
            "open": [10.0],
            "high": [10.0],
            "low": [10.0],
            "close": [10.0],
            "adj_close": [10.0],
            "volume": [1000],
        },
        index=pd.DatetimeIndex(["2020-05-29"], name="date"),
    )
    write_cache(held_cache, price_cache_path("HELD", tmp_path))
    write_price_cache_meta("HELD", "2015-01-01", "2020-05-29", tmp_path)
    masked_cache = pd.DataFrame(
        {
            "ticker": ["MASKED_UNHELD"],
            "open": [20.0],
            "high": [20.0],
            "low": [20.0],
            "close": [20.0],
            "adj_close": [20.0],
            "volume": [1000],
        },
        index=pd.DatetimeIndex(["2019-06-01"], name="date"),  # real data stopped early
    )
    write_cache(masked_cache, price_cache_path("MASKED_UNHELD", tmp_path))
    # Metadata claims coverage was REQUESTED far beyond the real last bar.
    write_price_cache_meta("MASKED_UNHELD", "2015-01-01", "2025-12-31", tmp_path)

    strategy = _EqualWeightStrategy({"exclude": ("MASKED_UNHELD",)})  # never holds it
    result = run_backtest(strategy, _config(), providers)

    assert any("MASKED_UNHELD" in names for names in result.coverage_report.masked_tickers.values())
    assert result.coverage_report.overall_bound > 0.0


# -- finding 2: delisting_haircut must reach the reported return series ----


def test_delisting_haircut_reaches_the_reported_return_series():
    """quant-gate VERDICT.md finding 2 (blocker): a 50%-weighted name's
    series ends mid-period; run at three haircuts and assert `net_equity`
    moves with the haircut (previously it was inert on everything but the
    ledger). AAA is flat at 10.0 until it force-exits, so its forced-exit
    return is exactly `-haircut`; BBB is flat (0% return) throughout, so
    the period's gross return is exactly `0.5 * -haircut`."""
    sessions = trading_days("2019-06-01", "2020-05-31")
    panel = _flat_panel(sessions, {"AAA": 10.0, "BBB": 20.0, "BENCH": 100.0})
    feb_end = pd.Timestamp("2020-02-28")
    panel = panel[~((panel["ticker"] == "AAA") & (panel.index > feb_end))]

    net_equities = {}
    for haircut in (0.0, 0.5, 1.0):
        providers = _providers(panel, ["AAA", "BBB"])
        cfg = _config(end="2020-04-30", delisting_haircut=haircut, one_way_cost_bps=0.0)
        result = run_backtest(_EqualWeightStrategy(), cfg, providers)
        net_equities[haircut] = result.net_equity.loc[pd.Timestamp("2020-03-31")]

    assert net_equities[0.0] == pytest.approx(1.0)
    assert net_equities[0.5] == pytest.approx(0.75)
    assert net_equities[1.0] == pytest.approx(0.5)
    assert net_equities[1.0] < net_equities[0.5] < net_equities[0.0]


# -- finding 3: forced-exit return must be on the adj_close basis -----------


def test_forced_exit_uses_adj_close_basis_not_raw_price_for_a_reverse_split():
    """quant-gate VERDICT.md finding 3 (blocker): the gate's reverse-split
    fixture - a 1-for-10 reverse split then delisting must book ~0% (the
    holder's true economic value never changed, since `adj_close` already
    backward-adjusts for the split), not a fictitious multi-hundred-percent
    gain from dividing raw, unadjusted prices. A control run where AAA
    keeps trading after the identical split (no forced exit) isolates the
    defect to the forced-exit branch specifically."""
    sessions = trading_days("2019-06-01", "2020-05-31")
    panel = _flat_panel(sessions, {"AAA": 10.0, "BBB": 20.0, "BENCH": 100.0})

    split_date = pd.Timestamp("2020-02-10")
    last_trade = pd.Timestamp("2020-02-14")
    after_split = (panel["ticker"] == "AAA") & (panel.index >= split_date)
    # 1-for-10 reverse split: raw close jumps 10x; adj_close (already
    # backward-adjusted) stays flat - the holder's value never changed.
    panel.loc[after_split, "close"] = 100.0
    panel.loc[after_split, "adj_close"] = 10.0

    forced_exit_panel = panel[~((panel["ticker"] == "AAA") & (panel.index > last_trade))]
    control_panel = panel  # AAA keeps trading after the split - no forced exit

    forced_exit_result = run_backtest(
        _EqualWeightStrategy(),
        _config(end="2020-04-30", one_way_cost_bps=0.0),
        _providers(forced_exit_panel, ["AAA", "BBB"]),
    )
    control_result = run_backtest(
        _EqualWeightStrategy(),
        _config(end="2020-04-30", one_way_cost_bps=0.0),
        _providers(control_panel, ["AAA", "BBB"]),
    )

    period_end = pd.Timestamp("2020-02-28")
    assert forced_exit_result.net_returns.loc[period_end] == pytest.approx(0.0, abs=1e-6)
    assert control_result.net_returns.loc[period_end] == pytest.approx(0.0, abs=1e-6)
    assert forced_exit_result.quality_flags.forced_exits >= 1
    assert control_result.quality_flags.forced_exits == 0


# -- finding 4: extreme guard per-book counting + policy selection ----------


def test_extreme_guard_excludes_a_short_squeeze_under_exclude_legacy_default():
    """quant-gate VERDICT.md finding 4: ORCHESTRATOR DECISION - the guard's
    trigger is the RAW PRICE return regardless of position sign (inherited
    parity with the old repo's `long_short_engine.py`, which applies the
    identical guard to the short basket's underlying return, per-book
    counted). A shorted name squeezing +400% (genuinely adverse to the
    short) is excluded under the default "exclude_legacy" policy exactly
    like a long winner would be - counted in `extreme_returns_short`, not
    `extreme_returns_long`."""
    sessions = trading_days("2019-06-01", "2020-05-31")
    panel = _flat_panel(sessions, {"S1": 10.0, "S2": 10.0, "BENCH": 100.0})
    spike_start = pd.Timestamp("2020-02-10")
    panel.loc[(panel["ticker"] == "S1") & (panel.index >= spike_start), "close"] = 50.0
    panel.loc[(panel["ticker"] == "S1") & (panel.index >= spike_start), "adj_close"] = 50.0

    strategy = _FixedWeightStrategy({"weights": {"S1": -0.5, "S2": -0.5}})
    providers = _providers(panel, ["S1", "S2"])
    result = run_backtest(strategy, _config(end="2020-04-30", one_way_cost_bps=0.0), providers)

    assert result.quality_flags.extreme_returns_short >= 1
    assert result.quality_flags.extreme_returns_long == 0
    # S1 (the squeeze) is excluded; S2 (flat) is renormalized to the full
    # short book weight, so the reported period return hides the squeeze.
    period_return = result.gross_returns.loc[pd.Timestamp("2020-02-28")]
    assert period_return == pytest.approx(0.0, abs=1e-6)


def test_extreme_return_policy_flag_only_keeps_the_short_squeeze_loss():
    """The SAME fixture as above under `extreme_return_policy="flag_only"`:
    the trigger is still counted, but nothing is excluded - the reported
    period return shows the true, much larger squeeze loss."""
    sessions = trading_days("2019-06-01", "2020-05-31")
    panel = _flat_panel(sessions, {"S1": 10.0, "S2": 10.0, "BENCH": 100.0})
    spike_start = pd.Timestamp("2020-02-10")
    panel.loc[(panel["ticker"] == "S1") & (panel.index >= spike_start), "close"] = 50.0
    panel.loc[(panel["ticker"] == "S1") & (panel.index >= spike_start), "adj_close"] = 50.0

    strategy = _FixedWeightStrategy({"weights": {"S1": -0.5, "S2": -0.5}})
    providers = _providers(panel, ["S1", "S2"])
    cfg = _config(end="2020-04-30", one_way_cost_bps=0.0, extreme_return_policy="flag_only")
    result = run_backtest(strategy, cfg, providers)

    assert result.quality_flags.extreme_returns_short >= 1
    # True squeeze loss: -0.5*4.0 (S1) + -0.5*0.0 (S2 flat) = -2.0 (-200%).
    period_return = result.gross_returns.loc[pd.Timestamp("2020-02-28")]
    assert period_return == pytest.approx(-2.0, abs=1e-6)


def test_two_extreme_return_policies_differ_on_the_same_planted_spike():
    """Direct A/B: `exclude_legacy` and `flag_only` must give DIFFERENT
    period returns on the identical spike - proving the policy selection
    actually changes behavior, not just a config field that's ignored."""
    sessions = trading_days("2019-06-01", "2020-05-31")
    panel = _flat_panel(sessions, {"S1": 10.0, "S2": 10.0, "BENCH": 100.0})
    spike_start = pd.Timestamp("2020-02-10")
    panel.loc[(panel["ticker"] == "S1") & (panel.index >= spike_start), "close"] = 50.0
    panel.loc[(panel["ticker"] == "S1") & (panel.index >= spike_start), "adj_close"] = 50.0
    strategy_weights = {"S1": -0.5, "S2": -0.5}

    exclude_result = run_backtest(
        _FixedWeightStrategy({"weights": strategy_weights}),
        _config(end="2020-04-30", one_way_cost_bps=0.0, extreme_return_policy="exclude_legacy"),
        _providers(panel, ["S1", "S2"]),
    )
    flag_result = run_backtest(
        _FixedWeightStrategy({"weights": strategy_weights}),
        _config(end="2020-04-30", one_way_cost_bps=0.0, extreme_return_policy="flag_only"),
        _providers(panel, ["S1", "S2"]),
    )

    period_end = pd.Timestamp("2020-02-28")
    assert exclude_result.gross_returns.loc[period_end] != pytest.approx(
        flag_result.gross_returns.loc[period_end]
    )


def test_known_caveat_added_when_short_book_extreme_returns_are_excluded():
    """quant-gate VERDICT.md finding 4(b): a nonzero
    `extreme_returns_short` under the default policy must add a
    `known_caveats` entry warning that short-book performance is
    flattered."""
    sessions = trading_days("2019-06-01", "2020-05-31")
    panel = _flat_panel(sessions, {"S1": 10.0, "S2": 10.0, "BENCH": 100.0})
    spike_start = pd.Timestamp("2020-02-10")
    panel.loc[(panel["ticker"] == "S1") & (panel.index >= spike_start), "close"] = 50.0
    panel.loc[(panel["ticker"] == "S1") & (panel.index >= spike_start), "adj_close"] = 50.0

    strategy = _FixedWeightStrategy({"weights": {"S1": -0.5, "S2": -0.5}})
    providers = _providers(panel, ["S1", "S2"])
    result = run_backtest(strategy, _config(end="2020-04-30", one_way_cost_bps=0.0), providers)

    caveats = result.provenance["known_caveats"]
    assert any("short" in c.lower() and "flatter" in c.lower() for c in caveats)


def test_degenerate_book_is_recorded_when_every_name_in_a_sign_book_is_excluded():
    """quant-gate VERDICT.md finding 4, "related, same function" note: when
    EVERY name in one sign-book is excluded, that book silently contributes
    0 and the period's net exposure shifts - recorded, not silently
    absorbed."""
    sessions = trading_days("2019-06-01", "2020-05-31")
    panel = _flat_panel(sessions, {"S1": 10.0, "S2": 10.0, "BENCH": 100.0})
    spike_start = pd.Timestamp("2020-02-10")
    for ticker in ("S1", "S2"):
        panel.loc[(panel["ticker"] == ticker) & (panel.index >= spike_start), "close"] = 50.0
        panel.loc[(panel["ticker"] == ticker) & (panel.index >= spike_start), "adj_close"] = 50.0

    strategy = _FixedWeightStrategy({"weights": {"S1": -0.5, "S2": -0.5}})
    providers = _providers(panel, ["S1", "S2"])
    result = run_backtest(strategy, _config(end="2020-04-30", one_way_cost_bps=0.0), providers)

    assert any(
        "short" in books for books in result.quality_flags.degenerate_excluded_book_dates.values()
    )
    period_return = result.gross_returns.loc[pd.Timestamp("2020-02-28")]
    assert period_return == pytest.approx(0.0, abs=1e-6)


# -- finding 5: next_open must measure returns on an adjusted open basis ---


def test_next_open_return_excludes_the_fill_day_intraday_move_from_the_outgoing_book():
    """quant-gate VERDICT.md finding 5 (blocker): in `next_open` mode, a
    big intraday rally ON the fill day itself (open flat, close way up)
    must NOT be credited to the period ending AT that fill date (the
    outgoing book, which never held the position past the open) - it
    belongs to the incoming book, which bought at that session's open."""
    from quantlab.core.calendar import next_trading_day

    sessions = trading_days("2019-06-01", "2020-05-31")
    panel = _flat_panel(sessions, {"AAA": 10.0, "BENCH": 100.0})

    fill_date = next_trading_day(pd.Timestamp("2020-02-28"))
    # Fill day itself: open stays flat at 10 (no overnight gap into it),
    # but the session RALLIES to close/adj_close 20 - a move that happens
    # AFTER the next_open fill already occurred that morning.
    on_fill_day = panel.index == fill_date
    panel.loc[(panel["ticker"] == "AAA") & on_fill_day, "close"] = 20.0
    panel.loc[(panel["ticker"] == "AAA") & on_fill_day, "adj_close"] = 20.0
    # AAA re-prices permanently to 20 from the NEXT session onward, so the
    # INCOMING book (which bought at this fill day's open of 10) correctly
    # captures the move going forward.
    after_fill_day = panel.index > fill_date
    for col in ("open", "close", "adj_close"):
        panel.loc[(panel["ticker"] == "AAA") & after_fill_day, col] = 20.0

    providers = _providers(panel, ["AAA"])
    result = run_backtest(
        _EqualWeightStrategy(), _config(execution="next_open", end="2020-04-30"), providers
    )

    # The period ending AT fill_date (Jan31-decision book, held from its
    # own fill date through this one) must show ~0% - AAA was flat at 10
    # right up through this session's OPEN, which is where this period's
    # exit is priced.
    assert result.gross_returns.loc[fill_date] == pytest.approx(0.0, abs=1e-6)
