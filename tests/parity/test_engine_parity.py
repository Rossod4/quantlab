"""Engine parity (work packet acceptance criterion 2): the NEW generic
engine, run in `close` mode on the M03 momentum plugin, must reproduce
`net_returns`/`net_equity` to 1e-10 against a REFERENCE re-implementation of
the OLD REPO's monthly rebalance loop - a true cross-implementation check,
per the work packet's own instruction for THIS test (unlike
tests/parity/test_signal_parity.py, which deliberately uses hard-coded
golden numbers instead - see that file's docstring for why a sys.path
import is the wrong choice for a pure-function pin. A full LOOP's wiring is
what's under test here, not one function's arithmetic, so hand-deriving 23
periods' worth of golden numbers would be both laborious and fragile to
insignificant fixture tweaks; importing the old repo's OWN loop pieces is
the more robust choice for exactly this test.).

## Bridged conventions (documented per the work packet's acceptance
criterion 2 instruction)

1. **Return-date indexing / calendar labeling.** The old repo builds its
   month-end panel via `daily_prices.resample(freq).last()`, which labels
   each bucket with the CALENDAR month's last day - not necessarily an NYSE
   trading session (a calendar month-end falling on a weekend would get a
   non-trading-day label). The new engine's `core.calendar.rebalance_dates`
   always labels with the actual last NYSE SESSION of the month. This is a
   purely mechanical labeling difference, unrelated to the signal/cost
   numerics under test, so the reference loop below is built directly on
   `core.calendar.rebalance_dates`' own NYSE session dates (never on
   `pd.date_range`/`resample`) - both implementations therefore share
   IDENTICAL month-end date labels by construction, and the test verifies
   the arithmetic wiring, not calendar-labeling trivia.
2. **First-rebalance turnover.** `costs.compute_turnover`'s empty-old-book
   special case (1.0, matching the old repo's `compute_turnover([], new,
   top_n)`) - see costs.py's docstring - is what makes period-1 parity
   possible at all; without it the new engine's general weight-vector
   formula would give 0.5, not 1.0, for the very first rebalance.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from quantlab.backtest.config import BacktestConfig
from quantlab.backtest.engine import BacktestProviders, run_backtest
from quantlab.core.calendar import rebalance_dates, trading_days
from quantlab.data.interfaces import (
    ConstituentsProvider,
    CorporateActionsProvider,
    FundamentalsProvider,
    PriceProvider,
)
from quantlab.strategies.momentum import MomentumStrategy

_OLD_REPO_ROOT = Path(r"C:\Users\arwga\Developer\ClaudeProjects\Trading\MomentumValueStrategy")

_TICKERS = ["T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8"]
_BENCHMARK = "BENCH"
# Ascending monthly growth rates - T8 (highest) only becomes eligible after
# the constituents switch below, so the top-N selection changes EXACTLY
# once (at the switch), giving one clean, hand-traceable turnover/cost
# event alongside many zero-turnover periods - no delistings, no extreme
# returns (all well under EXTREME_MONTHLY_RETURN_BOUND=3.0), per the work
# packet's parity-fixture spec.
_GROWTH = {
    "T1": 0.998,
    "T2": 1.001,
    "T3": 1.004,
    "T4": 1.007,
    "T5": 1.010,
    "T6": 1.013,
    "T7": 1.016,
    "T8": 1.020,
    _BENCHMARK: 1.005,
}
_N_LONG = 3
_ONE_WAY_COST_BPS = 10.0
_LOOKBACK_MONTHS = 12
_SKIP_MONTHS = 1

_WARMUP_START = "2018-01-01"
_BACKTEST_START = pd.Timestamp("2020-01-01")
_BACKTEST_END = pd.Timestamp("2021-12-31")
# One join (T8), one leave (T1), effective at this rebalance - "constituents
# table with one join and one leave" per the work packet's fixture spec.
_SWITCH_DATE = pd.Timestamp("2021-01-31")


def _month_level(
    period: pd.Period, ticker: str, overrides: dict[tuple[pd.Period, str], float] | None = None
) -> float:
    """Ticker's synthetic price level in calendar month `period`, relative
    to an arbitrary epoch month - a fixed monthly growth rate compounded
    (see `_GROWTH`), UNLESS `(period, ticker)` has an explicit `overrides`
    entry (used by the single-period extreme-return fixture below to plant
    a one-month spike without disturbing any other month's level - later
    months are unaffected since this function is not path-dependent)."""
    if overrides is not None and (period, ticker) in overrides:
        return overrides[(period, ticker)]
    epoch = pd.Period("2018-01", freq="M")
    months = (period.year - epoch.year) * 12 + (period.month - epoch.month)
    return 100.0 * (_GROWTH[ticker] ** months)


def _membership_at(history: pd.DataFrame, asof: pd.Timestamp) -> list[str]:
    idx = history.index[history.index <= asof]
    if len(idx) == 0:
        return []
    return list(history.loc[idx.max(), "tickers"])


def _constituents_history() -> pd.DataFrame:
    return pd.DataFrame(
        {"tickers": [_TICKERS[:7], _TICKERS[1:8]]},  # [T1..T7] -> [T2..T8]
        index=pd.DatetimeIndex([pd.Timestamp(_WARMUP_START), _SWITCH_DATE]),
    )


class _FakePriceProvider(PriceProvider):
    def __init__(self, panel: pd.DataFrame):
        self._panel = panel

    def get_prices(self, tickers: list[str], start: object, end: object) -> pd.DataFrame:
        return self._panel[self._panel["ticker"].isin(tickers)].copy()


class _PITConstituentsProvider(ConstituentsProvider):
    def __init__(self, history: pd.DataFrame):
        self._history = history

    def membership(self, asof: object) -> list[str]:
        return _membership_at(self._history, pd.Timestamp(asof))

    def membership_history(self, start: object, end: object) -> pd.DataFrame:
        return self._history


class _NoOpFundamentalsProvider(FundamentalsProvider):
    def get_pit_fundamentals(self, ticker: str, asof: object) -> dict:
        return {}


class _EmptyActionsProvider(CorporateActionsProvider):
    def get_actions(self, ticker: str, start: object, end: object) -> pd.DataFrame:
        df = pd.DataFrame(columns=["ticker", "action_type", "value"])
        df.index = pd.DatetimeIndex([], name="date")
        return df


def _wide_month_end_reference(
    overrides: dict[tuple[pd.Period, str], float] | None = None,
) -> pd.DataFrame:
    """The reference loop's wide (NYSE-month-end-date x ticker) panel -
    built directly on `core.calendar.rebalance_dates`, never
    `pd.date_range`/`resample` (see this module's docstring, bridged
    convention 1)."""
    dates = rebalance_dates(_WARMUP_START, _BACKTEST_END, "month_end")
    all_tickers = [*_TICKERS, _BENCHMARK]
    rows = {
        d: {t: _month_level(pd.Period(d, freq="M"), t, overrides) for t in all_tickers}
        for d in dates
    }
    return pd.DataFrame.from_dict(rows, orient="index").sort_index()


def _daily_panel(overrides: dict[tuple[pd.Period, str], float] | None = None) -> pd.DataFrame:
    """Long daily OHLCV panel for `PITDataContext` - flat within each
    calendar month at that month's `_month_level` (mirrors
    tests/test_momentum_strategy.py's `_stepped_panel` construction), so
    momentum.py's `_month_end_prices` (last close of each calendar month)
    reproduces the SAME levels as `_wide_month_end_reference` exactly."""
    sessions = trading_days(_WARMUP_START, _BACKTEST_END)
    periods = pd.PeriodIndex(sessions, freq="M")
    frames = []
    for ticker in [*_TICKERS, _BENCHMARK]:
        closes = [_month_level(p, ticker, overrides) for p in periods]
        frames.append(
            pd.DataFrame(
                {
                    "ticker": [ticker] * len(sessions),
                    "open": closes,
                    "high": closes,
                    "low": closes,
                    "close": closes,
                    "adj_close": closes,
                    "volume": [10_000] * len(sessions),
                },
                index=sessions,
            )
        )
    return pd.concat(frames).sort_index()


def _run_reference_loop(month_end_prices: pd.DataFrame, constituents_history: pd.DataFrame):
    """Faithful re-implementation of the old repo's `run_backtest` monthly
    loop, calling the OLD REPO's OWN (frozen, ported) functions via a
    sys.path import - see this module's docstring."""
    sys.path.insert(0, str(_OLD_REPO_ROOT))
    try:
        from src.backtest.engine import compute_holding_period_return
        from src.costs.transaction_costs import apply_transaction_costs, compute_turnover
        from src.strategy.momentum import compute_momentum_signal, select_top_n
    finally:
        sys.path.remove(str(_OLD_REPO_ROOT))

    month_end_prices = month_end_prices.loc[month_end_prices.index <= _BACKTEST_END]
    eligible_formation_dates = [d for d in month_end_prices.index if d >= _BACKTEST_START]

    gross_returns: dict[pd.Timestamp, float] = {}
    net_returns: dict[pd.Timestamp, float] = {}
    old_portfolio: list[str] = []

    for formation_date in eligible_formation_dates:
        idx = month_end_prices.index.get_loc(formation_date)
        if idx + 1 >= len(month_end_prices.index):
            break
        next_date = month_end_prices.index[idx + 1]

        membership_t = _membership_at(constituents_history, formation_date)

        try:
            scores = compute_momentum_signal(
                month_end_prices, formation_date, _LOOKBACK_MONTHS, _SKIP_MONTHS
            )
        except ValueError:
            continue

        eligible_scores = scores[scores.index.isin(membership_t)]
        new_portfolio = select_top_n(eligible_scores, _N_LONG)
        if not new_portfolio:
            continue

        turnover = compute_turnover(old_portfolio, new_portfolio, len(new_portfolio))
        formation_prices = month_end_prices.loc[formation_date, new_portfolio]
        next_prices = month_end_prices.loc[next_date, new_portfolio]
        gross_return, _missing, _extreme = compute_holding_period_return(
            formation_prices, next_prices
        )
        net_return = apply_transaction_costs(gross_return, turnover, _ONE_WAY_COST_BPS)

        gross_returns[next_date] = gross_return
        net_returns[next_date] = net_return
        old_portfolio = new_portfolio

    net_returns_s = pd.Series(net_returns, dtype=float).sort_index()
    net_equity_s = (1 + net_returns_s).cumprod()
    return net_returns_s, net_equity_s


