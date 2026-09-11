"""Tests for the M03b share-terms restatement in `PITDataContext.fundamentals()`
(data/pit.py) and its provenance fields in
data/providers/edgar_fundamentals.py - closing plans/state/M03/VERDICT.md's
MATERIAL "stale share terms" finding (see plans/M03b-share-terms.md and
plans/QUANT-NOTES.md "From M03 verdict").

The gate's canonical fixture: one 10-K files EntityCommonStockShares
Outstanding and four TTM EarningsPerShareDiluted quarters on one date, a
4:1 split happens 30 trading sessions later, and `asof` is another 30
sessions after that (well past the split). Without restatement, P/E and P/B
read 4x too cheap and the name would rank as the CHEAPEST in a composite
(VERDICT.md 4.1's measured example: 6.25 / 0.417 vs the correct 25.0 /
1.667); this file pins the restated, correct values through
`compute_value_ratios` directly.
"""

from __future__ import annotations

from dataclasses import asdict

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
from quantlab.data.providers.edgar_fundamentals import get_point_in_time_fundamentals
from quantlab.data.requirements import DataRequirements
from quantlab.strategies.value import (
    FUNDAMENTAL_FIELDS,
    _fundamentals_from_ctx,
    compute_value_ratios,
)

FILED = pd.Timestamp("2020-01-15")
_SESSIONS = trading_days(FILED, FILED + pd.Timedelta(days=400))
SPLIT_DATE = _SESSIONS[30]
ASOF = _SESSIONS[60]

RAW_PRICE_AT_ASOF = 50.0
SHARES_OUTSTANDING_FILED = 100.0
TTM_EPS_FILED = 8.0
STOCKHOLDERS_EQUITY = 12000.0
SPLIT_RATIO = 4.0  # 4-for-1: R new shares per old share (yfinance convention)


class _FakePriceProvider(PriceProvider):
    def __init__(self, panel: pd.DataFrame):
        self._panel = panel

    def get_prices(self, tickers: list[str], start: object, end: object) -> pd.DataFrame:
        return self._panel[self._panel["ticker"].isin(tickers)].copy()


class _FakeConstituentsProvider(ConstituentsProvider):
    def membership(self, asof: object) -> list[str]:
        return ["AAA"]

    def membership_history(self, start: object, end: object) -> pd.DataFrame:
        raise NotImplementedError


class _FactsBackedFundamentalsProvider(FundamentalsProvider):
    """Wraps the real (ported-frozen-plus-M03b-additive) extraction logic
    directly, so these tests exercise production filed-date provenance, not
    a fake that fabricates it - same pattern as
    tests/canaries/test_lookahead.py and tests/test_value_strategy.py."""

    def __init__(self, facts: pd.DataFrame):
        self._facts = facts

    def get_pit_fundamentals(self, ticker: str, asof: object) -> dict:
        return asdict(get_point_in_time_fundamentals(self._facts, asof))


class _EmptyCorporateActionsProvider(CorporateActionsProvider):
    def get_actions(self, ticker: str, start: object, end: object) -> pd.DataFrame:
        df = pd.DataFrame(columns=["ticker", "action_type", "value"])
        df.index = pd.DatetimeIndex([], name="date")
        return df


class _FixedActionsProvider(CorporateActionsProvider):
    def __init__(self, actions: pd.DataFrame):
        self._actions = actions

    def get_actions(self, ticker: str, start: object, end: object) -> pd.DataFrame:
        return self._actions[self._actions["ticker"] == ticker].copy()


def _facts(filed: pd.Timestamp = FILED) -> pd.DataFrame:
    quarters = [
        ("2019-01-01", "2019-03-31"),
        ("2019-04-01", "2019-06-30"),
        ("2019-07-01", "2019-09-30"),
        ("2019-10-01", "2019-12-31"),
    ]
    rows = [
        {
            "tag": "EntityCommonStockSharesOutstanding",
            "start": pd.NaT,
            "end": pd.Timestamp("2019-12-31"),
            "filed": filed,
            "val": SHARES_OUTSTANDING_FILED,
        },
        {
            "tag": "StockholdersEquity",
            "start": pd.NaT,
            "end": pd.Timestamp("2019-12-31"),
            "filed": filed,
            "val": STOCKHOLDERS_EQUITY,
        },
    ]
    for start, end in quarters:
        rows.append(
            {
                "tag": "EarningsPerShareDiluted",
                "start": pd.Timestamp(start),
                "end": pd.Timestamp(end),
                "filed": filed,
                "val": TTM_EPS_FILED / 4,
            }
        )
    return pd.DataFrame(rows)


