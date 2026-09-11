"""Hand-computed parity fixtures for the M02b as-of adjustment replay
(src/quantlab/data/adjustment.py) - the binding condition recorded in
plans/state/M02/VERDICT.md carried item 1. Every expected value here is
computed by hand from the CRSP-style formula documented in adjustment.py's
module docstring, checked to a tolerance far tighter than any float64
representation error in these numbers (packet acceptance criterion 2).

Also covers packet acceptance criteria 4 (12-month momentum across a split
is ~0% for a flat-value stock, not the M02 verdict's -90% hazard) and 5
(prices() before an ex-date is unaffected by a future action existing in
the provider) end-to-end through PITDataContext. Criterion 3 (canary (f)
and its mutation check) lives in tests/canaries/test_lookahead.py, per the
work packet.
"""

from __future__ import annotations

import pandas as pd
import pytest

from quantlab.core.calendar import trading_days
from quantlab.core.errors import ActionsFetchError, DataQualityError, StaleActionsCacheError
from quantlab.data.adjustment import adjustment_factors, apply_asof_adjustment
from quantlab.data.interfaces import (
    ConstituentsProvider,
    CorporateActionsProvider,
    FundamentalsProvider,
    PriceProvider,
)
from quantlab.data.pit import PITDataContext
from quantlab.data.requirements import DataRequirements

TOL = 1e-12


def _split_action(ticker: str, ex_date: str, ratio: float) -> pd.DataFrame:
    return pd.DataFrame(
        {"ticker": [ticker], "action_type": ["split"], "value": [ratio]},
        index=pd.DatetimeIndex([ex_date], name="date"),
    )


def _dividend_action(ticker: str, ex_date: str, amount: float) -> pd.DataFrame:
    return pd.DataFrame(
        {"ticker": [ticker], "action_type": ["dividend"], "value": [amount]},
        index=pd.DatetimeIndex([ex_date], name="date"),
    )


def _raw_close_panel(ticker: str, dates_and_closes: list[tuple[str, float]]) -> pd.DataFrame:
    dates = pd.DatetimeIndex([d for d, _ in dates_and_closes], name="date")
    closes = [c for _, c in dates_and_closes]
    n = len(closes)
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
        index=dates,
    )


# -- NVDA 10:1 split ex 2024-06-10 ------------------------------------------


def test_nvda_10_for_1_split_adjusts_pre_split_price_when_asof_on_or_after_ex_date():
    panel = _raw_close_panel("NVDA", [("2024-06-07", 1210.0)])
    actions = {"NVDA": _split_action("NVDA", "2024-06-10", 10.0)}

    result = apply_asof_adjustment(panel, actions, asof="2024-06-10")

    assert result.loc["2024-06-07", "close"] == pytest.approx(121.0, abs=TOL)
    assert result.loc["2024-06-07", "raw_close"] == pytest.approx(1210.0, abs=TOL)


def test_nvda_10_for_1_split_leaves_price_unadjusted_when_asof_before_ex_date():
    """The replay must not know about a split the market hasn't announced
    yet as of the decision date - even though the (hostile/prescient) input
    actions frame already contains it."""
    panel = _raw_close_panel("NVDA", [("2024-06-07", 1210.0)])
    actions = {"NVDA": _split_action("NVDA", "2024-06-10", 10.0)}

    result = apply_asof_adjustment(panel, actions, asof="2024-06-07")

    assert result.loc["2024-06-07", "close"] == pytest.approx(1210.0, abs=TOL)


# -- AAPL 4:1 split ex 2020-08-31 (analogous) --------------------------------


def test_aapl_4_for_1_split_adjusts_pre_split_price_when_asof_on_or_after_ex_date():
    panel = _raw_close_panel("AAPL", [("2020-08-28", 500.0)])
    actions = {"AAPL": _split_action("AAPL", "2020-08-31", 4.0)}

    result = apply_asof_adjustment(panel, actions, asof="2020-08-31")

    assert result.loc["2020-08-28", "close"] == pytest.approx(125.0, abs=TOL)
    assert result.loc["2020-08-28", "raw_close"] == pytest.approx(500.0, abs=TOL)


def test_aapl_4_for_1_split_leaves_price_unadjusted_when_asof_before_ex_date():
    panel = _raw_close_panel("AAPL", [("2020-08-28", 500.0)])
    actions = {"AAPL": _split_action("AAPL", "2020-08-31", 4.0)}

    result = apply_asof_adjustment(panel, actions, asof="2020-08-28")

    assert result.loc["2020-08-28", "close"] == pytest.approx(500.0, abs=TOL)


# -- Cash dividend ------------------------------------------------------------


