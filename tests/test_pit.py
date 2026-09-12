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
    accounting: bool = False,
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
        accounting=accounting,
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
    ctx = _context(
        "2020-01-15", DataRequirements(price_lookback_days=5), panel=panel, accounting=True
    )

    result = ctx.prices_for_returns(["AAA"], 5)

    assert "adj_close" in result.columns
    assert (result.index <= pd.Timestamp("2020-01-15")).all()


def test_prices_more_lookback_than_declared_raises_undeclared_data_error():
    ctx = _context("2020-01-15", DataRequirements(price_lookback_days=3))
    with pytest.raises(UndeclaredDataError):
        ctx.prices(["AAA"], 5)


def test_prices_for_returns_more_lookback_than_declared_raises():
    ctx = _context("2020-01-15", DataRequirements(price_lookback_days=3), accounting=True)
    with pytest.raises(UndeclaredDataError):
        ctx.prices_for_returns(["AAA"], 5)


# -- accounting=True gate (M04 HANDOFF.3 follow-up to quant-gate VERDICT.md,
# cycle 1 non-blocking note) -------------------------------------------------


def test_prices_for_returns_raises_on_a_non_accounting_context_by_default():
    """The DECISION-path default (`accounting=False`) blocks
    `prices_for_returns()` outright, by construction - previously any
    context, including the one a strategy's own `generate_targets`
    receives, could call this and get `adj_close` plus raw OHL with only
    convention standing in the way."""
    ctx = _context("2020-01-15", DataRequirements(price_lookback_days=5))
    with pytest.raises(UndeclaredDataError):
        ctx.prices_for_returns(["AAA"], 5)


def test_prices_for_returns_succeeds_on_an_accounting_true_context():
    ctx = _context("2020-01-15", DataRequirements(price_lookback_days=5), accounting=True)
    result = ctx.prices_for_returns(["AAA"], 5)
    assert "adj_close" in result.columns


def test_prices_unaffected_by_the_accounting_flag():
    """`prices()` (the decision path) must remain callable regardless of
    `accounting` - the new gate is scoped to `prices_for_returns()` only."""
    ctx = _context("2020-01-15", DataRequirements(price_lookback_days=5))
    result = ctx.prices(["AAA"], 5)
    assert "adj_close" not in result.columns


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
    """M03b (plans/M03b-share-terms.md): declaring `ttm_eps` also returns
    a per-field provenance key, `ttm_eps_split_factor`, plus
    `share_terms_asof` - see data/pit.py's `fundamentals()` docstring.
    `cash` alone would NOT add them; declaring it alongside `ttm_eps` here
    does. `shares_outstanding` was NOT declared, so no
    `shares_outstanding_split_factor` key appears (M03b REVIEW.md finding
    2: each provenance key is gated on its OWN field, not on "either field
    declared")."""
    requirements = DataRequirements(fundamental_fields=frozenset({"ttm_eps", "cash"}))
    ctx = _context("2020-01-15", requirements)

    result = ctx.fundamentals("AAA")

    assert set(result.keys()) == {
        "ttm_eps",
        "cash",
        "ttm_eps_split_factor",
        "share_terms_asof",
    }
    assert result["ttm_eps"] == 1.5
    assert result["cash"] == 20.0
    # FUNDAMENTALS_FIXED carries no *_filed provenance, so nothing to
    # restate against - factor is the documented no-op default.
    assert result["ttm_eps_split_factor"] == 1.0


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


# -- per-context actions memoisation (M03b verdict carried item 9) ----------


class _CountingCorporateActionsProvider(CorporateActionsProvider):
    """Records how many times `get_actions` was actually called - the
    call-count fixture item 9 asks for."""

    def __init__(self, actions: pd.DataFrame):
        self._actions = actions
        self.call_count = 0

    def get_actions(self, ticker: str, start: object, end: object) -> pd.DataFrame:
        self.call_count += 1
        start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
        return self._actions.loc[
            (self._actions.index >= start_ts) & (self._actions.index <= end_ts)
        ].copy()


