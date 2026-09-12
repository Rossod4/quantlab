"""Block-bootstrap Monte Carlo over a single strategy's own realized return
series: "how much of this result could plausibly be luck, given the
serial-correlation structure of the data itself?" - resample many
alternate histories via the stationary bootstrap (`bootstrap.py`, Politis &
Romano 1994) and report the resulting CAGR/max-drawdown/Sharpe distribution.

Distinct from `reality_check.py`: Monte Carlo here resamples ONE series many
times to characterize ITS OWN sampling uncertainty; Reality Check resamples
MANY trial series once each to test whether the BEST of them beats a
benchmark by more than multiple testing would predict by chance. Both share
the same bootstrap primitive because both need a resampling scheme that
preserves the original series' autocorrelation - the only overlap.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from quantlab.validation.bootstrap import stationary_bootstrap_resample
from quantlab.validation.metrics import MONTHS_PER_YEAR, max_drawdown, sharpe_ratio

_PERCENTILES = (5, 50, 95)


def block_bootstrap_paths(
    returns: pd.Series, n_paths: int, block_len: float, seed: int
) -> np.ndarray:
    """`n_paths` stationary-bootstrap resamples of `returns`, each the same
    length as the original, as a `(n_paths, len(returns))` array of raw
    period returns (not equity curves - `monte_carlo_summary` builds those)."""
    rng = np.random.default_rng(seed)
    values = returns.to_numpy()
    paths = np.empty((n_paths, len(values)))
    for i in range(n_paths):
        paths[i] = stationary_bootstrap_resample(values, block_len, rng)
    return paths


@dataclass(frozen=True)
class MonteCarloResult:
    """5th/50th/95th percentiles of CAGR, max drawdown, and Sharpe across
    `n_paths` bootstrap resamples, plus the probability that a resampled
    path's max drawdown is worse (more negative) than the OBSERVED
    (original, unresampled) max drawdown - the report card's
    `P(drawdown worse than observed)` gate input."""

    n_paths: int
    block_len: float
    periods_per_year: int
    observed_max_drawdown: float
    cagr_p5: float
    cagr_p50: float
    cagr_p95: float
    max_drawdown_p5: float
    max_drawdown_p50: float
    max_drawdown_p95: float
    sharpe_p5: float
    sharpe_p50: float
    sharpe_p95: float
    prob_drawdown_worse_than_observed: float

    def to_json(self) -> dict[str, Any]:
        return {
            "n_paths": self.n_paths,
            "block_len": self.block_len,
            "periods_per_year": self.periods_per_year,
            "observed_max_drawdown": self.observed_max_drawdown,
            "cagr_p5": self.cagr_p5,
            "cagr_p50": self.cagr_p50,
            "cagr_p95": self.cagr_p95,
            "max_drawdown_p5": self.max_drawdown_p5,
            "max_drawdown_p50": self.max_drawdown_p50,
            "max_drawdown_p95": self.max_drawdown_p95,
            "sharpe_p5": self.sharpe_p5,
            "sharpe_p50": self.sharpe_p50,
            "sharpe_p95": self.sharpe_p95,
            "prob_drawdown_worse_than_observed": self.prob_drawdown_worse_than_observed,
        }


def monte_carlo_summary(
    returns: pd.Series,
    n_paths: int,
    block_len: float,
    seed: int,
    periods_per_year: int = MONTHS_PER_YEAR,
) -> MonteCarloResult:
    """Run `block_bootstrap_paths` and summarize. Each resampled path's
    equity curve is `(1 + path).cumprod()` with a leading 1.0 prepended (NOT
    `metrics.standard_metrics`'s first-return-blind convention - a
    resampled path's own first return matters exactly as much as any other,
    so it must not be silently dropped from CAGR/drawdown - see
    `metrics.standard_metrics`'s docstring on why that convention is frozen
    for ported code and must not be reused elsewhere)."""
    paths = block_bootstrap_paths(returns, n_paths, block_len, seed)
    observed_max_drawdown = max_drawdown(_equity_with_start(returns.to_numpy()))

    cagrs = np.empty(n_paths)
    drawdowns = np.empty(n_paths)
    sharpes = np.empty(n_paths)
    years = len(returns) / periods_per_year
    for i in range(n_paths):
        path = paths[i]
        equity = _equity_with_start(path)
        cagrs[i] = _cagr_from_years(equity, years)
        drawdowns[i] = max_drawdown(equity)
        sharpes[i] = sharpe_ratio(pd.Series(path), periods_per_year=periods_per_year)

    # Strict "<" ("worse than", not "at least as bad as"): a STRICTLY
    # more negative drawdown. With "<=" a strategy whose observed drawdown
    # is 0 (e.g. a monotonically increasing equity curve) would trivially
    # score prob=1.0 against every resample tying at 0, which reads as
    # "certain to be beaten" for a result that, if anything, is unusually
    # good - "<" correctly reads that case as prob=0.0 instead.
    prob_worse = float(np.mean(drawdowns < observed_max_drawdown))

    return MonteCarloResult(
        n_paths=n_paths,
        block_len=block_len,
        periods_per_year=periods_per_year,
        observed_max_drawdown=float(observed_max_drawdown),
        cagr_p5=float(np.nanpercentile(cagrs, 5)),
        cagr_p50=float(np.nanpercentile(cagrs, 50)),
        cagr_p95=float(np.nanpercentile(cagrs, 95)),
        max_drawdown_p5=float(np.nanpercentile(drawdowns, 5)),
        max_drawdown_p50=float(np.nanpercentile(drawdowns, 50)),
        max_drawdown_p95=float(np.nanpercentile(drawdowns, 95)),
        sharpe_p5=float(np.nanpercentile(sharpes, 5)),
        sharpe_p50=float(np.nanpercentile(sharpes, 50)),
        sharpe_p95=float(np.nanpercentile(sharpes, 95)),
        prob_drawdown_worse_than_observed=prob_worse,
    )


def _equity_with_start(path: np.ndarray) -> pd.Series:
    """A synthetic-1.0-prepended equity curve from a raw return array, index
    is nominal integer positions (0..len(path)) - only the VALUES matter for
    `cagr`/`max_drawdown`, which read `.iloc`/array values, not dates."""
    growth = np.concatenate(([1.0], np.cumprod(1 + path)))
    return pd.Series(growth, index=pd.RangeIndex(len(growth)))


def _cagr_from_years(equity: pd.Series, years: float) -> float:
    if years <= 0:
        return float("nan")
    total_return = equity.iloc[-1] / equity.iloc[0]
    return total_return ** (1 / years) - 1
