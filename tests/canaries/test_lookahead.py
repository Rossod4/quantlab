"""Standing adversarial tests for PITDataContext's anti-look-ahead
guarantees (CLAUDE.md invariant #1 and #6: "Bias canaries ... must always
pass; extend them when adding data paths").

Each test below is written so it FAILS if its guard is removed - it asserts
on the guard's observable behavior (data excluded / column absent / a fresh
call unaffected by a prior mutation), not merely on the absence of bad data
in a clean fixture. Every fixture here is deliberately adversarial: a
future-dated price row, a filing filed after asof, etc.
"""

from __future__ import annotations

import pandas as pd

from quantlab.data.interfaces import (
    ConstituentsProvider,
    CorporateActionsProvider,
    FundamentalsProvider,
    PriceProvider,
)
from quantlab.data.pit import PITDataContext
from quantlab.data.providers.edgar_fundamentals import get_point_in_time_fundamentals
from quantlab.data.providers.sp500_constituents import _membership_from_table
from quantlab.data.requirements import DataRequirements


class _AlwaysReturnsFullPanelPriceProvider(PriceProvider):
    """Deliberately misbehaves: ignores the requested [start, end] and
    always hands back its full fixed panel, including rows dated well
    beyond any reasonable asof - the adversarial fixture for canary (a)."""

    def __init__(self, panel: pd.DataFrame):
        self._panel = panel

    def get_prices(self, tickers: list[str], start: object, end: object) -> pd.DataFrame:
        return self._panel[self._panel["ticker"].isin(tickers)].copy()


class _FactsBackedFundamentalsProvider(FundamentalsProvider):
    """Wraps the real (ported, frozen) extraction logic directly, so this
    canary exercises the actual production gating code, not a stand-in."""

    def __init__(self, facts: pd.DataFrame):
        self._facts = facts

    def get_pit_fundamentals(self, ticker: str, asof: object) -> dict:
        from dataclasses import asdict

        return asdict(get_point_in_time_fundamentals(self._facts, asof))


class _TwoRowConstituentsProvider(ConstituentsProvider):
    """Two point-in-time membership rows - the adversarial fixture for
    canary (c): asof falls strictly between them.

    `membership()` delegates to the PRODUCTION as-of lookup
    (`sp500_constituents._membership_from_table` - the exact code the real
    provider runs), so deleting or weakening the production guard makes
    canary (c) fail; a test-local reimplementation of the lookup would keep
    passing regardless. Tickers here have no dots, so the production
    normalize_ticker pass-through leaves them unchanged."""

    def __init__(self):
        self._table = pd.DataFrame(
            {"tickers": [["AAA"], ["AAA", "BBB"]]},
            index=pd.DatetimeIndex(["2020-01-01", "2020-02-01"]),
        )

    def membership(self, asof: object) -> list[str]:
        return _membership_from_table(self._table, asof)

    def membership_history(self, start: object, end: object) -> pd.DataFrame:
        return self._table


class _EmptyCorporateActionsProvider(CorporateActionsProvider):
    def get_actions(self, ticker: str, start: object, end: object) -> pd.DataFrame:
        df = pd.DataFrame(columns=["ticker", "action_type", "value"])
        df.index = pd.DatetimeIndex([], name="date")
        return df


def _minimal_context(
    asof,
    requirements: DataRequirements,
    price_provider: PriceProvider,
    fundamentals_provider: FundamentalsProvider | None = None,
    constituents_provider: ConstituentsProvider | None = None,
) -> PITDataContext:
    return PITDataContext(
        asof=asof,
        requirements=requirements,
        price_provider=price_provider,
        constituents_provider=constituents_provider or _TwoRowConstituentsProvider(),
        fundamentals_provider=fundamentals_provider
        or _FactsBackedFundamentalsProvider(
            pd.DataFrame(columns=["tag", "start", "end", "filed", "val"])
        ),
        corporate_actions_provider=_EmptyCorporateActionsProvider(),
    )


# -- (a) future-dated price row must be excluded ---------------------------


