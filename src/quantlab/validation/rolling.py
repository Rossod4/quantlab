"""Rolling-window and sub-period ("regime") robustness tables.

`rolling_window_metrics` is ported VERBATIM from ..\\MomentumValueStrategy\\
src\\evaluation\\walk_forward.py (frozen numerics, parity to 1e-12 - see
tests/parity/test_metrics_parity.py's sibling coverage of the shared
`standard_metrics` helper it's built from; the three rolling tests
themselves are reproduced directly in tests/test_rolling.py since the old
module conflates rolling-window and walk-forward code in one file and this
port splits them). Like the old repo, its CAGR/Max Drawdown are blind to
each window's first return - frozen, see `metrics.standard_metrics`'s
docstring for why that is kept rather than fixed here.

`subperiod_table` is new for M05: metrics over arbitrary named date ranges
(config-driven regimes, or the `first_second_half_splits` helper below).
Unlike `rolling_window_metrics`, it is under no parity obligation, so it
does NOT share that first-return blindness (quant-gate VERDICT.md cycle-1
finding 1): it rebases the sub-period's equity path from the actual prior
boundary point in the FULL-period `net_equity` curve (the run's own
synthetic pre-start 1.0, or the real equity value after the immediately
preceding return - whichever is closer), so a sub-period's CAGR and Max
Drawdown correctly account for its own first return. Both functions read
ONLY `net_returns`/`net_equity` (never `snapshots` - carried M04 verdict
item 1).
"""

from __future__ import annotations

import pandas as pd

from quantlab.validation.metrics import (
    annualized_vol,
    cagr,
    max_drawdown,
    sharpe_ratio,
    standard_metrics,
)


def rolling_window_metrics(
    returns: pd.Series,
    window_years: int,
    periods_per_year: int,
    risk_free_rate: float = 0.0,
) -> pd.DataFrame:
    """Metrics over every rolling `window_years`-long window of a return series.

    Each row is one window, indexed by the window's END date, stepping
    forward one period at a time. Overlapping windows are deliberate - see
    the old module's docstring for the full rationale.

    Raises ValueError if the series is shorter than one window.
    """
    window_len = window_years * periods_per_year
    if len(returns) < window_len:
        raise ValueError(
            f"Need at least {window_len} periods ({window_years} years at "
            f"{periods_per_year}/year) for one rolling window; got {len(returns)}."
        )
    rows = {}
    for end in range(window_len, len(returns) + 1):
        window = returns.iloc[end - window_len : end]
        rows[window.index[-1]] = standard_metrics(window, periods_per_year, risk_free_rate)
    return pd.DataFrame.from_dict(rows, orient="index")


def first_second_half_splits(
    index: pd.DatetimeIndex,
) -> dict[str, tuple[pd.Timestamp, pd.Timestamp]]:
    """Split a date index into two contiguous, non-overlapping halves BY
    POSITION (not calendar time), so every return is counted in exactly one
    half - the product of the two halves' growth factors then equals the
    full period's growth factor exactly (M05 acceptance criterion 4), which
    a calendar-midpoint split (e.g. "before/after 2019-01-01") would not
    guarantee for an unevenly-spaced or gapped index.
    """
    n = len(index)
    if n < 2:
        raise ValueError(f"need at least 2 dates to split into two halves; got {n}")
    mid = n // 2
    first = (index[0], index[mid - 1])
    second = (index[mid], index[-1])
    return {"first_half": first, "second_half": second}


_SUBPERIOD_METRIC_NAMES = (
    "CAGR",
    "Annualized Volatility",
    "Sharpe Ratio",
    "Max Drawdown",
    "Growth",
)


def _rebased_subperiod_equity(
    net_returns: pd.Series, net_equity: pd.Series, start: object, end: object
) -> pd.Series | None:
    """The equity path for [start, end] (inclusive, by return date), rebased
    to 1.0 at the boundary point immediately BEFORE the sub-period's first
    included return - i.e. `net_equity`'s own value at that prior date.
    Because `net_equity` always carries one synthetic pre-start 1.0 point
    before every real return date (`BacktestResult`'s own convention, see
    `backtest/engine.py`'s `_equity_with_start`), that prior point always
    exists: either the run's global synthetic start (when the sub-period
    begins at the very first return of the whole series) or the real
    equity value left by the immediately preceding return. Rebasing from
    THAT point - rather than restarting the curve at `1 + returns.iloc[0]`
    the way `metrics.standard_metrics` does - is what lets the returned
    curve's CAGR/Max Drawdown correctly see the sub-period's own first
    return (quant-gate VERDICT.md cycle-1 finding 1).

    Returns None when no return falls in [start, end].
    """
    sliced = net_returns.loc[pd.Timestamp(start) : pd.Timestamp(end)]
    if sliced.empty:
        return None
    first_pos = net_equity.index.get_loc(sliced.index[0])
    last_pos = net_equity.index.get_loc(sliced.index[-1])
    equity_slice = net_equity.iloc[first_pos - 1 : last_pos + 1]
    return equity_slice / equity_slice.iloc[0]


def subperiod_table(
    net_returns: pd.Series,
    net_equity: pd.Series,
    splits: dict[str, tuple[object, object]],
    periods_per_year: int,
    risk_free_rate: float = 0.0,
) -> pd.DataFrame:
    """Metrics for each named [start, end] (inclusive) sub-period of
    `net_returns`/`net_equity` - fixed first/second halves and named
    regimes (config, not code - see configs/validation.yaml) both flow
    through this one function. A split with no returns in range gets an
    all-NaN row rather than raising, since a regime entirely before/after a
    given backtest's window is an expected, not exceptional, occurrence.

    `CAGR`/`Max Drawdown` are computed from the rebased equity path (see
    `_rebased_subperiod_equity`), NOT via `metrics.standard_metrics`, so
    they correctly account for the sub-period's own first return.
    `Annualized Volatility`/`Sharpe Ratio` are computed directly from the
    sliced returns (unaffected by the equity-construction issue either
    way). `Growth` is the sub-period's own total growth factor
    (`rebased_equity.iloc[-1]`) - added so acceptance criterion 4's
    "product of sub-period growth == total growth" check can be verified
    ON THE TABLE rather than by recomputing from the raw returns.

    Takes the return AND equity series directly (not a `BacktestResult`) so
    callers control exactly which series (net) is used - see metrics.py's
    module docstring on never reading `snapshots`.
    """
    rows: dict[str, dict[str, float]] = {}
    for name, (start, end) in splits.items():
        rebased = _rebased_subperiod_equity(net_returns, net_equity, start, end)
        if rebased is None:
            rows[name] = dict.fromkeys(_SUBPERIOD_METRIC_NAMES, float("nan"))
            continue
        sliced_returns = net_returns.loc[pd.Timestamp(start) : pd.Timestamp(end)]
        rows[name] = {
            "CAGR": cagr(rebased),
            "Annualized Volatility": annualized_vol(sliced_returns, periods_per_year),
            "Sharpe Ratio": sharpe_ratio(sliced_returns, risk_free_rate, periods_per_year),
            "Max Drawdown": max_drawdown(rebased),
            "Growth": rebased.iloc[-1],
        }
    return pd.DataFrame.from_dict(rows, orient="index")