def test_gated_actions_are_memoised_within_one_context_and_reused_by_prices_and_fundamentals():
    """M03b verdict carried item 9 (closed in M04, REVIEW.md finding 2):
    within ONE `PITDataContext`, a ticker's gated actions frame is fetched
    from the provider ONCE and reused by BOTH `prices()` and
    `fundamentals()` - before this fix each call re-fetched independently,
    doubling (at least) the actions-provider hit for every ticker on every
    rebalance across the whole universe."""
    provider = _CountingCorporateActionsProvider(_empty_actions())
    requirements = DataRequirements(
        price_lookback_days=5,
        fundamental_fields=frozenset({"shares_outstanding", "ttm_eps"}),
    )
    ctx = PITDataContext(
        asof="2020-01-15",
        requirements=requirements,
        price_provider=_FakePriceProvider(_price_panel(pd.bdate_range("2020-01-01", "2020-01-31"))),
        constituents_provider=_FakeConstituentsProvider(["AAA"]),
        fundamentals_provider=_FakeFundamentalsProvider(FUNDAMENTALS_FIXED),
        corporate_actions_provider=provider,
    )

    ctx.prices(["AAA"], 5)
    ctx.fundamentals("AAA")

    assert provider.call_count == 1


def test_gated_actions_memoisation_is_per_ticker_not_global():
    """A SECOND, different ticker still gets its own fresh fetch - the
    cache is keyed per ticker, not "has anything been fetched yet"."""
    provider = _CountingCorporateActionsProvider(_empty_actions())
    requirements = DataRequirements(price_lookback_days=5)
    ctx = PITDataContext(
        asof="2020-01-15",
        requirements=requirements,
        price_provider=_FakePriceProvider(
            pd.concat(
                [
                    _price_panel(pd.bdate_range("2020-01-01", "2020-01-31"), ticker="AAA"),
                    _price_panel(pd.bdate_range("2020-01-01", "2020-01-31"), ticker="BBB"),
                ]
            )
        ),
        constituents_provider=_FakeConstituentsProvider(["AAA", "BBB"]),
        fundamentals_provider=_FakeFundamentalsProvider(FUNDAMENTALS_FIXED),
        corporate_actions_provider=provider,
    )

    ctx.prices(["AAA"], 5)
    ctx.prices(["AAA"], 5)  # repeat AAA - still cached
    ctx.prices(["BBB"], 5)  # a new ticker - fresh fetch

    assert provider.call_count == 2


def test_gated_actions_cache_does_not_leak_across_context_instances():
    """A FRESH `PITDataContext` (a new rebalance date, or a new per-child
    context from the blend factory) gets its own empty cache - memoisation
    is scoped to one instance's lifetime, never shared globally."""
    provider = _CountingCorporateActionsProvider(_empty_actions())
    requirements = DataRequirements(price_lookback_days=5)
    panel = _price_panel(pd.bdate_range("2020-01-01", "2020-01-31"))

    def _new_ctx() -> PITDataContext:
        return PITDataContext(
            asof="2020-01-15",
            requirements=requirements,
            price_provider=_FakePriceProvider(panel),
            constituents_provider=_FakeConstituentsProvider(["AAA"]),
            fundamentals_provider=_FakeFundamentalsProvider(FUNDAMENTALS_FIXED),
            corporate_actions_provider=provider,
        )

    _new_ctx().prices(["AAA"], 5)
    _new_ctx().prices(["AAA"], 5)

    assert provider.call_count == 2


# -- _assert_no_future_dates (internal LookaheadError guard) ------------------


def test_assert_no_future_dates_raises_lookahead_error_on_violation():
    dates = pd.DatetimeIndex(["2020-01-01", "2020-02-01"])
    with pytest.raises(LookaheadError):
        _assert_no_future_dates(dates, pd.Timestamp("2020-01-15"), context="test")


def test_assert_no_future_dates_passes_when_all_dates_le_asof():
    dates = pd.DatetimeIndex(["2020-01-01", "2020-01-10"])
    _assert_no_future_dates(dates, pd.Timestamp("2020-01-15"), context="test")  # no raise


