"""Performance metrics computed on a `BacktestResult`'s return/equity series.

`cagr`, `annualized_vol`, `sharpe_ratio`, `max_drawdown` are ported VERBATIM
from ..\\MomentumValueStrategy\\src\\evaluation\\metrics.py (frozen numerics,
CLAUDE.md invariant #4; parity to 1e-12 against the old repo's own tests in
tests/parity/test_metrics_parity.py). `periods_per_year` stays an explicit
argument on every function below - never inferred from the data - per the
work packet and the old module's own docstring.

New for M05: `calmar`, `sortino`, `hit_rate`, `turnover_mean`,
`cost_drag_cagr`, `tracking_error`, `information_ratio`, `beta`,
`overlap_periods`, and `summary()`.

Carried from the M04 verdict (plans/QUANT-NOTES.md "From M04 verdict"):
metrics are computed ONLY from `net_returns` / `net_equity` / `gross_returns`
/ `gross_equity` and the benchmark series - NEVER from `BacktestResult.
snapshots`, which is a position-inspection ledger that never credits
dividends and diverges from `net_equity` by roughly the cumulative dividend
yield. `summary()` below never reads `.snapshots` (or `.holdings_history`,
`.quality_flags`, `.coverage_report`) - see
tests/test_metrics.py::test_summary_does_not_touch_snapshots.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from quantlab.backtest.result import BacktestResult

MONTHS_PER_YEAR = 12

# Rebalance-frequency -> periods/year, for `summary()`'s use reading the
# frequency out of `BacktestResult.provenance["backtest_config"][
# "rebalance_freq"]` (the value `backtest/engine.py` embeds there via
# `json.loads(config.model_dump_json())` - `BacktestConfig.rebalance_freq`
# is a `RebalanceFreq` Literal of "daily"|"weekly"|"month_end" today;
# "quarter_end" is included defensively per the work packet's own listing,
# though `core/calendar.py`'s `RebalanceFreq` does not currently emit it).
PERIODS_PER_YEAR: dict[str, int] = {
    "daily": 252,
    "weekly": 52,
    "month_end": 12,
    "quarter_end": 4,
}


# --- ported verbatim (see module docstring) --------------------------------


def cagr(equity_curve: pd.Series) -> float:
    """Compound annual growth rate implied by an equity curve.

    `equity_curve` is indexed by date, starting at some baseline value
    (e.g. 1.0) and compounding over time.
    """
    total_return = equity_curve.iloc[-1] / equity_curve.iloc[0]
    years = (equity_curve.index[-1] - equity_curve.index[0]).days / 365.25
    if years <= 0:
        return np.nan
    return total_return ** (1 / years) - 1


def annualized_vol(returns: pd.Series, periods_per_year: int = MONTHS_PER_YEAR) -> float:
    """Annualized volatility from a series of periodic returns.

    `periods_per_year` defaults to 12 (monthly returns) but must be
    overridden for any other rebalance frequency. Passing the wrong value
    here wouldn't error, just silently misstate volatility/Sharpe, so it's a
    required judgment call at the call site, not something this function can
    infer from the data.
    """
    return returns.std() * np.sqrt(periods_per_year)


def sharpe_ratio(
    returns: pd.Series, risk_free_rate: float = 0.0, periods_per_year: int = MONTHS_PER_YEAR
) -> float:
    """Annualized Sharpe ratio from a series of periodic returns.

    `risk_free_rate` is an ANNUAL rate. `periods_per_year` - see
    `annualized_vol`'s docstring above.
    """
    annualized_return = returns.mean() * periods_per_year
    vol = annualized_vol(returns, periods_per_year)
    if vol == 0:
        return np.nan
    return (annualized_return - risk_free_rate) / vol


def max_drawdown(equity_curve: pd.Series) -> float:
    """Largest peak-to-trough decline in an equity curve, as a negative fraction."""
    running_max = equity_curve.cummax()
    drawdown = equity_curve / running_max - 1
    return drawdown.min()


# --- shared helper (new; used by rolling.py, walk_forward.py, basic.py) ---


def standard_metrics(
    returns: pd.Series, periods_per_year: int, risk_free_rate: float = 0.0
) -> dict[str, float]:
    """The four standard metrics for one window/period of returns - exactly
    the old repo's `_window_metrics` helper (`walk_forward.py`), shared here
    so `rolling.rolling_window_metrics` and `walk_forward.walk_forward_blend`'s
    comparison table don't each reimplement it slightly differently.

    IMPORTANT (quant-gate VERDICT.md cycle-1 finding 1): the equity curve is
    `(1 + returns).cumprod()` with NO leading 1.0 point - `equity.iloc[0]`
    is `1 + returns.iloc[0]`, not 1.0. This means `CAGR` and `Max Drawdown`
    are BLIND to the window's first return: it cancels out of `cagr`'s
    `equity[-1] / equity[0]`, and `max_drawdown`'s `cummax` never sees a
    peak preceding it (a window opening with a −50% return reports 0%
    drawdown). This is frozen, byte-identical to the old repo's own
    construction (verified: `..\\MomentumValueStrategy\\src\\evaluation\\
    walk_forward.py`'s `_window_metrics` has the identical
    `(1 + returns).cumprod()` with no synthetic start point), which is why
    `rolling_window_metrics` keeps it despite the defect - CLAUDE.md
    invariant #4 freezes ported numerics, and `tests/test_rolling.py`
    deliberately pins the 11-of-12-returns behaviour this produces.
    `Annualized Volatility`/`Sharpe Ratio` are unaffected (computed directly
    from `returns`, not the equity curve).

    Do NOT use this helper for a new surface where the first return matters
    (e.g. a sub-period/regime table) - `rolling.subperiod_table` uses its
    own equity-rebasing helper instead precisely to avoid this blindness.
    """
    equity = (1 + returns).cumprod()
    return {
        "CAGR": cagr(equity),
        "Annualized Volatility": annualized_vol(returns, periods_per_year),
        "Sharpe Ratio": sharpe_ratio(returns, risk_free_rate, periods_per_year),
        "Max Drawdown": max_drawdown(equity),
    }


# --- new metrics -------------------------------------------------------


def calmar(equity_curve: pd.Series, periods_per_year: int = MONTHS_PER_YEAR) -> float:
    """CAGR / |max drawdown|. `periods_per_year` is accepted for a uniform
    call signature with the other metrics even though `cagr`/`max_drawdown`
    don't need it directly; NaN if there was no drawdown (avoids a
    division by zero silently reading as an infinite Calmar)."""
    mdd = max_drawdown(equity_curve)
    if mdd == 0:
        return np.nan
    return cagr(equity_curve) / abs(mdd)


def sortino(
    returns: pd.Series, risk_free_rate: float = 0.0, periods_per_year: int = MONTHS_PER_YEAR
) -> float:
    """Annualized Sortino ratio: like `sharpe_ratio` but the denominator is
    downside deviation (target return 0) instead of total volatility -
    upside variance never penalizes the strategy. NaN when downside
    deviation is zero (mirrors `sharpe_ratio`'s zero-vol guard).

    Convention (quant-gate VERDICT.md non-blocking finding 5, stated
    explicitly since it is not obvious from the formula alone): the target
    return is 0, and downside deviation divides by the FULL-SAMPLE period
    count (`(downside**2).mean()`, i.e. every period, ddof=0) - NOT by the
    count of losing periods only. Full-sample N is the standard
    lower-partial-moment convention and is the right choice here: dividing
    by downside-only N would make Sortino incomparable across series with
    different numbers of losing periods. Because of this, Sortino's
    denominator is NOT on the same ddof footing as `annualized_vol`/
    `sharpe_ratio`'s `pandas.Series.std()` (sample std, ddof=1) - the two
    ratios should not be compared via their denominators alone."""
    annualized_return = returns.mean() * periods_per_year
    downside = returns.clip(upper=0.0)
    downside_deviation = np.sqrt((downside**2).mean()) * np.sqrt(periods_per_year)
    if downside_deviation == 0:
        return np.nan
    return (annualized_return - risk_free_rate) / downside_deviation


def hit_rate(returns: pd.Series) -> float:
    """Fraction of periods with a strictly positive return."""
    if len(returns) == 0:
        return np.nan
    return float((returns > 0).mean())


def turnover_mean(turnover: pd.Series) -> float:
    """Mean per-rebalance turnover (fraction of book traded)."""
    return float(turnover.mean())


def cost_drag_cagr(gross_equity: pd.Series, net_equity: pd.Series) -> float:
    """Gross CAGR minus net CAGR - how much annualized return transaction
    costs consumed (matches the old repo's `comparison.py` "Cost Drag
    (CAGR)" row)."""
    return cagr(gross_equity) - cagr(net_equity)


def _align(a: pd.Series, b: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Common-dates alignment, matching the old repo's `blend_returns`
    convention (comparison.py) - a metric comparing two series can only be
    computed where both exist."""
    common = a.index.intersection(b.index)
    return a.loc[common], b.loc[common]


def overlap_periods(returns: pd.Series, benchmark_returns: pd.Series) -> int:
    """Number of common dates between `returns` and `benchmark_returns` -
    the sample size `tracking_error`/`information_ratio`/`beta` are
    actually computed on (quant-gate VERDICT.md non-blocking finding 6). A
    benchmark covering only a fraction of `returns`' window still produces
    a fully-formed beta/IR/TE with no indication of how few dates it came
    from; this makes that sample size inspectable/flaggable."""
    return len(_align(returns, benchmark_returns)[0])


def tracking_error(
    returns: pd.Series, benchmark_returns: pd.Series, periods_per_year: int = MONTHS_PER_YEAR
) -> float:
    """Annualized standard deviation of (returns - benchmark_returns) on
    their common dates. Zero when the two series are identical."""
    r, b = _align(returns, benchmark_returns)
    active = r - b
    return float(active.std() * np.sqrt(periods_per_year))


def information_ratio(
    returns: pd.Series, benchmark_returns: pd.Series, periods_per_year: int = MONTHS_PER_YEAR
) -> float:
    """Annualized active return over tracking error. NaN when tracking
    error is zero (mirrors `sharpe_ratio`'s zero-vol guard); 0 when the two
    series are identical (active return is then also 0, before the guard
    can fire)."""
    r, b = _align(returns, benchmark_returns)
    active = r - b
    te = tracking_error(returns, benchmark_returns, periods_per_year)
    if te == 0:
        return np.nan if active.mean() != 0 else 0.0
    return float(active.mean() * periods_per_year / te)


def beta(returns: pd.Series, benchmark_returns: pd.Series) -> float:
    """OLS beta of `returns` against `benchmark_returns` on their common
    dates: Cov(r, b) / Var(b). 1.0 for a series equal to the benchmark; NaN
    when the benchmark has zero variance."""
    r, b = _align(returns, benchmark_returns)
    variance = b.var()
    if variance == 0:
        return np.nan
    return float(r.cov(b) / variance)


@dataclass(frozen=True)
class MetricsSummary:
    """Everything `summary()` computes for one `BacktestResult`. All fields
    are net-of-cost unless named `gross_*`/`benchmark_*`."""

    periods_per_year: int
    net_cagr: float
    gross_cagr: float
    net_annualized_vol: float
    net_sharpe: float
    net_sortino: float
    net_calmar: float
    net_max_drawdown: float
    hit_rate: float
    turnover_mean: float
    cost_drag_cagr: float
    benchmark_cagr: float
    benchmark_sharpe: float
    tracking_error: float
    information_ratio: float
    beta: float
    # Sample size beta/information_ratio/tracking_error were actually
    # computed on - see `overlap_periods`'s docstring (quant-gate
    # VERDICT.md non-blocking finding 6).
    benchmark_overlap_periods: int

    def to_json(self) -> dict[str, Any]:
        return {
            "periods_per_year": self.periods_per_year,
            "net_cagr": self.net_cagr,
            "gross_cagr": self.gross_cagr,
            "net_annualized_vol": self.net_annualized_vol,
            "net_sharpe": self.net_sharpe,
            "net_sortino": self.net_sortino,
            "net_calmar": self.net_calmar,
            "net_max_drawdown": self.net_max_drawdown,
            "hit_rate": self.hit_rate,
            "turnover_mean": self.turnover_mean,
            "cost_drag_cagr": self.cost_drag_cagr,
            "benchmark_cagr": self.benchmark_cagr,
            "benchmark_sharpe": self.benchmark_sharpe,
            "tracking_error": self.tracking_error,
            "information_ratio": self.information_ratio,
            "beta": self.beta,
            "benchmark_overlap_periods": self.benchmark_overlap_periods,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> MetricsSummary:
        return cls(**data)


def summary(
    result: BacktestResult, benchmark_result: BacktestResult | None = None
) -> MetricsSummary:
    """Metrics summary for one `BacktestResult`.

    Reads `periods_per_year` from `result.provenance["backtest_config"][
    "rebalance_freq"]` - never inferred from the data, never passed
    separately, per the work packet's exact signature `summary(result:
    BacktestResult) -> MetricsSummary`.

    Reads ONLY `net_returns`, `gross_returns`, `net_equity`, `gross_equity`,
    `turnover`, and (unless `benchmark_result` overrides them)
    `benchmark_returns`/`benchmark_equity` - never `snapshots`,
    `holdings_history`, `quality_flags`, or `coverage_report` (carried M04
    verdict item 1). `benchmark_result`, when given, is a full,
    independently-run `BacktestResult` (e.g. a separately-costed benchmark
    backtest) whose OWN net_returns/net_equity are used for every benchmark
    comparison instead of `result`'s embedded `benchmark_returns`/
    `benchmark_equity` - useful when the caller wants a benchmark run under
    different assumptions than whatever `result`'s engine run compared
    against. When omitted (the common case), `result`'s own embedded
    benchmark series are used.
    """
    freq = result.provenance["backtest_config"]["rebalance_freq"]
    periods_per_year = PERIODS_PER_YEAR[freq]

    net_returns = result.net_returns
    net_equity = result.net_equity
    gross_equity = result.gross_equity

    if benchmark_result is not None:
        benchmark_returns = benchmark_result.net_returns
        benchmark_equity = benchmark_result.net_equity
    else:
        benchmark_returns = result.benchmark_returns
        benchmark_equity = result.benchmark_equity

    return MetricsSummary(
        periods_per_year=periods_per_year,
        net_cagr=cagr(net_equity),
        gross_cagr=cagr(gross_equity),
        net_annualized_vol=annualized_vol(net_returns, periods_per_year),
        net_sharpe=sharpe_ratio(net_returns, periods_per_year=periods_per_year),
        net_sortino=sortino(net_returns, periods_per_year=periods_per_year),
        net_calmar=calmar(net_equity, periods_per_year),
        net_max_drawdown=max_drawdown(net_equity),
        hit_rate=hit_rate(net_returns),
        turnover_mean=turnover_mean(result.turnover),
        cost_drag_cagr=cost_drag_cagr(gross_equity, net_equity),
        benchmark_cagr=cagr(benchmark_equity),
        benchmark_sharpe=sharpe_ratio(benchmark_returns, periods_per_year=periods_per_year),
        tracking_error=tracking_error(net_returns, benchmark_returns, periods_per_year),
        information_ratio=information_ratio(net_returns, benchmark_returns, periods_per_year),
        beta=beta(net_returns, benchmark_returns),
        benchmark_overlap_periods=overlap_periods(net_returns, benchmark_returns),
    )
