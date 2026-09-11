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

from quantlab.core.calendar import prev_trading_day
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


class _AlwaysReturnsFullActionsProvider(CorporateActionsProvider):
    """Deliberately misbehaves: ignores the requested [start, end] and
    always hands back its full fixed action history, including a split
    dated well beyond any reasonable asof - the adversarial fixture for
    canary (f)."""

    def __init__(self, actions: pd.DataFrame):
        self._actions = actions

    def get_actions(self, ticker: str, start: object, end: object) -> pd.DataFrame:
        return self._actions[self._actions["ticker"] == ticker].copy()


def _minimal_context(
    asof,
    requirements: DataRequirements,
    price_provider: PriceProvider,
    fundamentals_provider: FundamentalsProvider | None = None,
    constituents_provider: ConstituentsProvider | None = None,
    corporate_actions_provider: CorporateActionsProvider | None = None,
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
        corporate_actions_provider=corporate_actions_provider or _EmptyCorporateActionsProvider(),
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


# -- (f) action with ex-date AFTER asof must have zero effect on prices() ---


def test_canary_future_dated_action_has_zero_effect_on_prices():
    """M02b / VERDICT.md's actions-canary gap: a hostile
    CorporateActionsProvider returns a split dated AFTER asof (ignoring the
    requested window, like _AlwaysReturnsFullPanelPriceProvider does for
    prices). prices() must produce a byte-identical panel whether or not
    that future split exists in the provider - the as-of adjustment replay
    (data/adjustment.py) must not know about a split the market hasn't
    announced yet as of the decision date."""
    panel = pd.DataFrame(
        {
            "ticker": ["AAA", "AAA"],
            "open": [1210.0, 1210.0],
            "high": [1210.5, 1210.5],
            "low": [1209.5, 1209.5],
            "close": [1210.0, 1210.0],
            "adj_close": [1210.0, 1210.0],
            "volume": [100, 100],
        },
        index=pd.DatetimeIndex(["2024-06-05", "2024-06-06"], name="date"),
    )
    price_provider = _AlwaysReturnsFullPanelPriceProvider(panel)
    future_split = pd.DataFrame(
        {"ticker": ["AAA"], "action_type": ["split"], "value": [10.0]},
        index=pd.DatetimeIndex(["2024-06-10"], name="date"),  # AFTER asof below
    )
    requirements = DataRequirements(price_lookback_days=2)

    ctx_with_future_split = _minimal_context(
        "2024-06-07",
        requirements,
        price_provider=price_provider,
        corporate_actions_provider=_AlwaysReturnsFullActionsProvider(future_split),
    )
    ctx_without = _minimal_context(
        "2024-06-07",
        requirements,
        price_provider=price_provider,
        corporate_actions_provider=_EmptyCorporateActionsProvider(),
    )

    with_split = ctx_with_future_split.prices(["AAA"], 2)
    without_split = ctx_without.prices(["AAA"], 2)

    pd.testing.assert_frame_equal(with_split, without_split)


# -- (g) filing_lag_sessions can only ever RESTRICT visible filings ---------


def test_canary_increasing_filing_lag_only_ever_narrows_visible_filings():
    """M03 orchestrator-authorised extension: `fundamentals(ticker, *,
    filing_lag_sessions=N)` steps its `filed <= effective_asof` gate back N
    further NYSE sessions. This exercises the REAL production extraction
    logic (`get_point_in_time_fundamentals`, via `_FactsBackedFundamentalsProvider`)
    against three StockholdersEquity filings, one filed on each of asof,
    asof's prior session, and the session before that. As `filing_lag_sessions`
    increases 0 -> 1 -> 2 -> 3, the freshest visible filing must monotonically
    fall back to the next-older one, then to none - i.e. the value visible at
    a higher lag is never a filing that was invisible at a lower lag (a
    strictly-narrowing / subset chain, never a wider one)."""
    asof = pd.Timestamp("2020-01-15")
    session_minus_1 = prev_trading_day(asof)
    session_minus_2 = prev_trading_day(session_minus_1)

    facts = pd.DataFrame(
        [
            {
                "tag": "StockholdersEquity",
                "start": pd.NaT,
                "end": pd.Timestamp("2019-12-31"),
                "filed": session_minus_2,
                "val": 100.0,
            },
            {
                "tag": "StockholdersEquity",
                "start": pd.NaT,
                "end": pd.Timestamp("2020-01-05"),
                "filed": session_minus_1,
                "val": 200.0,
            },
            {
                "tag": "StockholdersEquity",
                "start": pd.NaT,
                "end": pd.Timestamp("2020-01-10"),
                "filed": asof,
                "val": 300.0,
            },
        ]
    )
    ctx = _minimal_context(
        asof,
        DataRequirements(fundamental_fields=frozenset({"stockholders_equity"})),
        price_provider=_AlwaysReturnsFullPanelPriceProvider(pd.DataFrame()),
        fundamentals_provider=_FactsBackedFundamentalsProvider(facts),
    )

    visible_by_lag = [
        ctx.fundamentals("AAA", filing_lag_sessions=lag)["stockholders_equity"]
        for lag in (0, 1, 2, 3)
    ]

    assert visible_by_lag == [300.0, 200.0, 100.0, None]


# -- (h) a split ex-dated after asof must have zero effect on the M03b -----
# -- share-terms restatement -------------------------------------------------


def test_canary_future_dated_split_has_zero_effect_on_fundamentals_share_terms():
    """M03b (plans/M03b-share-terms.md): `fundamentals()` restates
    `shares_outstanding`/`ttm_eps` into as-of share terms using only split
    actions with ex-date in `(filed, asof]` (data/pit.py's
    `_split_factor_since_filed`, fed by `_gated_actions_by_ticker` - the
    SAME gated-to-asof actions `prices()` uses for canary (f), never a
    second raw provider call). A hostile CorporateActionsProvider ignores
    the requested window and returns a 4:1 split dated one day AFTER asof;
    `fundamentals()` must produce a byte-identical dict whether or not that
    split exists in the provider.

    Mutation-check performed manually during development (plans/state/M03b/
    HANDOFF.md records the result): widening `_gated_actions_by_ticker`'s
    hard-slice bound from `<= self._asof` to `<= self._asof + one day`
    makes this canary fail, confirming it has real power against a
    regression in the shared gate this restatement depends on."""
    filed = pd.Timestamp("2021-01-15")
    asof = pd.Timestamp("2021-03-01")
    facts = pd.DataFrame(
        [
            {
                "tag": "EntityCommonStockSharesOutstanding",
                "start": pd.NaT,
                "end": pd.Timestamp("2020-12-31"),
                "filed": filed,
                "val": 100.0,
            }
        ]
    )
    requirements = DataRequirements(fundamental_fields=frozenset({"shares_outstanding"}))
    future_split = pd.DataFrame(
        {"ticker": ["AAA"], "action_type": ["split"], "value": [4.0]},
        index=pd.DatetimeIndex([asof + pd.Timedelta(days=1)], name="date"),
    )

    ctx_with_future_split = _minimal_context(
        asof,
        requirements,
        price_provider=_AlwaysReturnsFullPanelPriceProvider(pd.DataFrame()),
        fundamentals_provider=_FactsBackedFundamentalsProvider(facts),
        corporate_actions_provider=_AlwaysReturnsFullActionsProvider(future_split),
    )
    ctx_without = _minimal_context(
        asof,
        requirements,
        price_provider=_AlwaysReturnsFullPanelPriceProvider(pd.DataFrame()),
        fundamentals_provider=_FactsBackedFundamentalsProvider(facts),
        corporate_actions_provider=_EmptyCorporateActionsProvider(),
    )

    with_split = ctx_with_future_split.fundamentals("AAA")
    without_split = ctx_without.fundamentals("AAA")

    assert with_split == without_split
    assert with_split["shares_outstanding"] == 100.0
    assert with_split["shares_outstanding_split_factor"] == 1.0