# -- window clamp to the calendar's pinned first session (M04b item 2) ------


def test_prices_window_clamped_to_calendar_first_session_does_not_raise():
    """A lookback generous enough that the naive (unclamped) window would
    reach before the calendar's pinned first session (1990-01-02) must not
    raise `DateOutOfBounds` - `_sliced_price_panel` clamps the window
    instead, and the caller simply gets fewer sessions than requested."""
    panel = _price_panel(pd.bdate_range("1990-01-02", "1990-06-29"))
    ctx = _context("1990-06-01", DataRequirements(price_lookback_days=5000), panel=panel)

    result = ctx.prices(["AAA"], 5000)  # would raise DateOutOfBounds without the M04b clamp

    assert (result.index <= pd.Timestamp("1990-06-01")).all()
    assert result.index.min() >= pd.Timestamp("1990-01-02")


# -- run-level PricePanelStore (M04b work packet item 4) ---------------------


def test_panel_store_backed_context_matches_provider_backed_context_byte_for_byte():
    """M04b acceptance criterion 4(a): a `PITDataContext` given a
    `PricePanelStore` built from the SAME provider must produce
    byte-identical `prices()`, `prices_for_returns()`, `actions()` and
    `fundamentals()` output to one using the provider directly."""
    from quantlab.backtest.panel_store import PricePanelStore

    panel = _price_panel(pd.bdate_range("2020-01-01", "2020-01-31"))
    provider = _FakePriceProvider(panel)
    store = PricePanelStore.build(provider, ["AAA", "BBB"], "2019-01-01", "2020-12-31")
    requirements = DataRequirements(
        price_lookback_days=5,
        fundamental_fields=frozenset({"ttm_eps"}),
        needs_actions=True,
    )
    actions = pd.DataFrame(
        {"ticker": ["AAA"], "action_type": ["dividend"], "value": [0.5]},
        index=pd.DatetimeIndex(["2020-01-10"], name="date"),
    )

    def _build(panel_store):
        return PITDataContext(
            asof="2020-01-15",
            requirements=requirements,
            price_provider=provider,
            constituents_provider=_FakeConstituentsProvider(["AAA", "BBB"]),
            fundamentals_provider=_FakeFundamentalsProvider(FUNDAMENTALS_FIXED),
            corporate_actions_provider=_FakeCorporateActionsProvider(actions),
            accounting=True,
            panel_store=panel_store,
        )

    provider_ctx, store_ctx = _build(None), _build(store)

    pd.testing.assert_frame_equal(provider_ctx.prices(["AAA"], 5), store_ctx.prices(["AAA"], 5))
    pd.testing.assert_frame_equal(
        provider_ctx.prices_for_returns(["AAA"], 5), store_ctx.prices_for_returns(["AAA"], 5)
    )
    pd.testing.assert_frame_equal(provider_ctx.actions("AAA"), store_ctx.actions("AAA"))
    assert provider_ctx.fundamentals("AAA") == store_ctx.fundamentals("AAA")


def test_panel_store_missing_ticker_falls_back_to_the_provider():
    """A ticker the store was never built with must still work, transparently
    falling back to a direct provider call (M04b work packet item 4)."""
    from quantlab.backtest.panel_store import PricePanelStore

    panel = _price_panel(pd.bdate_range("2020-01-01", "2020-01-31"), ticker="AAA")
    provider = _FakePriceProvider(panel)
    store = PricePanelStore.build(provider, ["BBB"], "2019-01-01", "2020-12-31")  # AAA never loaded
    ctx = PITDataContext(
        asof="2020-01-15",
        requirements=DataRequirements(price_lookback_days=5),
        price_provider=provider,
        constituents_provider=_FakeConstituentsProvider(["AAA"]),
        fundamentals_provider=_FakeFundamentalsProvider(FUNDAMENTALS_FIXED),
        corporate_actions_provider=_FakeCorporateActionsProvider(_empty_actions()),
        panel_store=store,
    )

    result = ctx.prices(["AAA"], 5)

    assert not result.empty
    assert set(result["ticker"]) == {"AAA"}