def _price_panel(price: float = RAW_PRICE_AT_ASOF) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ticker": ["AAA"],
            "open": [price],
            "high": [price],
            "low": [price],
            "close": [price],
            "adj_close": [price],
            "volume": [1000],
        },
        index=pd.DatetimeIndex([ASOF], name="date"),
    )


def _split(ex_date: pd.Timestamp, ratio: float = SPLIT_RATIO) -> pd.DataFrame:
    return pd.DataFrame(
        {"ticker": ["AAA"], "action_type": ["split"], "value": [ratio]},
        index=pd.DatetimeIndex([ex_date], name="date"),
    )


def _context(
    actions: pd.DataFrame | None,
    facts_filed: pd.Timestamp = FILED,
    fundamental_fields: frozenset[str] = FUNDAMENTAL_FIELDS,
) -> PITDataContext:
    return PITDataContext(
        asof=ASOF,
        requirements=DataRequirements(
            price_lookback_days=1, fundamental_fields=fundamental_fields, needs_universe=True
        ),
        price_provider=_FakePriceProvider(_price_panel()),
        constituents_provider=_FakeConstituentsProvider(),
        fundamentals_provider=_FactsBackedFundamentalsProvider(_facts(facts_filed)),
        corporate_actions_provider=(
            _FixedActionsProvider(actions)
            if actions is not None
            else _EmptyCorporateActionsProvider()
        ),
    )


# -- the gate fixture: 4:1 split, 30 sessions after the filing --------------


def test_gate_fixture_pe_and_pb_correct_after_a_4_for_1_split():
    ctx = _context(_split(SPLIT_DATE))
    fund = _fundamentals_from_ctx(ctx, "AAA", 0)
    ratios = compute_value_ratios({"AAA": fund}, {"AAA": RAW_PRICE_AT_ASOF})

    assert ratios.loc["AAA", "pe"] == pytest.approx(25.0, abs=1e-9)
    assert ratios.loc["AAA", "pb"] == pytest.approx(5.0 / 3.0, abs=1e-9)

    # Sanity check against VERDICT.md 4.1's measured buggy numbers: without
    # the M03b restatement this exact fixture would have read 6.25 / 0.417.
    unrestated_pe = RAW_PRICE_AT_ASOF / TTM_EPS_FILED
    unrestated_pb = (RAW_PRICE_AT_ASOF * SHARES_OUTSTANDING_FILED) / STOCKHOLDERS_EQUITY
    assert unrestated_pe == pytest.approx(6.25, abs=1e-9)
    assert unrestated_pb == pytest.approx(0.41666667, abs=1e-6)


# -- the split window's upper bound is asof, not the lagged effective_asof --
# (M03b REVIEW.md blocking finding 1)


def test_split_at_asof_is_applied_even_with_a_filing_lag():
    """M03b REVIEW.md blocking finding 1: the split window's upper bound is
    `asof` itself, NOT the (possibly lagged) `effective_asof` that
    `filing_lag_sessions` uses for FILING visibility - the lag governs which
    FILINGS are visible, not whether a market-observable split has happened.
    At `filing_lag_sessions=1`, `effective_asof` is one session before
    `ASOF`; a split ex-dated exactly at `ASOF` (strictly after
    `effective_asof`) must still be applied. The mirror case - a split one
    session after `asof` has zero effect - is covered by canary (h) in
    tests/canaries/test_lookahead.py
    (test_canary_future_dated_split_has_zero_effect_on_fundamentals_share_terms)."""
    ctx = _context(_split(ASOF))  # split ex-dated exactly at asof

    raw = ctx.fundamentals("AAA", filing_lag_sessions=1)

    assert raw["shares_outstanding"] == pytest.approx(SHARES_OUTSTANDING_FILED * SPLIT_RATIO)
    assert raw["ttm_eps"] == pytest.approx(TTM_EPS_FILED / SPLIT_RATIO)
    assert raw["shares_outstanding_split_factor"] == pytest.approx(SPLIT_RATIO)
    assert raw["ttm_eps_split_factor"] == pytest.approx(SPLIT_RATIO)


# -- no split: identical to the pre-M03b (unrestated) output ----------------


def test_no_split_leaves_shares_and_eps_unrestated():
    ctx = _context(actions=None)

    fund = _fundamentals_from_ctx(ctx, "AAA", 0)
    assert fund.shares_outstanding == pytest.approx(SHARES_OUTSTANDING_FILED)
    assert fund.ttm_eps == pytest.approx(TTM_EPS_FILED)

    raw = ctx.fundamentals("AAA")
    assert raw["shares_outstanding_split_factor"] == pytest.approx(1.0)
    assert raw["ttm_eps_split_factor"] == pytest.approx(1.0)
    assert raw["share_terms_asof"] == ASOF


# -- split before the filing: already reflected under ASC 260, factor 1.0 --


