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

`apply_asof_adjustment` applies the identical per-date factor to
`open`/`high`/`low` as `close` (a pure multiplicative rescaling preserves
`low <= close <= high`); `volume` is deliberately left raw - a real split
multiplies share volume by the ratio, which this replay does not model, so
`volume` is on a different share-count basis from the (adjusted) price
columns across any gated ex-date. Never compute a dollar-volume or
volume-normalized metric spanning a split using this panel.

## What this module deliberately does NOT do

- Adjust `volume` - see above. Documented limitation (the M02b work
  packet's "out of scope"); a strategy needing split-adjusted volume must
  wait for a future milestone.
- Trust a caller's `end`/`asof` bound on the actions it's handed - both
  `adjustment_factors` and `apply_asof_adjustment` re-filter to
  `ex_date <= asof` internally, so this module is safe to call even with
  actions from a hostile/misbehaving provider that ignored the requested
  window (see tests/canaries/test_lookahead.py canary (f)). Note this
  internal re-gate is NOT itself exercised by canary (f): `pit.py`'s own
  hard slice already excludes a future-dated action before this module
  ever sees it (genuine defense-in-depth), so this module's independent
  re-gate is pinned only by the direct `apply_asof_adjustment`/
  `adjustment_factors` parity tests in tests/test_adjustment.py (e.g.
  `test_nvda_10_for_1_split_leaves_price_unadjusted_when_asof_before_ex_date`)
  - see plans/state/M02b/REVIEW.md's mutation test B.

## Truncated panels and `close_prev_ex` (VERDICT.md M02b re-review finding 1)

`pit.py` fetches a ticker's ENTIRE actions history (from the epoch) but
hands `apply_asof_adjustment` a price panel trimmed to `lookback_days`
sessions - so a routine dividend payer's history has ex-dates years before
the panel's first row. Such an event's factor would only ever apply to a
price strictly before its ex-date, and the panel has none that old, so
`apply_asof_adjustment` drops any action at or before the panel's first
available date for that ticker BEFORE computing factors - a no-op by
construction, not an approximation. This also makes `close_prev_ex` total
for every surviving event, since each has at least the panel's first row
before it. `close_prev_ex` is therefore "the last PANEL close before the
ex-date", which equals the true prior trading session only when the panel
has no gap there (always true for a normal, unbroken lookback window).
`adjustment_factors` itself keeps a strict, un-truncated contract: given a
dividend with no close strictly before its ex-date in the `raw_close` it
was handed, it raises rather than guessing.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from quantlab.core.errors import DataQualityError
from quantlab.core.types import normalize_timestamp

_ACTION_TYPE_SPLIT = "split"
_ACTION_TYPE_DIVIDEND = "dividend"

_REQUIRED_RAW_CLOSE_COLUMNS = {"ticker", "close"}
_ADJUSTABLE_PRICE_COLUMNS = ("open", "high", "low", "close")


def _event_factor(
    ticker: str,
    action_type: str,
    value: float,
    ex_date: pd.Timestamp,
    raw_close: pd.Series | None,
) -> float:
    """Individual (non-cumulative) adjustment factor for one action. See
    the module docstring for the formula and its provenance. Raises
    `DataQualityError` (never a bare exception) for any input that would
    otherwise silently produce a wrong or non-positive price - this is
    market/vendor data failing a quality check, not a programming error."""
    if action_type == _ACTION_TYPE_SPLIT:
        if value <= 0:
            raise DataQualityError(
                f"{ticker}: split ratio must be positive, got {value} on {ex_date.date()}"
            )
        return 1.0 / value

    if action_type == _ACTION_TYPE_DIVIDEND:
        if raw_close is None or raw_close.empty:
            raise DataQualityError(
                f"{ticker}: dividend action present but no raw_close series was supplied "
                f"to compute close_prev_ex for the {ex_date.date()} dividend"
            )
        prior = raw_close.loc[raw_close.index < ex_date]
        if prior.empty:
            raise DataQualityError(
                f"{ticker}: no raw close available strictly before ex-date {ex_date.date()} "
                "to compute the dividend adjustment factor (close_prev_ex) - see module "
                "docstring's truncated-panel section: apply_asof_adjustment should have "
                "already dropped any action this old for a trimmed panel."
            )
        close_prev_ex = float(prior.iloc[-1])
        if close_prev_ex <= 0:
            raise DataQualityError(
                f"{ticker}: non-positive close_prev_ex ({close_prev_ex}) before {ex_date.date()}"
            )
        factor = 1.0 - (value / close_prev_ex)
        if factor <= 0:
            raise DataQualityError(
                f"{ticker}: dividend of {value} on {ex_date.date()} against "
                f"close_prev_ex={close_prev_ex} yields a non-positive adjustment factor "
                f"({factor}) - either a genuine liquidating distribution this platform "
                "does not model, or a vendor dividend value in the wrong units. Refusing "
                "to silently produce a negative or zero as-of price."
            )
        return factor

    raise DataQualityError(f"{ticker}: unknown action_type {action_type!r} at {ex_date.date()}")


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
            _event_factor(
                str(row.get("ticker", "<unknown>")),
                row["action_type"],
                float(row["value"]),
                pd.Timestamp(ex_date),
                raw_close,
            )
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

    # Defense-in-depth (VERDICT.md M02b re-review finding 4): every
    # INDIVIDUAL factor above is already guaranteed positive by
    # `_event_factor`, so a product of them should be unreachable as
    # non-positive - but this composed value is what actually multiplies a
    # price, so it gets its own explicit check rather than trusting that
    # invariant silently.
    non_positive = cumulative[cumulative <= 0]
    if not non_positive.empty:
        bad_date = non_positive.index[0]
        raise DataQualityError(
            f"composed as-of adjustment factor at ex-date {bad_date.date()} is "
            f"non-positive ({non_positive.iloc[0]}) - this should be unreachable if every "
            "individual factor is positive; surfacing loudly rather than silently "
            "propagating a bad price."
        )

    return cumulative


def apply_asof_adjustment(
    raw_close: pd.DataFrame,
    actions_by_ticker: dict[str, pd.DataFrame],
    asof: object,
) -> pd.DataFrame:
    """As-of adjust a (possibly multi-ticker) raw close panel.

    `raw_close`: DataFrame indexed by date, MUST include "ticker" and
    "close" columns. If present, "open"/"high"/"low" get the IDENTICAL
    per-date factor applied as "close" (preserving `low <= close <= high`
    across a gated ex-date); any other column ("volume", ...) passes
    through unchanged - see module docstring's "deliberately does NOT"
    section on why volume is not adjusted.
    `actions_by_ticker`: {ticker: actions DataFrame} in the same long
    format `adjustment_factors` expects. A ticker missing from this dict,
    or mapped to an empty frame, is treated as "no known corporate
    actions" - its prices pass through unadjusted. Any action at or before
    the ticker's first available date in `raw_close` is dropped before
    computing factors - see module docstring's "Truncated panels" section
    (VERDICT.md M02b re-review finding 1): such an event cannot affect any
    row in this panel, and dropping it keeps `close_prev_ex` computable for
    every surviving dividend.
    `asof`: forwarded to `adjustment_factors` for every ticker - the single
    look-ahead gate for the whole panel.

    Returns a copy of `raw_close` with:
    - "close" (and "open"/"high"/"low" if present) replaced by the as-of
      adjusted value.
    - "raw_close" added, holding the original unadjusted close.

    Raises `DataQualityError` (via `adjustment_factors`/`_event_factor`) for
    a malformed action or a composed factor that would produce a
    non-positive price - see module docstring.
    """
    missing = _REQUIRED_RAW_CLOSE_COLUMNS - set(raw_close.columns)
    if missing:
        raise ValueError(f"raw_close is missing required column(s): {sorted(missing)}")

    asof_ts = normalize_timestamp(asof)
    result = raw_close.copy()
    result["raw_close"] = result["close"]

    if result.empty:
        return result

    adjustable_columns = [c for c in _ADJUSTABLE_PRICE_COLUMNS if c in result.columns]
    # M04b work packet perf fix (plans/M04b-engine-perf.md): precompute EVERY
    # adjustable column's raw numpy array ONCE, here, outside the per-ticker
    # loop below - a PURE performance change, not a numerical one. The
    # previous code called `result[col].to_numpy(dtype=float)` INSIDE the
    # loop (once for "close" on every ticker, plus once per adjustable
    # column on the assignment at the bottom of the loop), re-converting the
    # panel's FULL column from pandas to numpy on every single iteration -
    # O(tickers x rows) redundant conversions where O(rows) suffices, since
    # nothing in this function ever mutates `result`'s own columns mid-loop
    # (`adjusted` is a separate, freshly-copied array, written to but never
    # read back before this fix would have re-read the still-untouched raw
    # column). Profiled on the real 2012-2026 momentum run: ~35,000
    # `Series.to_numpy()` calls and ~550,000 `numpy.asarray` calls, together
    # over 160s of a ~213s run, for a strategy requesting the FULL universe
    # (~500 tickers) every rebalance.
    raw_arrays = {col: result[col].to_numpy(dtype=float) for col in adjustable_columns}
    close_array = raw_arrays["close"]
    adjusted = {col: raw_arrays[col].copy() for col in adjustable_columns}
    dates = result.index.to_numpy()
    tickers = result["ticker"].to_numpy()

    for ticker in pd.unique(tickers):
        mask = tickers == ticker
        ticker_dates = dates[mask]
        ticker_closes = close_array[mask]

        ticker_actions = actions_by_ticker.get(ticker)
        if ticker_actions is None or ticker_actions.empty:
            continue

        close_series = pd.Series(ticker_closes, index=pd.DatetimeIndex(ticker_dates)).sort_index()

        # VERDICT.md M02b re-review finding 1: drop any action at or before
        # this ticker's first available date in the (possibly
        # lookback-trimmed) panel - it is output-preserving (its factor
        # only ever applies to a price strictly before its ex-date, and the
        # panel has none that old) and keeps close_prev_ex computable for
        # every surviving dividend. See module docstring.
        first_panel_date = close_series.index.min()
        ticker_actions = ticker_actions.loc[ticker_actions.index > first_panel_date]
        if ticker_actions.empty:
            continue

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

        # VERDICT.md M02b re-review finding 3: the identical per-date factor
        # array is applied to every adjustable price column, not just
        # close, so open/high/low stay on the same scale as close (and
        # `low <= close <= high` survives a gated ex-date).
        for col in adjustable_columns:
            adjusted[col][mask] = raw_arrays[col][mask] * applied

    for col in adjustable_columns:
        result[col] = adjusted[col]
    return result