def test_canary_future_dated_price_row_is_excluded_from_prices():
    panel = pd.DataFrame(
        {
            "ticker": ["AAA", "AAA", "AAA"],
            "open": [10.0, 11.0, 999.0],
            "high": [10.5, 11.5, 999.5],
            "low": [9.5, 10.5, 998.5],
            "close": [10.0, 11.0, 999.0],
            "adj_close": [10.0, 11.0, 999.0],
            "volume": [100, 100, 100],
        },
        index=pd.DatetimeIndex(["2020-01-10", "2020-01-14", "2020-06-01"], name="date"),
    )
    provider = _AlwaysReturnsFullPanelPriceProvider(panel)
    ctx = _minimal_context(
        "2020-01-15", DataRequirements(price_lookback_days=10), price_provider=provider
    )

    result = ctx.prices(["AAA"], 10)

    assert pd.Timestamp("2020-06-01") not in result.index
    assert (result.index <= pd.Timestamp("2020-01-15")).all()


# -- (b) filing filed after asof, period before asof, must be excluded ------


def test_canary_filing_filed_after_asof_is_excluded_from_fundamentals():
    facts = pd.DataFrame(
        [
            {
                "tag": "StockholdersEquity",
                "start": pd.NaT,
                "end": pd.Timestamp("2019-12-31"),  # period BEFORE asof
                "filed": pd.Timestamp("2020-06-01"),  # filed AFTER asof
                "val": 999.0,
            }
        ]
    )
    provider = _FactsBackedFundamentalsProvider(facts)
    requirements = DataRequirements(fundamental_fields=frozenset({"stockholders_equity"}))
    ctx = _minimal_context(
        "2020-01-15",
        requirements,
        price_provider=_AlwaysReturnsFullPanelPriceProvider(pd.DataFrame()),
        fundamentals_provider=provider,
    )

    result = ctx.fundamentals("AAA")

    assert result["stockholders_equity"] is None


# -- (c) universe() between membership rows returns the earlier row only ----


def test_canary_universe_between_membership_rows_returns_earlier_row_only():
    ctx = _minimal_context(
        "2020-01-15",  # strictly between the 2020-01-01 and 2020-02-01 rows
        DataRequirements(needs_universe=True),
        price_provider=_AlwaysReturnsFullPanelPriceProvider(pd.DataFrame()),
    )

    assert ctx.universe() == ["AAA"]


# -- (d) mutating a returned frame must not affect a fresh call -------------


def test_canary_mutating_returned_frame_does_not_alter_fresh_call():
    panel = pd.DataFrame(
        {
            "ticker": ["AAA"],
            "open": [10.0],
            "high": [10.5],
            "low": [9.5],
            "close": [10.0],
            "adj_close": [10.0],
            "volume": [100],
        },
        index=pd.DatetimeIndex(["2020-01-14"], name="date"),
    )
    provider = _AlwaysReturnsFullPanelPriceProvider(panel)
    ctx = _minimal_context(
        "2020-01-15", DataRequirements(price_lookback_days=5), price_provider=provider
    )

    first = ctx.prices(["AAA"], 5)
    first.iloc[0, first.columns.get_loc("close")] = -12345.0

    second = ctx.prices(["AAA"], 5)

    assert -12345.0 not in second["close"].to_numpy()


# -- (e) signal-visible price access must not carry adj_close ---------------


def test_canary_decision_path_prices_never_carry_adj_close():
    panel = pd.DataFrame(
        {
            "ticker": ["AAA"],
            "open": [10.0],
            "high": [10.5],
            "low": [9.5],
            "close": [10.0],
            "adj_close": [7.5],  # deliberately different, to prove it isn't leaking through
            "volume": [100],
        },
        index=pd.DatetimeIndex(["2020-01-14"], name="date"),
    )
    provider = _AlwaysReturnsFullPanelPriceProvider(panel)
    ctx = _minimal_context(
        "2020-01-15", DataRequirements(price_lookback_days=5), price_provider=provider
    )

    result = ctx.prices(["AAA"], 5)

    assert "adj_close" not in result.columns
    assert "adj_close" not in result.to_dict()