def test_panel_store_is_untrusted_hostile_post_asof_rows_never_reach_prices():
    """M04b acceptance criterion 6: a store containing rows dated AFTER
    `asof` must produce a byte-identical `prices()` panel with or without
    those rows - the store is untrusted exactly like a provider, since the
    SAME hard-slice-then-assert in `_sliced_price_panel` runs regardless of
    whether `raw` came from a provider or a store."""
    from quantlab.backtest.panel_store import PricePanelStore

    panel = _price_panel(pd.bdate_range("2020-01-01", "2020-01-31"))
    hostile_rows = _price_panel(pd.bdate_range("2020-06-01", "2020-06-05"), start_price=9999.0)
    hostile_panel = pd.concat([panel, hostile_rows]).sort_index()

    clean_store = PricePanelStore.build(
        _FakePriceProvider(panel), ["AAA"], "2019-01-01", "2020-12-31"
    )
    hostile_store = PricePanelStore.build(
        _FakePriceProvider(hostile_panel), ["AAA"], "2019-01-01", "2020-12-31"
    )
    requirements = DataRequirements(price_lookback_days=5)

    def _build(store):
        return PITDataContext(
            asof="2020-01-15",
            requirements=requirements,
            price_provider=_FakePriceProvider(panel),
            constituents_provider=_FakeConstituentsProvider(["AAA"]),
            fundamentals_provider=_FakeFundamentalsProvider(FUNDAMENTALS_FIXED),
            corporate_actions_provider=_FakeCorporateActionsProvider(_empty_actions()),
            panel_store=store,
        )

    clean_result = _build(clean_store).prices(["AAA"], 5)
    hostile_result = _build(hostile_store).prices(["AAA"], 5)

    pd.testing.assert_frame_equal(clean_result, hostile_result, check_freq=False)
    assert pd.Timestamp("2020-06-01") not in hostile_result.index


# -- run-level actions store (M04b work packet item 4) -----------------------


def test_actions_store_hit_is_used_by_prices_and_the_provider_is_never_called():
    """A ticker present in `actions_store` feeds `_gated_actions_by_ticker`
    (used by `prices()`/`fundamentals()`, sliced to `<= asof` exactly as a
    provider-fetched frame would be), and the real provider is never called
    for it. `actions()` itself is a separate accessor that does not consult
    `actions_store` (only `prices()`/`fundamentals()`'s shared gate does -
    see data/pit.py's `_gated_actions_by_ticker`)."""
    actions = pd.DataFrame(
        {"ticker": ["AAA", "AAA"], "action_type": ["dividend", "split"], "value": [0.5, 2.0]},
        index=pd.DatetimeIndex(["2020-01-10", "2020-02-01"], name="date"),
    )
    provider = _CountingCorporateActionsProvider(actions)
    panel = _price_panel(pd.bdate_range("2020-01-01", "2020-01-31"))
    ctx_with_store = PITDataContext(
        asof="2020-01-15",
        requirements=DataRequirements(price_lookback_days=5),
        price_provider=_FakePriceProvider(panel),
        constituents_provider=_FakeConstituentsProvider(["AAA"]),
        fundamentals_provider=_FakeFundamentalsProvider(FUNDAMENTALS_FIXED),
        corporate_actions_provider=provider,
        actions_store={"AAA": actions},
    )
    ctx_without_store = PITDataContext(
        asof="2020-01-15",
        requirements=DataRequirements(price_lookback_days=5),
        price_provider=_FakePriceProvider(panel),
        constituents_provider=_FakeConstituentsProvider(["AAA"]),
        fundamentals_provider=_FakeFundamentalsProvider(FUNDAMENTALS_FIXED),
        corporate_actions_provider=_CountingCorporateActionsProvider(actions),
    )

    with_store_result = ctx_with_store.prices(["AAA"], 5)
    without_store_result = ctx_without_store.prices(["AAA"], 5)

    pd.testing.assert_frame_equal(with_store_result, without_store_result)
    assert provider.call_count == 0
