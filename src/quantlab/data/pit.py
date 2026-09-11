"""`PITDataContext`: the ONLY object a strategy ever sees.

Every data access a strategy performs goes through an instance of this
class, hard-bound to one `asof` date at construction. No strategy is ever
handed a raw provider or an unsliced frame (see data/interfaces.py's module
docstring and CLAUDE.md invariant #1). Two kinds of misuse are converted
into typed errors rather than silently tolerated:

- `LookaheadError`: a genuine temporal violation - data timestamped after
  `asof` was about to leak through. The four accessor methods below
  (`prices`, `prices_for_returns`, `actions`, `fundamentals`/`universe`)
  never actually raise this in normal operation: they defensively FILTER
  out any offending rows before returning (see `_hard_slice`,
  `_assert_no_future_dates`, and the "excluded, not raised" canaries in
  tests/canaries/test_lookahead.py) - a single contaminated row from a
  vendor cache is expected noise, not something worth aborting a whole
  backtest over. `_assert_no_future_dates` is instead the reachable,
  directly-unit-tested (tests/test_pit.py) internal invariant check
  proving the filtering can never silently regress: it is the "this must
  never happen" assertion sitting immediately after every hard-slice.
- `UndeclaredDataError`: the strategy asked for more than its
  `DataRequirements` declared (see data/requirements.py) - undeclared
  fundamentals fields, more price lookback than declared, or a `universe()`
  call when membership access wasn't requested at all.

THE CENTRAL DESIGN DECISION OF THIS MILESTONE (M02) - adj_close exposure -
was implemented as `prices()` vs `prices_for_returns()`; see the M02
handoff (plans/state/M02/HANDOFF.md) for the original reasoning.
`prices_for_returns()` (the accounting path, for equity-curve/backtest
bookkeeping only - never for strategy signal logic) still exposes
yfinance's `adj_close`, clearly documented as reflecting ALL splits/
dividends through TODAY (not just through `asof`) - safe only for
computing returns over already-elapsed historical periods, never for
ranking/decision-making. `prices()` is UNCHANGED in that respect (never
adj_close).

M02b (the HARD, gate-mandated follow-on packet recorded in
plans/state/M02/VERDICT.md's carried item 1 and plans/QUANT-NOTES.md)
changed `prices()` itself: its `close`, `open`, `high` and `low` columns
are now an AS-OF ADJUSTMENT REPLAY - the raw price multiplied by a
cumulative factor computed ONLY from corporate-action events with
ex-date <= asof (data/adjustment.py), the IDENTICAL per-date factor
applied to all four columns - not the raw price. The original raw close
value is still available under the explicit `raw_close` column (raw
open/high/low are not separately retained). `volume` is NOT adjusted
(documented limitation - a real split multiplies share volume by the
ratio, which this replay does not model; never combine `volume` with the
adjusted price columns across a gated ex-date, e.g. for dollar volume).
This closes the M02 verdict's -90%-momentum hazard (a 10:1 split reading
as a spurious return collapse) without letting any future corporate
action leak into a decision made before it was announced:
`adjustment_factors`/`apply_asof_adjustment` re-gate to `ex_date <= asof`
internally, and `prices()` additionally hard-slices the actions it
fetches before handing them off, mirroring the existing
hard-slice-then-assert pattern used for prices/actions everywhere else in
this module.

Two things a strategy author must not get wrong (VERDICT.md M02b
re-review): (1) for any session before a gated ex-date, `close` (and
`open`/`high`/`low`) is a total-return-comparable LEVEL, not a price
anyone could have traded at that day - only `raw_close`/the row's true
traded price is that. (2) A missing or stale actions history for a ticker
BLOCKS `prices()` (raises `StaleActionsCacheError`/`ActionsFetchError`,
propagated uncaught - see data/corporate_actions.py) rather than
degrading it to an unadjusted result; there is no silent fallback.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from quantlab.core.calendar import is_trading_day, prev_trading_day, trading_days
from quantlab.core.errors import LookaheadError, UndeclaredDataError
from quantlab.core.types import normalize_timestamp
from quantlab.data.adjustment import apply_asof_adjustment
from quantlab.data.interfaces import (
    ConstituentsProvider,
    CorporateActionsProvider,
    FundamentalsProvider,
    PriceProvider,
)
from quantlab.data.requirements import DataRequirements

# "close" here is the M02b as-of adjustment replay (data/adjustment.py),
# not the provider's raw value - see module docstring. "raw_close" carries
# the original, untouched raw close alongside it.
_PRICE_DECISION_COLUMNS = ["ticker", "open", "high", "low", "close", "raw_close", "volume"]
_PRICE_RETURNS_COLUMNS = ["ticker", "open", "high", "low", "close", "adj_close", "volume"]

# actions()/prices() need "everything up to asof", not a bounded lookback -
# this stands in for "the beginning of time" when calling providers whose
# interface requires an explicit start date.
_EPOCH = pd.Timestamp("1900-01-01")


def _assert_no_future_dates(dates: pd.Index, asof: pd.Timestamp, context: str) -> None:
    """Defense-in-depth invariant check: raise `LookaheadError` if any date
    in `dates` exceeds `asof`.

    Called immediately after every hard-slice in this module, so it should
    never actually fire in normal operation - the slice already removed
    anything it would catch. It exists so a future bug that weakens or
    removes a hard-slice fails LOUDLY instead of silently leaking a future
    row to a strategy; see tests/test_pit.py for a direct unit test that
    calls this function with deliberately-violating dates.
    """
    idx = pd.DatetimeIndex(dates)
    violations = idx[idx > asof]
    if len(violations) > 0:
        raise LookaheadError(
            f"{context}: {len(violations)} row(s) dated after asof={asof.date()} "
            f"(first violation: {violations.min().date()})"
        )


def _last_session_on_or_before(date: pd.Timestamp) -> pd.Timestamp:
    """Inclusive as-of trading-day lookup: `date` itself if it's a session,
    else the most recent session before it. `core.calendar.prev_trading_day`
    is strict (always excludes `date`), which is wrong for this use - see
    plans/QUANT-NOTES.md's M00 note warning against repurposing it for
    inclusive PIT alignment."""
    if is_trading_day(date):
        return date
    return prev_trading_day(date)


def _fundamentals_effective_asof(asof: pd.Timestamp, filing_lag_sessions: int) -> pd.Timestamp:
    """The effective as-of date `fundamentals()` gates against: `asof`
    snapped to the last real session on or before it (`_last_session_on_or_
    before`), then stepped back `filing_lag_sessions` further NYSE sessions
    via `prev_trading_day` (strict-for-sessions, which is exactly right
    once already snapped to a session - see plans/QUANT-NOTES.md's M00
    note). `filing_lag_sessions=0` returns `_last_session_on_or_before(asof)`:
    identical to the pre-extension `filed <= asof` gate for a session
    `asof`, but strictly narrower (never wider) for a non-session `asof` -
    e.g. a Saturday `asof` of 2020-01-18 now gates at 2020-01-17 instead of
    literally 2020-01-18. Still restrict-only, so no pre-existing caller can
    see a filing it couldn't see before.

    Raises `ValueError` if `filing_lag_sessions` is negative - a negative
    lag would let a decision see a filing filed AFTER it (look-ahead), so
    this must be impossible to express, not merely unused."""
    if filing_lag_sessions < 0:
        raise ValueError(f"filing_lag_sessions must be >= 0, got {filing_lag_sessions}")
    effective = _last_session_on_or_before(asof)
    for _ in range(filing_lag_sessions):
        effective = prev_trading_day(effective)
    return effective


class PITDataContext:
    """Hard-bound to one `asof` date; the only data-access surface a
    strategy ever receives."""

    def __init__(
        self,
        asof: object,
        requirements: DataRequirements,
        price_provider: PriceProvider,
        constituents_provider: ConstituentsProvider,
        fundamentals_provider: FundamentalsProvider,
        corporate_actions_provider: CorporateActionsProvider,
    ):
        self._asof = normalize_timestamp(asof)
        self._requirements = requirements
        self._price_provider = price_provider
        self._constituents_provider = constituents_provider
        self._fundamentals_provider = fundamentals_provider
        self._corporate_actions_provider = corporate_actions_provider

    @property
    def asof(self) -> pd.Timestamp:
        return self._asof

    # -- prices -----------------------------------------------------------

    def prices(self, tickers: list[str], lookback_days: int) -> pd.DataFrame:
        """Decision-path OHLCV: NEVER includes adj_close. `close`/`open`/
        `high`/`low` are the as-of adjustment replay (data/adjustment.py) -
        raw price x the identical cumulative factor per date, from
        corporate-action events with ex-date <= asof; the untouched raw
        close is under `raw_close`. `volume` is NOT adjusted. Rows hard-
        sliced to <= asof; at most `lookback_days` distinct trading
        sessions ending at the last session <= asof. Raises
        `StaleActionsCacheError`/`ActionsFetchError` (uncaught) if any
        requested ticker's actions history is stale or unfetchable - this
        blocks the decision rather than silently returning an unadjusted
        result. See module docstring for the full M02b contract."""
        panel = self._sliced_price_panel(tickers, lookback_days)
        actions_by_ticker = self._gated_actions_by_ticker(tickers)
        adjusted = apply_asof_adjustment(panel, actions_by_ticker, self._asof)
        return adjusted[_PRICE_DECISION_COLUMNS].copy()

    def _gated_actions_by_ticker(self, tickers: list[str]) -> dict[str, pd.DataFrame]:
        """Fetch each ticker's corporate actions and hard-slice to ex-date
        <= asof - independent of `DataRequirements.needs_actions` (the
        adjustment replay in `prices()` is unconditional, not an
        opt-in accessor) and independent of whether the provider itself
        honored the requested `end` bound. Mirrors the hard-slice-then-
        assert pattern `actions()` uses below; `adjustment.py` re-gates
        internally too, so this is defense-in-depth, not the sole guard."""
        gated: dict[str, pd.DataFrame] = {}
        for ticker in tickers:
            raw = self._corporate_actions_provider.get_actions(ticker, _EPOCH, self._asof)
            sliced = raw.loc[raw.index <= self._asof]
            _assert_no_future_dates(
                sliced.index, self._asof, context=f"PITDataContext.prices actions[{ticker}]"
            )
            gated[ticker] = sliced
        return gated

    def prices_for_returns(self, tickers: list[str], lookback_days: int) -> pd.DataFrame:
        """Accounting-path OHLCV, including yfinance's globally-adjusted
        `adj_close`. For equity-curve/return bookkeeping only - NEVER for
        strategy signal logic. See module docstring for the full reasoning."""
        panel = self._sliced_price_panel(tickers, lookback_days)
        return panel[_PRICE_RETURNS_COLUMNS].copy()

    def _sliced_price_panel(self, tickers: list[str], lookback_days: int) -> pd.DataFrame:
        if lookback_days > self._requirements.price_lookback_days:
            raise UndeclaredDataError(
                f"prices() requested lookback_days={lookback_days} exceeds declared "
                f"DataRequirements.price_lookback_days={self._requirements.price_lookback_days}"
            )
        if lookback_days <= 0:
            empty = pd.DataFrame(columns=_PRICE_RETURNS_COLUMNS)
            empty.index = pd.DatetimeIndex([], name="date")
            return empty

        last_session = _last_session_on_or_before(self._asof)
        # Generous calendar-day buffer so `sessions` comfortably contains at
        # least `lookback_days` trading days even across long holiday runs;
        # trimmed to exactly `lookback_days` below regardless.
        buffer_days = lookback_days * 2 + 30
        window_start = last_session - pd.Timedelta(days=buffer_days)
        sessions = trading_days(window_start, last_session)
        sessions = sessions[-lookback_days:]

        if len(sessions) == 0:
            empty = pd.DataFrame(columns=_PRICE_RETURNS_COLUMNS)
            empty.index = pd.DatetimeIndex([], name="date")
            return empty

        raw = self._price_provider.get_prices(tickers, sessions.min(), sessions.max())

        # Hard slice: never trust a provider to have honored the requested
        # window - a caching bug (or an adversarial fixture, see
        # tests/canaries/test_lookahead.py) could hand back rows beyond
        # asof. Filter first (the documented, silent "exclude" behavior),
        # then assert nothing slipped through (the LookaheadError guard).
        # The slice bound is `last_session`, not the calendar `asof`: a
        # misbehaving provider could inject a non-session row (e.g. a
        # Saturday between the last session and a weekend asof) that would
        # pass an `<= asof` check while not being a real trading session.
        sliced = raw.loc[raw.index <= last_session]
        sliced = sliced[sliced["ticker"].isin(tickers)]
        _assert_no_future_dates(sliced.index, self._asof, context="PITDataContext.prices")

        # Keep only genuine calendar sessions (already trimmed to the last
        # `lookback_days` sessions ending at `last_session` above), so a
        # non-session row can neither appear in the result nor consume one
        # of the N lookback slots - criterion: "at most N sessions ending
        # at the last session <= asof", enforced against the calendar, not
        # against whatever dates the provider happened to return.
        return sliced.loc[sliced.index.isin(sessions)]

    # -- fundamentals -------------------------------------------------------

    def fundamentals(self, ticker: str, *, filing_lag_sessions: int = 0) -> dict[str, Any]:
        """Only SEC figures with `filed <= asof` (enforced inside the
        ported extraction logic - see data/providers/edgar_fundamentals.py).
        Returns only the fields declared in DataRequirements.fundamental_fields;
        raises UndeclaredDataError if none were declared.

        `filing_lag_sessions` (orchestrator-authorised additive extension,
        M03; see plans/state/M03/HANDOFF.md): optionally steps the gate back
        this many NYSE sessions before evaluating `filed <= effective_asof`
        instead of `filed <= asof` - see `_fundamentals_effective_asof`.
        Exists because the EDGAR filed-date gate is day-granular, so a
        same-day, often after-hours filing is otherwise visible to a
        same-day decision (M02 VERDICT.md carried item 2 /
        plans/QUANT-NOTES.md); passing a lag hides such filings. The
        parameter can only RESTRICT what's visible, never expand it:
        default 0 is identical to the pre-existing `filed <= asof` gate for
        a session `asof` (every prior caller and the M02 parity fixtures
        are byte-identical), and strictly narrower - never wider - for a
        non-session `asof` (see `_fundamentals_effective_asof`). A negative
        value raises `ValueError` rather than being silently accepted,
        since it would otherwise let a decision see a filing filed strictly
        after it - genuine look-ahead. `prices()` is unaffected: this
        parameter exists on `fundamentals()` only."""
        if not self._requirements.fundamental_fields:
            raise UndeclaredDataError(
                f"fundamentals() called for {ticker!r} but DataRequirements declares no "
                "fundamental_fields"
            )
        effective_asof = _fundamentals_effective_asof(self._asof, filing_lag_sessions)
        full = self._fundamentals_provider.get_pit_fundamentals(ticker, effective_asof)
        declared = self._requirements.fundamental_fields
        return {field: value for field, value in full.items() if field in declared}

    # -- universe -----------------------------------------------------------

    def universe(self) -> list[str]:
        """Point-in-time constituents as of `asof` (as-of lookup - only
        membership changes recorded on or before `asof` can influence the
        result). Raises UndeclaredDataError if DataRequirements.needs_universe
        is False."""
        if not self._requirements.needs_universe:
            raise UndeclaredDataError(
                "universe() called but DataRequirements.needs_universe is False"
            )
        members = self._constituents_provider.membership(self._asof)
        return list(members)

    # -- corporate actions ----------------------------------------------

    def actions(self, ticker: str) -> pd.DataFrame:
        """Corporate action events for `ticker` with effective (ex-)date
        <= asof. Raises UndeclaredDataError if DataRequirements.needs_actions
        is False - added in this milestone (on review advice) so that every
        accessor is declaration-gated before M03's Strategy ABC freezes the
        declaration surface."""
        if not self._requirements.needs_actions:
            raise UndeclaredDataError(
                "actions() called but DataRequirements.needs_actions is False"
            )
        raw = self._corporate_actions_provider.get_actions(ticker, _EPOCH, self._asof)
        sliced = raw.loc[raw.index <= self._asof]
        _assert_no_future_dates(sliced.index, self._asof, context="PITDataContext.actions")
        return sliced.copy()
