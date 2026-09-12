"""Tests for strategies/momentum.py's `MomentumStrategy` glue (the ported
signal math itself - compute_momentum_signal/select_top_n/select_bottom_n -
is pinned against the old repo in tests/parity/test_signal_parity.py, and
the close-vs-raw_close discipline is pinned by
tests/canaries/test_momentum_canary.py)."""

from __future__ import annotations

import pandas as pd
import pytest

from quantlab.core.calendar import trading_days
from quantlab.core.errors import UndeclaredDataError
from quantlab.data.interfaces import (
    ConstituentsProvider,
    CorporateActionsProvider,
    FundamentalsProvider,
    PriceProvider,
)
from quantlab.data.pit import PITDataContext
from quantlab.data.requirements import DataRequirements
from quantlab.strategies.momentum import MomentumStrategy

ASOF = pd.Timestamp("2021-04-30")
N_MONTHS = 16  # enough for lookback_months=12 + skip_months=1 + margin


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
        raise NotImplementedError


class _NoOpFundamentalsProvider(FundamentalsProvider):
    def get_pit_fundamentals(self, ticker: str, asof: object) -> dict:
        return {}


class _EmptyCorporateActionsProvider(CorporateActionsProvider):
    def get_actions(self, ticker: str, start: object, end: object) -> pd.DataFrame:
        df = pd.DataFrame(columns=["ticker", "action_type", "value"])
        df.index = pd.DatetimeIndex([], name="date")
        return df


def _sessions(lookback_days: int, asof: pd.Timestamp = ASOF) -> pd.DatetimeIndex:
    window_start = asof - pd.Timedelta(days=lookback_days * 2 + 60)
    return trading_days(window_start, asof)[-lookback_days:]


def _stepped_panel(
    sessions: pd.DatetimeIndex, rates: dict[str, float], base: float = 100.0
) -> pd.DataFrame:
    """One row per (session, ticker); each ticker's close is flat within a
    calendar month and grows by its own monthly `rate` from month to month -
    the daily-panel analogue of the old repo's month-end price fixtures
    (see tests/test_momentum.py in the old repo)."""
    months = pd.PeriodIndex(sessions, freq="M")
    unique_months = months.unique().sort_values()
    month_index = {m: i for i, m in enumerate(unique_months)}

    frames = []
    for ticker, rate in rates.items():
        closes = [base * (rate ** month_index[m]) for m in months]
        frames.append(
            pd.DataFrame(
                {
                    "ticker": [ticker] * len(sessions),
                    "open": closes,
                    "high": closes,
                    "low": closes,
                    "close": closes,
                    "adj_close": closes,
                    "volume": [1000] * len(sessions),
                },
                index=sessions,
            )
        )
    return pd.concat(frames).sort_index()


def _context(
    requirements: DataRequirements, panel: pd.DataFrame, tickers: list[str]
) -> PITDataContext:
    return PITDataContext(
        asof=ASOF,
        requirements=requirements,
        price_provider=_FakePriceProvider(panel),
        constituents_provider=_FakeConstituentsProvider(tickers),
        fundamentals_provider=_NoOpFundamentalsProvider(),
        corporate_actions_provider=_EmptyCorporateActionsProvider(),
    )


def _three_ticker_ctx(strat: MomentumStrategy) -> PITDataContext:
    requirements = strat.requires()
    sessions = _sessions(requirements.price_lookback_days)
    panel = _stepped_panel(sessions, rates={"WINNER": 1.05, "FLAT": 1.00, "LOSER": 0.96})
    return _context(requirements, panel, ["WINNER", "FLAT", "LOSER"])


# -- book selection & weight sanity (acceptance criterion 5) -----------------


def test_long_only_selects_winner_and_sums_to_one():
    strat = MomentumStrategy({"book": "long_only", "n_long": 1})
    ctx = _three_ticker_ctx(strat)

    result = strat.generate_targets(ctx, ASOF)

    assert result.weights == pytest.approx({"WINNER": 1.0}, abs=1e-9)
    assert sum(result.weights.values()) == pytest.approx(1.0, abs=1e-9)


def test_long_short_is_dollar_neutral_gross_two():
    strat = MomentumStrategy({"book": "long_short", "n_long": 1, "n_short": 1})
    ctx = _three_ticker_ctx(strat)

    result = strat.generate_targets(ctx, ASOF)

    assert result.weights["WINNER"] == pytest.approx(1.0, abs=1e-9)
    assert result.weights["LOSER"] == pytest.approx(-1.0, abs=1e-9)
    assert "FLAT" not in result.weights
    assert sum(result.weights.values()) == pytest.approx(0.0, abs=1e-9)
    assert sum(abs(w) for w in result.weights.values()) == pytest.approx(2.0, abs=1e-9)


def test_130_30_nets_one_gross_sixteen_tenths():
    strat = MomentumStrategy({"book": "130_30", "n_long": 1, "n_short": 1})
    ctx = _three_ticker_ctx(strat)

    result = strat.generate_targets(ctx, ASOF)

    assert result.weights["WINNER"] == pytest.approx(1.3, abs=1e-9)
    assert result.weights["LOSER"] == pytest.approx(-0.3, abs=1e-9)
    assert sum(result.weights.values()) == pytest.approx(1.0, abs=1e-9)
    assert sum(abs(w) for w in result.weights.values()) == pytest.approx(1.6, abs=1e-9)


