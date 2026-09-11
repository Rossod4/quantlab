"""Tests for strategies/value.py's `ValueStrategy` glue (the ported ratio/
ranking math itself is pinned against the old repo in
tests/parity/test_signal_parity.py).

Also covers the M02b VERDICT.md carried item 1 (price levels must use the
true traded price at asof, never a stale pre-split level) and the
`filing_lag_sessions` one-session filing lag, resolved via the
orchestrator-authorised `PITDataContext.fundamentals(..., filing_lag_sessions=)`
extension (data/pit.py) - see strategies/value.py's module docstring and
plans/state/M03/HANDOFF.md for the restrict-only argument; the standing
adversarial check that the lag can only narrow visible filings lives in
tests/canaries/test_lookahead.py canary (g).
"""

from __future__ import annotations

import pandas as pd
import pytest

from quantlab.core.calendar import prev_trading_day
from quantlab.core.errors import UndeclaredDataError
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
    ValueStrategy,
    _asof_raw_price,
    _fundamentals_from_ctx,
)

ASOF = pd.Timestamp("2021-04-30")


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


class _PerTickerFundamentalsProvider(FundamentalsProvider):
    def __init__(self, by_ticker: dict[str, dict]):
        self._by_ticker = by_ticker

    def get_pit_fundamentals(self, ticker: str, asof: object) -> dict:
        return dict(self._by_ticker.get(ticker, {}))


class _FactsBackedFundamentalsProvider(FundamentalsProvider):
    """Wraps the real (ported, frozen) extraction logic directly - same
    pattern as tests/canaries/test_lookahead.py - so the filing_lag_sessions
    tests below exercise real `filed`-date gating, not a fake that ignores
    it."""

    def __init__(self, facts: pd.DataFrame):
        self._facts = facts

    def get_pit_fundamentals(self, ticker: str, asof: object) -> dict:
        from dataclasses import asdict

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


def _price_row(ticker: str, date, close: float) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ticker": [ticker],
            "open": [close],
            "high": [close],
            "low": [close],
            "close": [close],
            "adj_close": [close],
            "volume": [1000],
        },
        index=pd.DatetimeIndex([date], name="date"),
    )


def _fundamentals(
    shares_outstanding=1000.0,
    stockholders_equity=5000.0,
    ttm_eps=2.0,
    ttm_ebitda=1000.0,
    total_debt=500.0,
    cash=200.0,
    annual_eps_growth=0.10,
) -> dict:
    return {
        "shares_outstanding": shares_outstanding,
        "stockholders_equity": stockholders_equity,
        "ttm_eps": ttm_eps,
        "ttm_ebitda": ttm_ebitda,
        "total_debt": total_debt,
        "cash": cash,
        "annual_eps_growth": annual_eps_growth,
    }


def _context(
    fundamentals_by_ticker: dict[str, dict],
    price_panel: pd.DataFrame,
    tickers: list[str],
    requirements: DataRequirements,
    actions: pd.DataFrame | None = None,
) -> PITDataContext:
    return PITDataContext(
        asof=ASOF,
        requirements=requirements,
        price_provider=_FakePriceProvider(price_panel),
        constituents_provider=_FakeConstituentsProvider(tickers),
        fundamentals_provider=_PerTickerFundamentalsProvider(fundamentals_by_ticker),
        corporate_actions_provider=(
            _FixedActionsProvider(actions)
            if actions is not None
            else _EmptyCorporateActionsProvider()
        ),
    )


def _basic_universe_ctx(strat: ValueStrategy) -> PITDataContext:
    tickers = ["CHEAP", "PRICEY"]
    price_panel = pd.concat([_price_row("CHEAP", ASOF, 10.0), _price_row("PRICEY", ASOF, 200.0)])
    fundamentals = {
        "CHEAP": _fundamentals(shares_outstanding=100.0, stockholders_equity=10_000.0, ttm_eps=5.0),
        "PRICEY": _fundamentals(shares_outstanding=100.0, stockholders_equity=1_000.0, ttm_eps=1.0),
    }
    return _context(fundamentals, price_panel, tickers, strat.requires())


