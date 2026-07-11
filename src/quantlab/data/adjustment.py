"""As-of adjustment replay: the M02b binding condition.

Computes decision-safe adjusted close prices - raw close multiplied by a
cumulative adjustment factor built ONLY from corporate-action events whose
ex-date is <= the decision's `asof` date, applied backward in time. This is
the packet mandated by plans/state/M02/VERDICT.md's "central design
decision" section: `PITDataContext.prices()` (data/pit.py) was raw-only
through M02 because the arithmetic here had no parity anchor yet; this
module is that anchor, and `pit.py` now wires it into `prices()`.

## Formula (CRSP-style backward adjustment)

For a raw close price on session date `t`, the as-of-adjusted price is:

    adjusted(t) = raw_close(t) * factor(t)

where `factor(t)` is the product of the *individual* factors of every
corporate action with ex-date `> t` AND ex-date `<= asof` (actions with
ex-date `<= t` have already taken effect by `t` and contribute nothing;
actions with ex-date `> asof` are exactly the look-ahead this module exists
to exclude - the replay must not know about a split/dividend the market
hasn't announced yet as of the decision date).

Individual per-action factors:

- **Split**, ratio `R` (yfinance convention: `R=10.0` for a 10-for-1 split,
  `R=0.5` for a 1-for-2 reverse split - i.e. "new shares per old share"):
  `individual_factor = 1 / R`. A 10-for-1 split divides the pre-split price
  by 10 to make it comparable to post-split prices.
- **Dividend**, cash amount `D`, ex-date `d`: `individual_factor =
  1 - D / close_prev_ex`, where `close_prev_ex` is the RAW close on the
  last session strictly before `d` (the last cum-dividend close). This is
  the standard CRSP return-factor formula for a cash distribution.

When multiple events share the same ex-date, their individual factors are
multiplied together before folding into the cumulative product (order
between same-day events does not matter - each event's factor is computed
independently from the untouched raw close series, never from a
partially-adjusted price, so composition is commutative and exact
regardless of chronological ordering between splits and dividends).

## What this module deliberately does NOT do

- Adjust `open`/`high`/`low`/`volume` - only `close` is as-of adjusted.
  Documented limitation (see the M02b work packet's "out of scope"); a
  strategy needing adjusted OHLC beyond close must wait for a future
  milestone.
- Trust a caller's `end`/`asof` bound on the actions it's handed - both
  `adjustment_factors` and `apply_asof_adjustment` re-filter to
  `ex_date <= asof` internally, so this module is safe to call even with
  actions from a hostile/misbehaving provider that ignored the requested
  window (see tests/canaries/test_lookahead.py canary (f)).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from quantlab.core.types import normalize_timestamp

_ACTION_TYPE_SPLIT = "split"
_ACTION_TYPE_DIVIDEND = "dividend"

_REQUIRED_RAW_CLOSE_COLUMNS = {"ticker", "close"}


def _event_factor(
    action_type: str,
    value: float,
    ex_date: pd.Timestamp,
    raw_close: pd.Series | None,
) -> float:
    """Individual (non-cumulative) adjustment factor for one action. See
    the module docstring for the formula and its provenance."""
    if action_type == _ACTION_TYPE_SPLIT:
        if value <= 0:
            raise ValueError(f"split ratio must be positive, got {value} on {ex_date.date()}")
        return 1.0 / value

    if action_type == _ACTION_TYPE_DIVIDEND:
        if raw_close is None or raw_close.empty:
            raise ValueError(
                "dividend action present but no raw_close series was supplied to "
                f"compute close_prev_ex for the {ex_date.date()} dividend"
            )
        prior = raw_close.loc[raw_close.index < ex_date]
        if prior.empty:
            raise ValueError(
                f"no raw close available strictly before ex-date {ex_date.date()} to "
                "compute the dividend adjustment factor (close_prev_ex)"
            )
        close_prev_ex = float(prior.iloc[-1])
        if close_prev_ex <= 0:
            raise ValueError(
                f"non-positive close_prev_ex ({close_prev_ex}) before {ex_date.date()}"
            )
        return 1.0 - (value / close_prev_ex)

    raise ValueError(f"unknown action_type {action_type!r} at {ex_date.date()}")


def adjustment_factors(
    actions: pd.DataFrame,
    asof: object,
    raw_close: pd.Series | None = None,
) -> pd.Series:
    """Cumulative as-of backward-adjustment factor, keyed by ex-date.

    `actions`: long-format frame for a SINGLE ticker (DatetimeIndex named
    "date" = ex-date, columns include "action_type" in {"split","dividend"}
    and "value" - the format `corporate_actions.py`'s provider emits).
    `asof`: only actions with ex-date <= asof are used - this is the
    look-ahead gate the packet mandates; it is enforced here, not merely by
    the caller, so this function is safe against a hostile/partial input.
    `raw_close`: the ticker's raw close series (DatetimeIndex -> float),
    required only if `actions` contains any dividend rows (splits need no
    price data). Extends the work packet's two-argument signature - see
    plans/state/M02b/HANDOFF.md for why.

    Returns a Series indexed by the sorted, deduplicated ex-dates of the
    gated actions. The value at ex-date `d` is the factor to multiply any
    raw close dated STRICTLY BEFORE `d` by (see module docstring); a raw
    close dated `>= d` gets 1.0 from this event (it already trades in
    post-event terms). Empty actions (before or after gating) -> empty
    Series - callers should treat "no entry covers this date" as factor
    1.0.
    """
    if actions is None or actions.empty:
        return pd.Series(dtype=float, name="factor")

    asof_ts = normalize_timestamp(asof)
    gated = actions.loc[actions.index <= asof_ts]
    if gated.empty:
        return pd.Series(dtype=float, name="factor")

    gated = gated.sort_index()
    individual = pd.Series(
        [
            _event_factor(row["action_type"], float(row["value"]), pd.Timestamp(ex_date), raw_close)
            for ex_date, row in gated.iterrows()
        ],
        index=gated.index,
        dtype=float,
    )

    # Same-day events (e.g. a split and a dividend both effective the same
    # ex-date) collapse to one row via a product - see module docstring on
    # why ordering between them doesn't matter.
    by_date = individual.groupby(level=0).prod().sort_index()

    # Reverse-cumulative product: the value at ex_date_i is the product of
    # the individual factors for ex_date_i AND every later gated event -
    # i.e. exactly the factor applicable to a raw close dated < ex_date_i.
    cumulative = by_date.iloc[::-1].cumprod().iloc[::-1]
    cumulative.index.name = "date"
    cumulative.name = "factor"
    return cumulative


def apply_asof_adjustment(
    raw_close: pd.DataFrame,
    actions_by_ticker: dict[str, pd.DataFrame],
    asof: object,
) -> pd.DataFrame:
    """As-of adjust a (possibly multi-ticker) raw close panel.

    `raw_close`: DataFrame indexed by date, MUST include "ticker" and
    "close" columns; any other columns (open/high/low/volume/...) pass
    through unchanged - only "close" is adjusted (see module docstring's
    "deliberately does NOT" section).
    `actions_by_ticker`: {ticker: actions DataFrame} in the same long
    format `adjustment_factors` expects. A ticker missing from this dict,
    or mapped to an empty frame, is treated as "no known corporate
    actions" - its close passes through unadjusted.
    `asof`: forwarded to `adjustment_factors` for every ticker - the single
    look-ahead gate for the whole panel.

    Returns a copy of `raw_close` with:
    - "close" replaced by the as-of adjusted close.
    - "raw_close" added, holding the original unadjusted close.
    """
    missing = _REQUIRED_RAW_CLOSE_COLUMNS - set(raw_close.columns)
    if missing:
        raise ValueError(f"raw_close is missing required column(s): {sorted(missing)}")

    asof_ts = normalize_timestamp(asof)
    result = raw_close.copy()
    result["raw_close"] = result["close"]

    if result.empty:
        return result

    adjusted_close = result["close"].to_numpy(dtype=float).copy()
    dates = result.index.to_numpy()
    tickers = result["ticker"].to_numpy()

    for ticker in pd.unique(tickers):
        mask = tickers == ticker
        ticker_dates = dates[mask]
        ticker_closes = result["close"].to_numpy(dtype=float)[mask]

        ticker_actions = actions_by_ticker.get(ticker)
        if ticker_actions is None or ticker_actions.empty:
            continue

        close_series = pd.Series(ticker_closes, index=pd.DatetimeIndex(ticker_dates)).sort_index()
        factors = adjustment_factors(ticker_actions, asof_ts, raw_close=close_series)
        if factors.empty:
            continue

        ex_dates = factors.index.to_numpy()
        factor_values = factors.to_numpy()
        # For each price date, find the smallest gated ex-date STRICTLY
        # greater than it (side="right" excludes an exact ex-date match,
        # matching "a date >= ex-date already trades in post-event terms").
        # A price on/after the last gated ex-date has nothing left to
        # adjust for -> factor 1.0.
        positions = np.searchsorted(ex_dates, ticker_dates, side="right")
        clipped = np.clip(positions, 0, len(factor_values) - 1)
        applied = np.where(positions < len(factor_values), factor_values[clipped], 1.0)
        adjusted_close[mask] = ticker_closes * applied

    result["close"] = adjusted_close
    return result