def test_split_before_the_filing_has_zero_effect():
    ctx = _context(_split(FILED - pd.Timedelta(days=5)))

    raw = ctx.fundamentals("AAA")

    assert raw["shares_outstanding"] == pytest.approx(SHARES_OUTSTANDING_FILED)
    assert raw["ttm_eps"] == pytest.approx(TTM_EPS_FILED)
    assert raw["shares_outstanding_split_factor"] == pytest.approx(1.0)
    assert raw["ttm_eps_split_factor"] == pytest.approx(1.0)


def test_split_exactly_on_the_filing_date_has_zero_effect():
    """Boundary case for the `(filed, asof]` window (gate-mandated, quant-
    gate VERDICT.md): a split ex-dated exactly ON the filing date is
    already reflected in that filing's per-share figures under ASC 260, so
    the window is strictly `filed < ex_date`, not `filed <= ex_date` - see
    data/pit.py's `_split_factor_since_filed` docstring. Same-day is the
    "already restated" side of the boundary."""
    ctx = _context(_split(FILED))

    raw = ctx.fundamentals("AAA")

    assert raw["shares_outstanding"] == pytest.approx(SHARES_OUTSTANDING_FILED)
    assert raw["ttm_eps"] == pytest.approx(TTM_EPS_FILED)
    assert raw["shares_outstanding_split_factor"] == pytest.approx(1.0)
    assert raw["ttm_eps_split_factor"] == pytest.approx(1.0)


def test_split_one_day_after_the_filing_date_is_applied():
    """The other side of the same boundary: one day after the filing date
    is strictly after `filed`, so the split IS in the window and must be
    applied at the full ratio."""
    ctx = _context(_split(FILED + pd.Timedelta(days=1)))

    raw = ctx.fundamentals("AAA")

    assert raw["shares_outstanding"] == pytest.approx(SHARES_OUTSTANDING_FILED * SPLIT_RATIO)
    assert raw["ttm_eps"] == pytest.approx(TTM_EPS_FILED / SPLIT_RATIO)
    assert raw["shares_outstanding_split_factor"] == pytest.approx(SPLIT_RATIO)
    assert raw["ttm_eps_split_factor"] == pytest.approx(SPLIT_RATIO)


# -- two splits after the filing compose -------------------------------------


def test_two_splits_after_filing_compose():
    two_splits = pd.concat([_split(SPLIT_DATE, ratio=2.0), _split(_SESSIONS[45], ratio=3.0)])
    ctx = _context(two_splits)

    raw = ctx.fundamentals("AAA")

    assert raw["shares_outstanding_split_factor"] == pytest.approx(6.0)
    assert raw["ttm_eps_split_factor"] == pytest.approx(6.0)
    assert raw["shares_outstanding"] == pytest.approx(SHARES_OUTSTANDING_FILED * 6.0)
    assert raw["ttm_eps"] == pytest.approx(TTM_EPS_FILED / 6.0)


# -- a split ex-dated after asof has zero effect -----------------------------


def test_split_after_asof_has_zero_effect():
    ctx = _context(_split(_SESSIONS[61]))  # one session after ASOF (_SESSIONS[60])

    raw = ctx.fundamentals("AAA")

    assert raw["shares_outstanding"] == pytest.approx(SHARES_OUTSTANDING_FILED)
    assert raw["ttm_eps"] == pytest.approx(TTM_EPS_FILED)
    assert raw["shares_outstanding_split_factor"] == pytest.approx(1.0)
    assert raw["ttm_eps_split_factor"] == pytest.approx(1.0)


# -- provenance keys are declaration-gated -----------------------------------


def test_provenance_keys_absent_when_neither_share_term_field_declared():
    ctx = _context(_split(SPLIT_DATE), fundamental_fields=frozenset({"stockholders_equity"}))

    raw = ctx.fundamentals("AAA")

    assert "shares_outstanding_split_factor" not in raw
    assert "ttm_eps_split_factor" not in raw
    assert "share_terms_asof" not in raw
    assert raw["stockholders_equity"] == pytest.approx(STOCKHOLDERS_EQUITY)


def test_provenance_key_present_only_for_the_declared_share_term_field():
    """Declaring only `shares_outstanding` (not `ttm_eps`) must yield only
    the `shares_outstanding_split_factor` key - the split into two
    independent per-field keys (M03b REVIEW.md finding 2) means each key is
    gated on its OWN field's declaration, not on "either field"."""
    ctx = _context(_split(SPLIT_DATE), fundamental_fields=frozenset({"shares_outstanding"}))

    raw = ctx.fundamentals("AAA")

    assert raw["shares_outstanding_split_factor"] == pytest.approx(4.0)
    assert "ttm_eps_split_factor" not in raw
    assert raw["share_terms_asof"] == ASOF