# -- basic selection & weight sanity ------------------------------------------


def test_selects_cheaper_ticker_and_weights_sum_to_one():
    strat = ValueStrategy({"n_holdings": 1})
    ctx = _basic_universe_ctx(strat)

    result = strat.generate_targets(ctx, ASOF)

    assert result.weights == pytest.approx({"CHEAP": 1.0}, abs=1e-9)


def test_equal_weight_across_all_holdings():
    strat = ValueStrategy({"n_holdings": 2})
    ctx = _basic_universe_ctx(strat)

    result = strat.generate_targets(ctx, ASOF)

    assert set(result.weights) == {"CHEAP", "PRICEY"}
    assert result.weights["CHEAP"] == pytest.approx(0.5, abs=1e-9)
    assert sum(result.weights.values()) == pytest.approx(1.0, abs=1e-9)


def test_fundamentals_declaration_matches_what_the_strategy_uses():
    strat = ValueStrategy({})
    assert strat.requires().fundamental_fields == FUNDAMENTAL_FIELDS


def test_undeclared_fundamentals_raises_undeclared_data_error():
    """`ctx.fundamentals()` (data/pit.py) raises `UndeclaredDataError` only
    when `fundamental_fields` is empty - a strategy asking for fields it
    never declared at all, not merely "fewer than it uses" (declaring a
    strict subset silently narrows what `fundamentals()` returns instead;
    see test_fundamentals_declaration_matches_what_the_strategy_uses above
    for the real strategy's own, fully-covering declaration)."""
    strat = ValueStrategy({"n_holdings": 1})
    too_small = DataRequirements(
        price_lookback_days=1,
        fundamental_fields=frozenset(),  # nothing declared at all
        needs_universe=True,
    )
    tickers = ["CHEAP", "PRICEY"]
    price_panel = pd.concat([_price_row("CHEAP", ASOF, 10.0), _price_row("PRICEY", ASOF, 200.0)])
    fundamentals = {
        "CHEAP": _fundamentals(),
        "PRICEY": _fundamentals(),
    }
    bad_ctx = _context(fundamentals, price_panel, tickers, too_small)
    with pytest.raises(UndeclaredDataError):
        strat.generate_targets(bad_ctx, ASOF)


# -- purity -------------------------------------------------------------------


def test_generate_targets_is_pure():
    strat = ValueStrategy({"n_holdings": 1})
    ctx = _basic_universe_ctx(strat)
    assert strat.generate_targets(ctx, ASOF) == strat.generate_targets(ctx, ASOF)


# -- price levels: M02b VERDICT.md carried item 1 ----------------------------


def test_asof_raw_price_uses_the_current_row_not_a_stale_pre_split_row():
    """A level metric must price off the true traded price AT asof - never
    an older, differently-scaled price from earlier in the ticker's history
    (a pre-split filing's per-share figures never reconcile with a
    split-adjusted historical price level). This fixture gives "AAA" a
    much larger raw price several months before asof and a 5:1 split
    in between; `_asof_raw_price` must return only the asof-day price
    (100.0), never the stale pre-split one (500.0) - which it does by
    construction here (it only ever asks `ctx.prices([ticker], 1)`), but
    this test pins that contract directly against a regression that widens
    the lookback or picks the wrong row."""
    panel = pd.concat(
        [
            _price_row("AAA", "2020-06-01", 500.0),  # stale pre-split level
            _price_row("AAA", ASOF, 100.0),  # true traded price at asof
        ]
    )
    split = pd.DataFrame(
        {"ticker": ["AAA"], "action_type": ["split"], "value": [5.0]},
        index=pd.DatetimeIndex(["2021-01-15"], name="date"),
    )
    ctx = _context(
        {"AAA": _fundamentals()},
        panel,
        ["AAA"],
        DataRequirements(
            price_lookback_days=1, fundamental_fields=FUNDAMENTAL_FIELDS, needs_universe=True
        ),
        actions=split,
    )

    price = _asof_raw_price(ctx, "AAA")

    assert price == pytest.approx(100.0, abs=1e-9)