def test_long_short_book_requires_positive_n_short():
    with pytest.raises(ValueError):
        MomentumStrategy({"book": "long_short", "n_short": 0})


def test_overlapping_long_and_short_selection_raises():
    strat = MomentumStrategy({"book": "long_short", "n_long": 3, "n_short": 3})
    ctx = _three_ticker_ctx(strat)  # only 3 scored names, top-3 == bottom-3
    with pytest.raises(ValueError, match="overlap"):
        strat.generate_targets(ctx, ASOF)


# -- purity & declare-vs-use --------------------------------------------------


def test_generate_targets_is_pure():
    strat = MomentumStrategy({"book": "long_only", "n_long": 1})
    ctx = _three_ticker_ctx(strat)

    assert strat.generate_targets(ctx, ASOF) == strat.generate_targets(ctx, ASOF)


# -- TargetWeights.unscored (M04b quant-gate VERDICT.md cycle 1 finding 3) --


def test_unscored_is_empty_when_every_declared_name_has_full_history():
    """A top-N selection out of a larger, FULLY-scorable universe must not
    flag any of the non-selected names as unscored - only names lacking a
    valid formation/lookback price are unscored, never a mere non-selection."""
    strat = MomentumStrategy({"book": "long_only", "n_long": 2})
    sessions = _sessions(strat.requires().price_lookback_days)
    panel = _stepped_panel(sessions, rates={"A": 1.05, "B": 1.02, "C": 0.99, "D": 1.01, "E": 1.00})
    ctx = _context(strat.requires(), panel, ["A", "B", "C", "D", "E"])

    result = strat.generate_targets(ctx, ASOF)

    assert result.unscored == {}
    # Sanity: this really is a top-2-of-5 selection, not "everyone selected".
    assert len(result.weights) == 2


def test_unscored_records_exactly_the_name_missing_a_lookback_price():
    """M04b quant-gate VERDICT.md cycle 1 finding 3 regression: a universe
    member present in `ctx.universe()` but whose price history doesn't reach
    back to the lookback month must be reported as unscored - exactly that
    name, not the whole non-selected remainder."""
    strat = MomentumStrategy({"book": "long_only", "n_long": 2})
    sessions = _sessions(strat.requires().price_lookback_days)
    full_panel = _stepped_panel(sessions, rates={"A": 1.05, "B": 1.02, "C": 0.99, "D": 1.01})
    # GAPPY only has data for its last handful of sessions - no valid price
    # at the lookback (12 months back) or even the skip (1 month back) date.
    recent_sessions = sessions[-40:]
    gappy_panel = _stepped_panel(recent_sessions, rates={"GAPPY": 1.10})
    panel = pd.concat([full_panel, gappy_panel]).sort_index()
    ctx = _context(strat.requires(), panel, ["A", "B", "C", "D", "GAPPY"])

    result = strat.generate_targets(ctx, ASOF)

    assert result.unscored == {"GAPPY": "missing formation or lookback price"}
    assert "GAPPY" not in result.weights


def test_undersized_context_raises_undeclared_data_error():
    strat = MomentumStrategy({"book": "long_only", "n_long": 1})
    too_small = DataRequirements(price_lookback_days=5, needs_universe=True)
    sessions = _sessions(5)
    panel = _stepped_panel(sessions, rates={"WINNER": 1.05, "LOSER": 0.96})
    ctx = _context(too_small, panel, ["WINNER", "LOSER"])

    with pytest.raises(UndeclaredDataError):
        strat.generate_targets(ctx, ASOF)


# -- month contiguity (M04 engine fix, carried from the M03 verdict) --------


def test_deleting_one_month_produces_an_all_nan_row_not_a_silent_13_month_lookback():
    """QUANT-NOTES.md's M03-verdict-carried item: `_month_end_prices` used
    to pivot on calendar months PRESENT in the panel, so deleting one
    month's rows silently shifted a 12-month-back lookup to 13 real months
    back for every ticker at once, rather than raising or producing a
    missing/NaN score. Deleting one interior month from the fixture must
    now leave that calendar month as an all-NaN row (old repo's
    `resample("ME").last()` semantics) so the signal for the deleted
    month's lookback offset is excluded, not silently mis-dated."""
    from quantlab.strategies.momentum import _month_end_prices

    strat = MomentumStrategy({"book": "long_only", "n_long": 1})
    requirements = strat.requires()
    sessions = _sessions(requirements.price_lookback_days)
    panel = _stepped_panel(sessions, rates={"WINNER": 1.05, "LOSER": 0.96})

    deleted_month = pd.PeriodIndex(sessions, freq="M").unique().sort_values()[3]
    keep_mask = pd.PeriodIndex(panel.index, freq="M") != deleted_month
    gapped_panel = panel.loc[keep_mask]

    wide = _month_end_prices(gapped_panel)

    deleted_month_end = deleted_month.to_timestamp(how="end").normalize()
    assert deleted_month_end in wide.index
    assert wide.loc[deleted_month_end].isna().all()
    # The index must be perfectly contiguous month-to-month around the gap -
    # no month silently vanishes.
    months = pd.PeriodIndex(wide.index, freq="M")
    assert list(months) == list(pd.period_range(months.min(), months.max(), freq="M"))
