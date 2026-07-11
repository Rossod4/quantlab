from __future__ import annotations

import pandas as pd
import pytest

from quantlab.core.errors import LookaheadError, UndeclaredDataError
from quantlab.data.interfaces import (
    ConstituentsProvider,
    CorporateActionsProvider,
    FundamentalsProvider,
    PriceProvider,
)
from quantlab.data.pit import PITDataContext, _assert_no_future_dates
from quantlab.data.requirements import DataRequirements


class _FakePriceProvider(PriceProvider):
    """Ignores start/end and always returns its full fixed panel - proves
    PITDataContext itself enforces the asof bound rather than trusting the
    provider to have honored the requested window."""

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
        raise NotImplementedError


class _FakeFundamentalsProvider(FundamentalsProvider):
    def __init__(self, fixed: dict):
        self._fixed = fixed

    def get_pit_fundamentals(self, ticker: str, asof: object) -> dict:
        return dict(self._fixed)


class _FakeCorporateActionsProvider(CorporateActionsProvider):
    def __init__(self, actions: pd.DataFrame):
        self._actions = actions

    def get_actions(self, ticker: str, start: object, end: object) -> pd.DataFrame:
        start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
        return self._actions.loc[
            (self._actions.index >= start_ts) & (self._actions.index <= end_ts)
        ].copy()


def _price_panel(dates, ticker: str = "AAA", start_price: float = 100.0) -> pd.DataFrame:
    idx = pd.DatetimeIndex(dates, name="date")
    n = len(idx)
    return pd.DataFrame(
        {
            "ticker": [ticker] * n,
            "open": [start_price + i for i in range(n)],
            "high": [start_price + i + 1 for i in range(n)],
            "low": [start_price + i - 1 for i in range(n)],
            "close": [start_price + i for i in range(n)],
            "adj_close": [start_price + i - 0.5 for i in range(n)],
            "volume": [1000] * n,
        },
        index=idx,
    )


FUNDAMENTALS_FIXED = {
    "shares_outstanding": 100.0,
    "stockholders_equity": 200.0,
    "ttm_eps": 1.5,
    "ttm_ebitda": 300.0,
    "total_debt": 50.0,
    "cash": 20.0,
    "annual_eps_growth": 0.1,
}


def _empty_actions() -> pd.DataFrame:
    df = pd.DataFrame(columns=["ticker", "action_type", "value"])
    df.index = pd.DatetimeIndex([], name="date")
    return df


def _context(
    asof,
    requirements: DataRequirements,
    panel: pd.DataFrame | None = None,
    tickers: list[str] | None = None,
    fundamentals: dict | None = None,
    actions: pd.DataFrame | None = None,
) -> PITDataContext:
    if panel is None:
        panel = _price_panel(pd.bdate_range("2020-01-01", "2020-01-31"))
    if tickers is None:
        tickers = ["AAA", "BBB"]
    if fundamentals is None:
        fundamentals = FUNDAMENTALS_FIXED
    if actions is None:
        actions = _empty_actions()
    return PITDataContext(
        asof=asof,
        requirements=requirements,
        price_provider=_FakePriceProvider(panel),
        constituents_provider=_FakeConstituentsProvider(tickers),
        fundamentals_provider=_FakeFundamentalsProvider(fundamentals),
        corporate_actions_provider=_FakeCorporateActionsProvider(actions),
    )


# -- construction ---------------------------------------------------------


def test_asof_is_normalized():
    ctx = _context("2020-01-15", DataRequirements())
    assert ctx.asof == pd.Timestamp("2020-01-15")


# -- prices() / prices_for_returns() ---------------------------------------


def test_prices_caps_to_lookback_days_and_hard_slices_to_asof():
    panel = _price_panel(pd.bdate_range("2020-01-01", "2020-01-31"))
    ctx = _context("2020-01-15", DataRequirements(price_lookback_days=5), panel=panel)

    result = ctx.prices(["AAA"], 5)

    assert result.index.max() <= pd.Timestamp("2020-01-15")
    assert result.index.unique().nunique() == 5


def test_prices_excludes_rows_beyond_asof_even_when_provider_ignores_window():
    """The fake provider always returns its full panel regardless of the
    requested [start, end] - proving PITDataContext, not the provider, is
    what enforces the asof bound."""
    panel = _price_panel(pd.bdate_range("2020-01-01", "2020-03-31"))
    ctx = _context("2020-01-10", DataRequirements(price_lookback_days=5), panel=panel)

    result = ctx.prices(["AAA"], 5)

    assert (result.index <= pd.Timestamp("2020-01-10")).all()


def test_prices_never_includes_adj_close():
    panel = _price_panel(pd.bdate_range("2020-01-01", "2020-01-31"))
    ctx = _context("2020-01-15", DataRequirements(price_lookback_days=5), panel=panel)

    result = ctx.prices(["AAA"], 5)

    assert "adj_close" not in result.columns


def test_prices_for_returns_includes_adj_close():
    panel = _price_panel(pd.bdate_range("2020-01-01", "2020-01-31"))
    ctx = _context("2020-01-15", DataRequirements(price_lookback_days=5), panel=panel)

    result = ctx.prices_for_returns(["AAA"], 5)

    assert "adj_close" in result.columns
    assert (result.index <= pd.Timestamp("2020-01-15")).all()


def test_prices_more_lookback_than_declared_raises_undeclared_data_error():
    ctx = _context("2020-01-15", DataRequirements(price_lookback_days=3))
    with pytest.raises(UndeclaredDataError):
        ctx.prices(["AAA"], 5)