# -- filing_lag_sessions: validated, strategy_id, and now enforced ----------


def test_filing_lag_sessions_is_validated_non_negative():
    with pytest.raises(ValueError):
        ValueStrategy({"filing_lag_sessions": -1})


def test_filing_lag_sessions_changes_strategy_id():
    a = ValueStrategy({"filing_lag_sessions": 0})
    b = ValueStrategy({"filing_lag_sessions": 1})
    assert a.strategy_id != b.strategy_id


def test_filing_lag_sessions_defaults_to_one():
    strat = ValueStrategy({})
    assert strat.params["filing_lag_sessions"] == 1


def _same_day_filing_ctx() -> PITDataContext:
    """One StockholdersEquity filing filed on the prior session (val=1000.0)
    and a fresher one filed on `asof` itself (val=2000.0) - the "same-day,
    after-hours filing" hazard from M02 VERDICT.md carried item 2."""
    session_minus_1 = prev_trading_day(ASOF)
    facts = pd.DataFrame(
        [
            {
                "tag": "StockholdersEquity",
                "start": pd.NaT,
                "end": pd.Timestamp("2021-03-31"),
                "filed": session_minus_1,
                "val": 1000.0,
            },
            {
                "tag": "StockholdersEquity",
                "start": pd.NaT,
                "end": pd.Timestamp("2021-04-15"),
                "filed": ASOF,
                "val": 2000.0,
            },
        ]
    )
    return PITDataContext(
        asof=ASOF,
        requirements=DataRequirements(fundamental_fields=FUNDAMENTAL_FIELDS, needs_universe=True),
        price_provider=_FakePriceProvider(_price_row("AAA", ASOF, 20.0)),
        constituents_provider=_FakeConstituentsProvider(["AAA"]),
        fundamentals_provider=_FactsBackedFundamentalsProvider(facts),
        corporate_actions_provider=_EmptyCorporateActionsProvider(),
    )


def test_filing_lag_one_hides_a_same_day_filing_that_lag_zero_shows():
    """(a): lag=1 hides the filing filed ON asof; lag=0 shows it."""
    ctx = _same_day_filing_ctx()

    seen_at_lag_0 = _fundamentals_from_ctx(ctx, "AAA", 0)
    seen_at_lag_1 = _fundamentals_from_ctx(ctx, "AAA", 1)

    assert seen_at_lag_0.stockholders_equity == pytest.approx(2000.0)
    assert seen_at_lag_1.stockholders_equity == pytest.approx(1000.0)


def test_filing_lag_zero_matches_the_pre_extension_default_gate():
    """(b): lag=0 is exactly the old `filed <= asof` gate - byte-identical
    to calling `ctx.fundamentals()` with no lag argument at all, so every
    pre-M03 caller (including the M02 parity fixtures) is unaffected."""
    ctx = _same_day_filing_ctx()

    explicit_lag_zero = _fundamentals_from_ctx(ctx, "AAA", 0)
    no_lag_argument = ctx.fundamentals("AAA")

    assert explicit_lag_zero.stockholders_equity == no_lag_argument["stockholders_equity"]
    assert explicit_lag_zero.stockholders_equity == pytest.approx(2000.0)


def test_filing_lag_negative_raises_at_the_context_level():
    """(c): a negative lag is refused by `PITDataContext.fundamentals()`
    itself, not merely by `ValueParams`'s pydantic validation - it must be
    impossible to express, not merely unused (a negative lag would be
    look-ahead: seeing a filing filed after the decision)."""
    ctx = _same_day_filing_ctx()
    with pytest.raises(ValueError):
        ctx.fundamentals("AAA", filing_lag_sessions=-1)