def test_cash_dividend_factor_hand_computed():
    """close_prev_ex = 100.0 on 2021-03-12 (last session before the
    2021-03-15 ex-date); D = 2.0 -> factor = 1 - 2/100 = 0.98."""
    close_series = pd.Series([100.0], index=pd.DatetimeIndex(["2021-03-12"]), name="close")
    actions = _dividend_action("DIVCO", "2021-03-15", 2.0)

    factors = adjustment_factors(actions, asof="2021-03-16", raw_close=close_series)

    assert factors.loc[pd.Timestamp("2021-03-15")] == pytest.approx(0.98, abs=TOL)

    panel = _raw_close_panel("DIVCO", [("2021-03-12", 100.0)])
    result = apply_asof_adjustment(panel, {"DIVCO": actions}, asof="2021-03-16")
    assert result.loc["2021-03-12", "close"] == pytest.approx(98.0, abs=TOL)


# -- Split + dividend composition across different ex-dates ------------------


def test_split_and_dividend_composition_across_ex_dates():
    """Dividend ex 2019-01-15 (close_prev_ex=50.0 on 2019-01-14, D=1.0 ->
    factor 0.98) followed by a 2:1 split ex 2019-06-03 (factor 0.5). A price
    dated before BOTH events carries the product of both factors; a price
    dated between them carries only the split factor; a price dated after
    both is untouched."""
    panel = _raw_close_panel(
        "COMBO",
        [
            ("2019-01-10", 45.0),  # before both events
            ("2019-01-14", 50.0),  # close_prev_ex for the dividend
            ("2019-03-01", 48.0),  # between the two ex-dates
            ("2019-07-01", 30.0),  # after both events
        ],
    )
    actions = pd.concat(
        [
            _dividend_action("COMBO", "2019-01-15", 1.0),
            _split_action("COMBO", "2019-06-03", 2.0),
        ]
    ).sort_index()

    result = apply_asof_adjustment(panel, {"COMBO": actions}, asof="2019-07-01")

    combined_factor = 0.98 * 0.5
    assert result.loc["2019-01-10", "close"] == pytest.approx(45.0 * combined_factor, abs=TOL)
    assert result.loc["2019-01-14", "close"] == pytest.approx(50.0 * combined_factor, abs=TOL)
    assert result.loc["2019-03-01", "close"] == pytest.approx(48.0 * 0.5, abs=TOL)
    assert result.loc["2019-07-01", "close"] == pytest.approx(30.0, abs=TOL)


def test_same_day_split_and_dividend_compose_regardless_of_row_order():
    """Split (ratio 3.0 -> factor 1/3) and dividend (close_prev_ex=40.0,
    D=4.0 -> factor 0.9) on the SAME ex-date: combined factor (1/3)*0.9=0.3,
    independent of which row appears first in the input frame."""
    close_series = pd.Series([40.0], index=pd.DatetimeIndex(["2022-04-01"]), name="close")
    dividend_first = pd.concat(
        [
            _dividend_action("SAMEDAY", "2022-04-04", 4.0),
            _split_action("SAMEDAY", "2022-04-04", 3.0),
        ]
    )
    split_first = pd.concat(
        [
            _split_action("SAMEDAY", "2022-04-04", 3.0),
            _dividend_action("SAMEDAY", "2022-04-04", 4.0),
        ]
    )

    factors_a = adjustment_factors(dividend_first, asof="2022-04-05", raw_close=close_series)
    factors_b = adjustment_factors(split_first, asof="2022-04-05", raw_close=close_series)

    expected = (1.0 / 3.0) * 0.9
    assert factors_a.loc[pd.Timestamp("2022-04-04")] == pytest.approx(expected, abs=TOL)
    assert factors_b.loc[pd.Timestamp("2022-04-04")] == pytest.approx(expected, abs=TOL)


# -- VERDICT.md M02b re-review finding 1: actions predating the panel -------


def test_apply_asof_adjustment_ignores_dividends_predating_the_panel_without_raising():
    """`pit.py` fetches a ticker's ENTIRE actions history but the price
    panel is trimmed to lookback_days - a dividend payer's ex-dates from
    years before the panel's first row used to raise ValueError computing
    close_prev_ex. Such events are output-preserving no-ops (their factor
    only applies to prices strictly before their ex-date, and none exist
    in the panel), so they must be dropped before factors are computed."""
    panel = _raw_close_panel(
        "KO", [("2024-09-03", 100.0), ("2024-09-04", 100.0), ("2024-09-05", 100.0)]
    )
    ancient_dividends = pd.concat(
        [_dividend_action("KO", ex, 0.4) for ex in ["2015-03-31", "2018-06-29", "2023-12-15"]]
    )

    result = apply_asof_adjustment(panel, {"KO": ancient_dividends}, asof="2024-09-05")

    assert result["close"].tolist() == pytest.approx([100.0, 100.0, 100.0], abs=TOL)


