"""Active-return decomposition and concentration measures.

Where does `strategy CAGR - benchmark CAGR` come from? On the aligned monthly
sample, with `x_b = benchmark - RF` and the OLS line `(strategy - RF) = a +
beta * x_b + e`:

    12 * mean(r_s) - 12 * mean(r_b) = 12 * a  +  (beta - 1) * 12 * mean(x_b)

EXACTLY (OLS with an intercept makes mean(e) = 0). So the arithmetic
annualised active return is the regression alpha plus LEVERAGE ON BETA, the
extra market premium earned by holding `beta` units of the benchmark instead
of one. The remainder between arithmetic and geometric annualisation is the
COMPOUNDING term:

    compounding = (geo_s - 12 * mean(r_s)) - (geo_b - 12 * mean(r_b))

(roughly minus half the variance difference), and the three sum to the
geometric excess `geo_s - geo_b` with no residual (`identity_gap` is that sum
checked, ~1e-16). All annualised returns here are computed on the ALIGNED
months (count of months, `(prod(1+r)) ** (12/n) - 1`); the platform's own
date-based CAGR can differ slightly, which `build.py` reports beside this.

"Beta-matched SPY". A benchmark levered to the strategy's beta,
`RF + beta * (SPY - RF)`, has the SAME Sharpe ratio as SPY (a leveraged
excess-return series is a scalar multiple of the unlevered one). So beta alone
can never close a Sharpe gap: the existing `net_sharpe_vs_benchmark` gate
gives a strategy no credit for beta leverage (extra CAGR from beta > 1 comes
with proportionally extra volatility) and charges it for concentration (the
idiosyncratic variance a 30-name book carries, which the market does not pay
for). The like-for-like comparison against a beta-matched SPY is in alpha /
appraisal-ratio terms (`alpha / idiosyncratic volatility`), reported here as
INFORMATION only; it changes no gate.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

from quantlab.attribution.regression import ROLLING_WINDOW, ols, rolling_capm
from quantlab.validation.metrics import MONTHS_PER_YEAR, sharpe_ratio


def annualised_geometric(returns: pd.Series) -> float:
    """`(prod(1 + r)) ** (12 / n) - 1` over `n` monthly returns."""
    n = len(returns)
    return float((1.0 + returns).prod() ** (MONTHS_PER_YEAR / n) - 1.0)


def decompose_active_return(
    strategy: pd.Series, benchmark: pd.Series, rf: pd.Series, hac_lags: int
) -> dict[str, Any]:
    """Split the geometric excess return of `strategy` over `benchmark` into
    leverage-on-beta, alpha and compounding (see module docstring). The three
    series share one monthly index."""
    if not (strategy.index.equals(benchmark.index) and strategy.index.equals(rf.index)):
        raise ValueError("strategy, benchmark and rf must share one index")
    xs, xb = strategy - rf, benchmark - rf
    fit = ols(xs.to_numpy(), xb.to_numpy(), ("benchmark",), hac_lags)
    alpha, beta = float(fit.coef[0]), float(fit.coef[1])

    geo_s, geo_b = annualised_geometric(strategy), annualised_geometric(benchmark)
    ppy = MONTHS_PER_YEAR
    leverage = (beta - 1.0) * ppy * float(xb.mean())
    alpha_ann = alpha * ppy
    compounding = (geo_s - ppy * float(strategy.mean())) - (geo_b - ppy * float(benchmark.mean()))
    excess = geo_s - geo_b

    levered = rf + beta * xb
    geo_levered = annualised_geometric(levered)
    resid_vol = float(fit.resid.std(ddof=1)) * np.sqrt(ppy)
    return {
        "n": fit.n,
        "beta_vs_benchmark": beta,
        "alpha_annualised_arithmetic": alpha_ann,
        "alpha_t_hac": float(fit.coef[0] / fit.se_hac[0]),
        "strategy_cagr_aligned": geo_s,
        "benchmark_cagr_aligned": geo_b,
        "excess_cagr_aligned": excess,
        "components": {
            "leverage_on_beta": leverage,
            "alpha": alpha_ann,
            "compounding": compounding,
        },
        "identity_gap": excess - (leverage + alpha_ann + compounding),
        "benchmark_premium_annualised": ppy * float(xb.mean()),
        "beta_matched_benchmark": {
            "definition": "RF + beta * (benchmark - RF), beta = beta_vs_benchmark",
            "cagr_aligned": geo_levered,
            "strategy_minus_levered_cagr": geo_s - geo_levered,
            "sharpe_excess_rf_levered": float(sharpe_ratio(levered - rf, 0.0, ppy)),
            "sharpe_excess_rf_benchmark": float(sharpe_ratio(xb, 0.0, ppy)),
            "sharpe_excess_rf_strategy": float(sharpe_ratio(xs, 0.0, ppy)),
            "idiosyncratic_volatility_annualised": resid_vol,
            "appraisal_ratio": alpha_ann / resid_vol if resid_vol > 0 else float("nan"),
        },
    }


def idiosyncratic_concentration(
    strategy_excess: pd.Series, market_excess: pd.Series, window: int = ROLLING_WINDOW
) -> dict[str, Any]:
    """How much of the variance the market does not explain, and whether one
    month dominates it.

    `full_sample_share` is 1 - R^2 over the whole sample. `rolling` is the
    same share in each trailing `window`-month CAPM fit: its mean, and its
    WORST window (the highest share - when the market explained least). The
    single largest residual month and its share of total squared residuals say
    whether idiosyncratic risk is spread out or one event."""
    fit = ols(strategy_excess.to_numpy(), market_excess.to_numpy(), ("market",), 0)
    rolled = rolling_capm(strategy_excess, market_excess, window)
    out: dict[str, Any] = {
        "full_sample_share": 1.0 - fit.r2,
    }
    if len(rolled):
        idio = 1.0 - rolled["r2"]
        out["rolling"] = {
            "window_months": window,
            "n_windows": len(rolled),
            "mean_share": float(idio.mean()),
            "worst_share": float(idio.max()),
            "worst_window_ends": str(idio.idxmax()),
        }
    else:
        out["rolling"] = None
    sq = fit.resid**2
    worst = int(np.argmax(sq))
    out["largest_residual_month"] = {
        "month": str(strategy_excess.index[worst]),
        "residual": float(fit.resid[worst]),
        "share_of_squared_residuals": float(sq[worst] / sq.sum()),
    }
    return out


def effective_holdings(holdings: Mapping[str, Mapping[str, float]]) -> dict[str, Any]:
    """`1 / sum(w^2)` per rebalance date, weights normalised to gross
    exposure 1 (`sum |w| = 1`) so cash or leverage does not shrink it; the
    mean / min / max over dates, plus the mean number of positions. An empty
    date (no positions) is skipped and counted."""
    effective: list[float] = []
    positions: list[int] = []
    empty = 0
    for weights in holdings.values():
        w = np.array([abs(v) for v in weights.values() if v != 0.0], dtype=float)
        if w.size == 0:
            empty += 1
            continue
        w = w / w.sum()
        effective.append(float(1.0 / (w**2).sum()))
        positions.append(int(w.size))
    if not effective:
        return {"n_dates": 0, "n_empty_dates": empty}
    return {
        "n_dates": len(effective),
        "n_empty_dates": empty,
        "effective_n_mean": float(np.mean(effective)),
        "effective_n_min": float(np.min(effective)),
        "effective_n_max": float(np.max(effective)),
        "positions_mean": float(np.mean(positions)),
        "weights_basis": "w / sum|w|, 1 / sum(w^2)",
    }
