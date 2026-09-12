"""Capacity and spread-realism check - VERBATIM port (frozen numerics,
CLAUDE.md invariant #4) of the Corwin-Schultz spread estimator and the
ADV-participation capacity bound from
..\\MomentumValueStrategy\\scripts\\cost_realism_analysis.py (audited in
REVIEW_PHASE5.md §5: median full spread ~21bps on the old repo's own
2012-2026 S&P 500 cache, capacity ceiling ~$95M-$335M AUM).

`corwin_schultz_spread` is copied formula-for-formula from the old script
(same beta/gamma/alpha/k algebra, same floor-negative-alpha-at-zero
treatment, same MEDIAN-across-days reduction; `l` renamed to `low_arr` only
to satisfy ruff's ambiguous-variable-name check - no numeric change) -
golden-tested against a fixture run through BOTH implementations in
tests/parity/test_capacity_parity.py. `capacity_estimate` is the SAME
participation-bound arithmetic (`participation * adv / position_frac`)
generalized to read `position_frac` from a real `BacktestResult`'s own
holdings instead of the old script's hardcoded "1/50 for an assumed 50-name
book" - see `_position_frac_from_holdings`'s docstring.

Column names are quantlab's own lowercase convention (`high`/`low`/`close`/
`volume`, matching `core/types.Bar`) rather than the old script's pandas
title-case (`High`/`Low`/`Close`/`Volume`) - a renaming only; the numerics
touching those columns are unchanged.

`price_panel_from_long` (new, for `cli.py`'s `validate --full`) converts a
`data.interfaces.PriceProvider.get_prices()` long-format panel into the
per-ticker `dict[str, DataFrame]` shape `capacity_estimate` expects -
letting the CLI build a REAL panel from the platform's own (cache-backed,
offline-when-warm) price provider instead of requiring a caller to construct
one by hand.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from quantlab.backtest.result import BacktestResult

_MIN_HISTORY_DAYS = 60  # old script: "too little history for a meaningful estimate"
_DEFAULT_SPREAD_PERCENTILES = (0.10, 0.25, 0.50, 0.75, 0.90, 0.99)
_DEFAULT_PARTICIPATION_LEVELS = (0.05, 0.10)
_DEFAULT_ADV_PERCENTILES = (0.10, 0.25)


def corwin_schultz_spread(high: pd.Series, low: pd.Series) -> float:
    """Median Corwin-Schultz (2012) estimated full spread, as a fraction of
    price - VERBATIM (see module docstring) from the old script's function
    of the same name.

    beta = sum of squared log(high/low) over two consecutive days; gamma =
    squared log of the two-day high over the two-day low. Negative alphas
    (where the model breaks) are floored at zero, the standard treatment.
    The MEDIAN across days is reported - the estimator is noisy day to day.
    """
    high_arr, low_arr = high.to_numpy(dtype=float), low.to_numpy(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        hl = np.log(high_arr / low_arr) ** 2
        beta = hl[:-1] + hl[1:]
        h2 = np.maximum(high_arr[:-1], high_arr[1:])
        l2 = np.minimum(low_arr[:-1], low_arr[1:])
        gamma = np.log(h2 / l2) ** 2
    k = 3 - 2 * np.sqrt(2)
    alpha = (np.sqrt(2 * beta) - np.sqrt(beta)) / k - np.sqrt(gamma / k)
    alpha = np.where(alpha < 0, 0, alpha)
    s = 2 * (np.exp(alpha) - 1) / (1 + np.exp(alpha))
    s = s[np.isfinite(s)]
    return float(np.median(s)) if len(s) else float("nan")


def _position_frac_from_holdings(holdings_history: dict[Any, Any]) -> float:
    """1 / (mean number of nonzero-weight positions per rebalance) across
    `holdings_history` - the REAL equal-weight-equivalent slice of capital a
    replaced holding trades, generalizing the old script's hardcoded "1/50"
    (an assumed 50-name book) to whatever book size a given strategy
    actually runs. NaN if `holdings_history` is empty or every snapshot is
    all-zero (caller must then pass `position_frac` explicitly)."""
    if not holdings_history:
        return float("nan")
    counts = [sum(1 for w in tw.weights.values() if w != 0) for tw in holdings_history.values()]
    counts = [c for c in counts if c > 0]
    if not counts:
        return float("nan")
    return 1.0 / float(np.mean(counts))


@dataclass(frozen=True)
class CapacityResult:
    n_tickers: int
    spread_percentiles: dict[str, float]  # "p10" -> full spread, bps
    half_spread_percentiles: dict[str, float]
    adv_percentiles: dict[str, float]  # "p10" -> median daily $ volume
    position_frac: float
    capacity_ceilings: dict[str, float]  # label -> AUM ceiling, $

    def to_json(self) -> dict[str, Any]:
        return {
            "n_tickers": self.n_tickers,
            "spread_percentiles": self.spread_percentiles,
            "half_spread_percentiles": self.half_spread_percentiles,
            "adv_percentiles": self.adv_percentiles,
            "position_frac": self.position_frac,
            "capacity_ceilings": self.capacity_ceilings,
        }

    @property
    def capacity_ceiling_min(self) -> float:
        return min(self.capacity_ceilings.values())

    @property
    def capacity_ceiling_max(self) -> float:
        return max(self.capacity_ceilings.values())


def capacity_estimate(
    result: BacktestResult,
    price_panel: dict[str, pd.DataFrame],
    *,
    position_frac: float | None = None,
    participation_levels: tuple[float, ...] = _DEFAULT_PARTICIPATION_LEVELS,
    adv_percentiles: tuple[float, ...] = _DEFAULT_ADV_PERCENTILES,
    spread_percentiles: tuple[float, ...] = _DEFAULT_SPREAD_PERCENTILES,
) -> CapacityResult:
    """`price_panel`: ticker -> DataFrame with (at least) `high`/`low`/
    `close`/`volume` columns, one row per trading day - the SAME universe
    the strategy traded (caller's responsibility, e.g. every ticker ever in
    `result.holdings_history`). Tickers with fewer than
    `_MIN_HISTORY_DAYS` usable rows are skipped, exactly as the old script's
    own guard.

    `position_frac` defaults to `1 / mean(#names held per rebalance)`
    computed from `result.holdings_history` (see
    `_position_frac_from_holdings`); pass it explicitly to reproduce the old
    script's own "assume a 50-name equal-weight book" (`position_frac=1/50`)
    - required when `result.holdings_history` is empty, as in a
    fixture-only golden/parity test.
    """
    if position_frac is None:
        position_frac = _position_frac_from_holdings(result.holdings_history)
    if position_frac is None or not np.isfinite(position_frac) or position_frac <= 0:
        raise ValueError(
            "position_frac could not be derived from result.holdings_history "
            "(empty or all-zero) - pass it explicitly"
        )

    spreads: dict[str, float] = {}
    advs: dict[str, float] = {}
    for ticker, df in price_panel.items():
        need = {"high", "low", "close", "volume"}
        if df.empty or not need.issubset(df.columns) or len(df) < _MIN_HISTORY_DAYS:
            continue
        spreads[ticker] = corwin_schultz_spread(df["high"], df["low"])
        advs[ticker] = float((df["close"] * df["volume"]).median())

    spreads_s = pd.Series(spreads).dropna()
    advs_s = pd.Series(advs).dropna()

    full_bps = spreads_s * 10_000
    half_bps = full_bps / 2
    spread_pctls = {f"p{int(q * 100):02d}": float(full_bps.quantile(q)) for q in spread_percentiles}
    half_spread_pctls = {
        f"p{int(q * 100):02d}": float(half_bps.quantile(q)) for q in spread_percentiles
    }
    adv_pctls = {f"p{int(q * 100):02d}": float(advs_s.quantile(q)) for q in adv_percentiles}

    ceilings: dict[str, float] = {}
    for participation in participation_levels:
        for adv_pctl in adv_percentiles:
            adv = advs_s.quantile(adv_pctl)
            capacity = participation * adv / position_frac
            ceilings[f"participation={participation:.0%},adv_p{int(adv_pctl * 100)}"] = float(
                capacity
            )

    return CapacityResult(
        n_tickers=len(spreads_s),
        spread_percentiles=spread_pctls,
        half_spread_percentiles=half_spread_pctls,
        adv_percentiles=adv_pctls,
        position_frac=position_frac,
        capacity_ceilings=ceilings,
    )


def price_panel_from_long(panel: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Convert a `PriceProvider.get_prices()` long-format panel (indexed by
    date, one `ticker` column, `high`/`low`/`close`/`volume` among its
    columns) into the per-ticker `dict[str, DataFrame]` shape
    `capacity_estimate` expects. Empty input (no ticker had any data over
    the window) returns `{}`, not an error - `capacity_estimate` already
    treats an empty/all-skipped panel as `n_tickers=0`."""
    if panel.empty:
        return {}
    return {
        str(ticker): group[["high", "low", "close", "volume"]]
        for ticker, group in panel.groupby("ticker")
    }