def _run_both_and_assert_parity(overrides: dict[tuple[pd.Period, str], float] | None = None):
    """Shared driver: build both implementations off the SAME (optionally
    spike-overridden) synthetic panel and assert `net_returns`/`net_equity`
    agree to 1e-10 - used both by the baseline parity test and by the
    single-period extreme-return fixture below (REVIEW.md finding 1)."""
    constituents_history = _constituents_history()
    reference_net_returns, reference_net_equity = _run_reference_loop(
        _wide_month_end_reference(overrides), constituents_history
    )
    assert len(reference_net_returns) > 5  # sanity: the fixture exercises multiple periods

    providers = BacktestProviders(
        price=_FakePriceProvider(_daily_panel(overrides)),
        constituents=_PITConstituentsProvider(constituents_history),
        fundamentals=_NoOpFundamentalsProvider(),
        corporate_actions=_EmptyActionsProvider(),
        cache_dir=Path("__no_such_quantlab_parity_cache__"),
    )
    strategy = MomentumStrategy(
        {
            "book": "long_only",
            "n_long": _N_LONG,
            "lookback_months": _LOOKBACK_MONTHS,
            "skip_months": _SKIP_MONTHS,
        }
    )
    config = BacktestConfig(
        start=_BACKTEST_START,
        end=_BACKTEST_END,
        strategy_config="unused.yaml",
        rebalance_freq="month_end",
        execution="close",
        cost_model="flat_bps",
        one_way_cost_bps=_ONE_WAY_COST_BPS,
        benchmark=_BENCHMARK,
    )

    result = run_backtest(strategy, config, providers)

    pd.testing.assert_series_equal(
        result.net_returns, reference_net_returns, check_exact=False, atol=1e-10, check_names=False
    )
    pd.testing.assert_series_equal(
        result.net_equity.loc[reference_net_equity.index],
        reference_net_equity,
        check_exact=False,
        atol=1e-10,
        check_names=False,
    )
    return reference_net_returns