def test_prices_for_returns_more_lookback_than_declared_raises():
    ctx = _context("2020-01-15", DataRequirements(price_lookback_days=3))
    with pytest.raises(UndeclaredDataError):
        ctx.prices_for_returns(["AAA"], 5)


def test_prices_zero_lookback_returns_empty_frame():
    ctx = _context("2020-01-15", DataRequirements(price_lookback_days=0))
    result = ctx.prices(["AAA"], 0)
    assert result.empty


def test_prices_on_weekend_asof_uses_prior_trading_session():
    panel = _price_panel(pd.bdate_range("2020-01-01", "2020-01-31"))
    # 2020-01-18 is a Saturday; the last session on or before it is Friday
    # 2020-01-17.
    ctx = _context("2020-01-18", DataRequirements(price_lookback_days=1), panel=panel)

    result = ctx.prices(["AAA"], 1)

    assert result.index.max() == pd.Timestamp("2020-01-17")


def test_prices_excludes_non_session_rows_and_they_do_not_consume_lookback_slots():
    """REVIEW.md finding 4: a misbehaving provider injecting a NON-SESSION
    row (here a Saturday, between the last real session and a weekend asof)
    must not have that row returned, nor have it consume one of the N
    lookback slots. The slice is enforced against the exchange calendar,
    not just `<= asof`."""
    trading = pd.bdate_range("2020-01-06", "2020-01-17")  # real sessions, Mon..Fri
    panel = pd.concat(
        [
            _price_panel(trading),
            _price_panel(pd.DatetimeIndex(["2020-01-18"]), start_price=999.0),  # Saturday
        ]
    ).sort_index()
    # asof is Sunday 2020-01-19: the Saturday row is <= asof but is not a
    # trading session, so a naive `<= asof` slice would let it through.
    ctx = _context("2020-01-19", DataRequirements(price_lookback_days=3), panel=panel)

    result = ctx.prices(["AAA"], 3)

    assert pd.Timestamp("2020-01-18") not in result.index
    # All 3 slots are real sessions ending at the last session (Fri 01-17) -
    # the Saturday row did not consume a slot.
    assert list(result.index.unique().sort_values()) == [
        pd.Timestamp("2020-01-15"),
        pd.Timestamp("2020-01-16"),
        pd.Timestamp("2020-01-17"),
    ]


def test_mutating_returned_prices_frame_does_not_affect_fresh_call():
    panel = _price_panel(pd.bdate_range("2020-01-01", "2020-01-31"))
    ctx = _context("2020-01-15", DataRequirements(price_lookback_days=5), panel=panel)

    first = ctx.prices(["AAA"], 5)
    first.iloc[0, first.columns.get_loc("close")] = -999.0

    second = ctx.prices(["AAA"], 5)
    assert -999.0 not in second["close"].to_numpy()


# -- fundamentals() ---------------------------------------------------------


def test_fundamentals_undeclared_raises_undeclared_data_error():
    ctx = _context("2020-01-15", DataRequirements())
    with pytest.raises(UndeclaredDataError):
        ctx.fundamentals("AAA")


def test_fundamentals_returns_only_declared_fields():
    requirements = DataRequirements(fundamental_fields=frozenset({"ttm_eps", "cash"}))
    ctx = _context("2020-01-15", requirements)

    result = ctx.fundamentals("AAA")

    assert set(result.keys()) == {"ttm_eps", "cash"}
    assert result["ttm_eps"] == 1.5
    assert result["cash"] == 20.0


# -- universe() ---------------------------------------------------------------


def test_universe_undeclared_raises_undeclared_data_error():
    ctx = _context("2020-01-15", DataRequirements(needs_universe=False))
    with pytest.raises(UndeclaredDataError):
        ctx.universe()


def test_universe_declared_returns_membership():
    ctx = _context("2020-01-15", DataRequirements(needs_universe=True), tickers=["AAA", "BBB"])
    assert ctx.universe() == ["AAA", "BBB"]


def test_mutating_returned_universe_list_does_not_affect_fresh_call():
    ctx = _context("2020-01-15", DataRequirements(needs_universe=True), tickers=["AAA", "BBB"])
    first = ctx.universe()
    first.append("ZZZ")
    assert ctx.universe() == ["AAA", "BBB"]


# -- actions() ----------------------------------------------------------------


def test_actions_filters_to_asof():
    actions = pd.DataFrame(
        {
            "ticker": ["AAA", "AAA"],
            "action_type": ["dividend", "split"],
            "value": [0.5, 2.0],
        },
        index=pd.DatetimeIndex(["2020-01-10", "2020-02-01"], name="date"),
    )
    ctx = _context("2020-01-15", DataRequirements(needs_actions=True), actions=actions)

    result = ctx.actions("AAA")

    assert list(result.index) == [pd.Timestamp("2020-01-10")]


def test_actions_undeclared_raises_undeclared_data_error():
    ctx = _context("2020-01-15", DataRequirements(needs_actions=False))
    with pytest.raises(UndeclaredDataError):
        ctx.actions("AAA")


# -- _assert_no_future_dates (internal LookaheadError guard) ------------------


def test_assert_no_future_dates_raises_lookahead_error_on_violation():
    dates = pd.DatetimeIndex(["2020-01-01", "2020-02-01"])
    with pytest.raises(LookaheadError):
        _assert_no_future_dates(dates, pd.Timestamp("2020-01-15"), context="test")


def test_assert_no_future_dates_passes_when_all_dates_le_asof():
    dates = pd.DatetimeIndex(["2020-01-01", "2020-01-10"])
    _assert_no_future_dates(dates, pd.Timestamp("2020-01-15"), context="test")  # no raise
