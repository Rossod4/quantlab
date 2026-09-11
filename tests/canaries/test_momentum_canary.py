"""Standing adversarial canary for the momentum plugin (M02b VERDICT.md
carried item 2, plans/QUANT-NOTES.md "From M02b verdict"): the Strategy ABC
docstring states cross-time price signals use `close`, never `raw_close` -
this canary pins that as an executable check against the REAL production
code path (`ctx.prices()` -> `strategies.momentum._month_end_prices` ->
`compute_momentum_signal`), not a reimplementation of it.

Mutation-checked during development (see plans/state/M03/HANDOFF.md for the
result): temporarily switching `_month_end_prices` to key off `raw_close`
instead of `close` must make this test fail.
"""

from __future__ import annotations

import pandas as pd
import pytest

from quantlab.core.calendar import trading_days
from quantlab.data.interfaces import (
    ConstituentsProvider,
    CorporateActionsProvider,
    FundamentalsProvider,
    PriceProvider,
)
from quantlab.data.pit import PITDataContext
from quantlab.data.requirements import DataRequirements
from quantlab.strategies.momentum import (
    MomentumStrategy,
    _month_end_prices,
    compute_momentum_signal,
)

TOL = 1e-9


class _FixedPanelPriceProvider(PriceProvider):
    def __init__(self, panel: pd.DataFrame):
        self._panel = panel

    def get_prices(self, tickers: list[str], start: object, end: object) -> pd.DataFrame:
        return self._panel[self._panel["ticker"].isin(tickers)].copy()


class _NoOpConstituentsProvider(ConstituentsProvider):
    def membership(self, asof: object) -> list[str]:
        return []

    def membership_history(self, start: object, end: object) -> pd.DataFrame:
        raise NotImplementedError


class _NoOpFundamentalsProvider(FundamentalsProvider):
    def get_pit_fundamentals(self, ticker: str, asof: object) -> dict:
        return {}


class _PerTickerActionsProvider(CorporateActionsProvider):
    def __init__(self, actions_by_ticker: dict[str, pd.DataFrame]):
        self._actions_by_ticker = actions_by_ticker

    def get_actions(self, ticker: str, start: object, end: object) -> pd.DataFrame:
        actions = self._actions_by_ticker.get(ticker)
        if actions is None:
            df = pd.DataFrame(columns=["ticker", "action_type", "value"])
            df.index = pd.DatetimeIndex([], name="date")
            return df
        start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
        return actions.loc[(actions.index >= start_ts) & (actions.index <= end_ts)].copy()


def _flat_value_split_panel(
    sessions: pd.DatetimeIndex,
    split_ex_date: pd.Timestamp,
    ticker: str,
    pre_split_price: float,
    post_split_price: float,
) -> pd.DataFrame:
    """A stock whose true economic value never changes across its split -
    identical to tests/test_adjustment.py's fixture of the same name."""
    closes = [pre_split_price if d < split_ex_date else post_split_price for d in sessions]
    n = len(sessions)
    return pd.DataFrame(
        {
            "ticker": [ticker] * n,
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "adj_close": closes,
            "volume": [1000] * n,
        },
        index=pd.DatetimeIndex(sessions, name="date"),
    )


def test_momentum_score_across_nvda_style_split_is_flat_for_flat_value_stock():
    ticker = "NVDA"
    split_ex_date = pd.Timestamp("2024-06-10")
    asof = pd.Timestamp("2024-12-31")

    strat = MomentumStrategy(
        {"book": "long_only", "n_long": 1, "lookback_months": 12, "skip_months": 1}
    )
    lookback_days = strat.requires().price_lookback_days

    all_sessions = trading_days(asof - pd.Timedelta(days=lookback_days * 2 + 60), asof)
    sessions = all_sessions[-lookback_days:]
    assert sessions.min() < split_ex_date < sessions.max(), (
        "fixture window must straddle the split for this canary to be meaningful"
    )

    panel = _flat_value_split_panel(
        sessions, split_ex_date, ticker, pre_split_price=1210.0, post_split_price=121.0
    )
    ctx = PITDataContext(
        asof=asof,
        requirements=DataRequirements(price_lookback_days=lookback_days, needs_universe=True),
        price_provider=_FixedPanelPriceProvider(panel),
        constituents_provider=_NoOpConstituentsProvider(),
        fundamentals_provider=_NoOpFundamentalsProvider(),
        corporate_actions_provider=_PerTickerActionsProvider(
            {
                ticker: pd.DataFrame(
                    {"ticker": [ticker], "action_type": ["split"], "value": [10.0]},
                    index=pd.DatetimeIndex([split_ex_date], name="date"),
                )
            }
        ),
    )

    # Exercises the REAL production path: ctx.prices() (the as-of adjustment
    # replay) -> the momentum plugin's own month-end adapter -> the ported
    # signal formula - not a reimplementation of any of it.
    daily_panel = ctx.prices([ticker], lookback_days)
    month_end = _month_end_prices(daily_panel)
    formation_date = month_end.index[-1]
    scores = compute_momentum_signal(month_end, formation_date, lookback_months=12, skip_months=1)

    assert scores[ticker] == pytest.approx(0.0, abs=TOL)