def test_new_engine_matches_reference_loop_to_1e_minus_10():
    _run_both_and_assert_parity()


def test_new_engine_matches_reference_with_a_single_period_extreme_return_spike():
    """REVIEW.md finding 1 (blocker): the extreme-return guard must EXCLUDE
    a flagged name from that period's return (shrinking the equal-weight
    divisor from N to N-k), not cap its contribution at 0% while keeping
    its weight - those are different numbers whenever the guard fires. T6
    is a stable top-3 (holding) pick pre-switch (see `_GROWTH`); spiking
    ONLY its 2020-06 month-end level to 5x plants a May->June return of
    ~400%, well past `extreme_return_bound` (default 3.0 = 300%). The old
    reference loop's OWN `compute_holding_period_return` naturally excludes
    T6 that period (dropping the equal-weight divisor from 3 to 2) - if the
    new engine's guard does anything other than exactly that, this fixture
    diverges from the reference by far more than 1e-10 (a factor of 3/2 on
    the affected period, propagating through every later equity value)."""
    spike_period = pd.Period("2020-06", freq="M")
    spiked_level = _month_level(spike_period, "T6") * 5.0
    overrides = {(spike_period, "T6"): spiked_level}

    # Confirm the fixture actually plants what it claims before trusting
    # the parity assertion to mean anything.
    prior_level = _month_level(pd.Period("2020-05", freq="M"), "T6")
    assert (spiked_level / prior_level - 1.0) > 3.0

    _run_both_and_assert_parity(overrides)


def test_fixture_has_a_nonzero_turnover_event_at_the_constituents_switch():
    """Sanity check on the fixture itself (not the engine): confirms the
    membership switch actually changes the top-N selection, so the parity
    test above is exercising real turnover/cost arithmetic at least once,
    not only degenerate zero-turnover periods."""
    reference = _wide_month_end_reference()
    constituents_history = _constituents_history()
    _, net_returns_and_equity = _run_reference_loop(reference, constituents_history)
    del net_returns_and_equity

    before = _membership_at(constituents_history, _SWITCH_DATE - pd.Timedelta(days=1))
    at_switch = _membership_at(constituents_history, _SWITCH_DATE)
    assert before == _TICKERS[:7]
    assert at_switch == _TICKERS[1:8]
    assert set(before) != set(at_switch)