def test_prices_does_not_raise_for_dividend_payer_with_history_predating_lookback_window():
    """End-to-end regression for VERDICT.md finding 1, through
    PITDataContext.prices() (pit.py fetches actions from the ticker's
    entire history, not just the lookback window). A multi-year quarterly
    dividend history entirely before the panel must not crash, and a
    genuinely in-window dividend must still apply correctly."""
    ticker = "KO"
    asof = pd.Timestamp("2024-12-10")
    lookback_days = 60

    sessions = trading_days(asof - pd.Timedelta(days=lookback_days * 2 + 30), asof)[-lookback_days:]
    panel = _raw_close_panel(ticker, [(str(d.date()), 100.0) for d in sessions])

    quarterly_ex_dates = pd.date_range("2015-01-01", sessions[0] - pd.Timedelta(days=1), freq="QS")
    historical_dividends = pd.concat(
        [_dividend_action(ticker, str(d.date()), 0.4) for d in quarterly_ex_dates]
    )
    mid_date = sessions[len(sessions) // 2]
    in_panel_dividend = _dividend_action(ticker, str(mid_date.date()), 1.0)
    actions = {ticker: pd.concat([historical_dividends, in_panel_dividend]).sort_index()}

    ctx = _adjustment_context(
        asof, DataRequirements(price_lookback_days=lookback_days), panel, [ticker], actions
    )

    result = ctx.prices([ticker], lookback_days)  # must not raise

    before_mid = result.loc[result.index < mid_date, "close"].tolist()
    on_or_after_mid = result.loc[result.index >= mid_date, "close"].tolist()
    assert before_mid == pytest.approx([99.0] * len(before_mid), abs=TOL)
    assert on_or_after_mid == pytest.approx([100.0] * len(on_or_after_mid), abs=TOL)


# -- VERDICT.md M02b re-review finding 3: open/high/low adjustment ----------


def test_apply_asof_adjustment_applies_same_factor_to_open_high_low_as_close():
    """close must not sit on a different scale from open/high/low in the
    same row: the identical per-date factor is applied to all four price
    columns. volume is deliberately NOT adjusted."""
    panel = pd.DataFrame(
        {
            "ticker": ["NVDA"],
            "open": [1200.0],
            "high": [1215.0],
            "low": [1195.0],
            "close": [1210.0],
            "volume": [500000],
        },
        index=pd.DatetimeIndex(["2024-06-07"], name="date"),
    )
    actions = {"NVDA": _split_action("NVDA", "2024-06-10", 10.0)}

    result = apply_asof_adjustment(panel, actions, asof="2024-06-10")

    row = result.loc["2024-06-07"]
    assert row["open"] == pytest.approx(120.0, abs=TOL)
    assert row["high"] == pytest.approx(121.5, abs=TOL)
    assert row["low"] == pytest.approx(119.5, abs=TOL)
    assert row["close"] == pytest.approx(121.0, abs=TOL)
    assert row["volume"] == 500000  # not adjusted
    assert row["low"] <= row["close"] <= row["high"]


# -- VERDICT.md M02b re-review finding 4: non-positive factor guard ---------


def test_dividend_exceeding_close_prev_ex_raises_data_quality_error():
    """A dividend larger than close_prev_ex silently produced a negative
    adjusted price before this guard - reachable from a genuine liquidating
    distribution or a vendor dividend value in the wrong units."""
    close_series = pd.Series([40.0], index=pd.DatetimeIndex(["2022-01-03"]), name="close")
    actions = _dividend_action("OVERSIZED", "2022-01-04", 45.0)

    with pytest.raises(DataQualityError, match="OVERSIZED"):
        adjustment_factors(actions, asof="2022-01-05", raw_close=close_series)


def test_dividend_equal_to_close_prev_ex_raises_data_quality_error():
    """The exact-zero boundary: a factor of 0.0 is also refused."""
    close_series = pd.Series([40.0], index=pd.DatetimeIndex(["2022-01-03"]), name="close")
    actions = _dividend_action("ZEROED", "2022-01-04", 40.0)

    with pytest.raises(DataQualityError, match="ZEROED"):
        adjustment_factors(actions, asof="2022-01-05", raw_close=close_series)


# -- Acceptance criteria 4 & 5: end-to-end through PITDataContext -----------


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


class _RaisingActionsProvider(CorporateActionsProvider):
    """Simulates a stale or unfetchable actions history for VERDICT.md
    findings 2/5.4: prices() must propagate this, never degrade silently."""

    def __init__(self, exc: Exception):
        self._exc = exc

    def get_actions(self, ticker: str, start: object, end: object) -> pd.DataFrame:
        raise self._exc


def _adjustment_context(
    asof: object,
    requirements: DataRequirements,
    panel: pd.DataFrame,
    tickers: list[str],
    actions_by_ticker: dict[str, pd.DataFrame],
) -> PITDataContext:
    return PITDataContext(
        asof=asof,
        requirements=requirements,
        price_provider=_FixedPanelPriceProvider(panel),
        constituents_provider=_NoOpConstituentsProvider(),
        fundamentals_provider=_NoOpFundamentalsProvider(),
        corporate_actions_provider=_PerTickerActionsProvider(actions_by_ticker),
    )


def _flat_value_split_panel(
    sessions: pd.DatetimeIndex,
    split_ex_date: pd.Timestamp,
    ticker: str,
    pre_split_price: float,
    post_split_price: float,
) -> pd.DataFrame:
    """A stock whose true economic value never changes: it quotes at
    `pre_split_price` before the split and, since the split divides the
    share price by exactly the same ratio applied to the pre-split price
    below, at `post_split_price` from the ex-date onward."""
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


def test_twelve_month_momentum_across_nvda_split_is_flat_for_flat_value_stock():
    """Acceptance criterion 4 / the M02 verdict's -90% scenario, inverted:
    a 12-month momentum computed on prices() (as-of adjusted close) across
    a real 10:1 split reads ~0% for a stock whose true value never moved,
    where the same computation on raw_close reads exactly -90%."""
    ticker = "NVDA"
    split_ex_date = pd.Timestamp("2024-06-10")
    asof = pd.Timestamp("2024-12-10")
    lookback_days = 252

    all_sessions = trading_days(asof - pd.Timedelta(days=lookback_days * 2 + 30), asof)
    sessions = all_sessions[-lookback_days:]
    assert sessions.min() < split_ex_date < sessions.max(), (
        "fixture window must straddle the split for this test to be meaningful"
    )

    panel = _flat_value_split_panel(
        sessions, split_ex_date, ticker, pre_split_price=1210.0, post_split_price=121.0
    )
    actions = {ticker: _split_action(ticker, "2024-06-10", 10.0)}
    ctx = _adjustment_context(
        asof, DataRequirements(price_lookback_days=lookback_days), panel, [ticker], actions
    )

    result = ctx.prices([ticker], lookback_days)

    momentum_adjusted = result["close"].iloc[-1] / result["close"].iloc[0] - 1.0
    momentum_raw = result["raw_close"].iloc[-1] / result["raw_close"].iloc[0] - 1.0

    assert momentum_adjusted == pytest.approx(0.0, abs=TOL)
    assert momentum_raw == pytest.approx(-0.9, abs=TOL)


def test_prices_before_ex_date_identical_with_or_without_future_action_in_provider():
    """Acceptance criterion 5: prices() for asof strictly before an ex-date
    returns the same values whether or not the future action exists in the
    provider."""
    ticker = "NVDA"
    split_ex_date = pd.Timestamp("2024-06-10")
    asof = pd.Timestamp("2024-06-07")  # strictly before the ex-date

    sessions = trading_days(asof - pd.Timedelta(days=30), asof)[-5:]
    panel = _flat_value_split_panel(
        sessions, split_ex_date, ticker, pre_split_price=1210.0, post_split_price=121.0
    )
    requirements = DataRequirements(price_lookback_days=5)

    ctx_with_future_split = _adjustment_context(
        asof, requirements, panel, [ticker], {ticker: _split_action(ticker, "2024-06-10", 10.0)}
    )
    ctx_without = _adjustment_context(asof, requirements, panel, [ticker], {})

    result_with = ctx_with_future_split.prices([ticker], 5)
    result_without = ctx_without.prices([ticker], 5)

    pd.testing.assert_frame_equal(result_with, result_without)


# -- VERDICT.md M02b re-review findings 2 & 5.4: block, never degrade ------


@pytest.mark.parametrize(
    "exc",
    [
        StaleActionsCacheError("AAA: actions cache is stale"),
        ActionsFetchError("AAA: failed to fetch corporate actions"),
    ],
)
def test_prices_propagates_actions_provider_errors_end_to_end(exc):
    """The invariant 'a missing or stale actions history blocks a decision,
    never degrades it' must hold through the full PITDataContext.prices()
    path, not only at the provider - pit.py has no try/except around
    get_actions, so either error must propagate uncaught."""
    ticker = "AAA"
    panel = _raw_close_panel(ticker, [("2024-01-02", 100.0)])
    ctx = PITDataContext(
        asof="2024-01-02",
        requirements=DataRequirements(price_lookback_days=1),
        price_provider=_FixedPanelPriceProvider(panel),
        constituents_provider=_NoOpConstituentsProvider(),
        fundamentals_provider=_NoOpFundamentalsProvider(),
        corporate_actions_provider=_RaisingActionsProvider(exc),
    )

    with pytest.raises(type(exc)):
        ctx.prices([ticker], 1)
