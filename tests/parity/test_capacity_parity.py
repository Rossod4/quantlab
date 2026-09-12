"""Golden/parity test for src/quantlab/validation/capacity.py against
..\\MomentumValueStrategy\\scripts\\cost_realism_analysis.py (CLAUDE.md
invariant #4: ported numerical logic is frozen).

The old script's own `corwin_schultz_spread` and its capacity-ceiling
arithmetic (`participation * adv / position_frac`) are TRANSCRIBED here as
`_old_corwin_schultz_spread`/`_old_capacity` - a second, independent
translation of the same formulas (using the old script's own `High`/`Low`
title-case column convention and `l` variable name, kept as in the
original for this reference copy only) - and reproduced on the SAME
synthetic fixture through both the old and the new implementation, to 1e-9.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantlab.validation.capacity import capacity_estimate, corwin_schultz_spread
from tests._validation_fixtures import make_backtest_result


def _net_returns(n: int = 10) -> pd.Series:
    return pd.Series([0.01] * n, index=pd.date_range("2020-01-31", periods=n, freq="ME"))


def _old_corwin_schultz_spread(high: pd.Series, low: pd.Series) -> float:
    """Verbatim transcription of the old script's function (see this
    module's docstring) - NOT a call into quantlab.validation.capacity."""
    h, low_vals = high.to_numpy(), low.to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        hl = np.log(h / low_vals) ** 2
        beta = hl[:-1] + hl[1:]
        h2 = np.maximum(h[:-1], h[1:])
        l2 = np.minimum(low_vals[:-1], low_vals[1:])
        gamma = np.log(h2 / l2) ** 2
    k = 3 - 2 * np.sqrt(2)
    alpha = (np.sqrt(2 * beta) - np.sqrt(beta)) / k - np.sqrt(gamma / k)
    alpha = np.where(alpha < 0, 0, alpha)
    s = 2 * (np.exp(alpha) - 1) / (1 + np.exp(alpha))
    s = s[np.isfinite(s)]
    return float(np.median(s)) if len(s) else np.nan


def _old_capacity(adv: float, participation: float, position_frac: float) -> float:
    return participation * adv / position_frac


def _fixture_panel() -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(2024)
    dates = pd.date_range("2020-01-01", periods=120, freq="B")
    panel = {}
    for ticker, base_price, base_range, base_volume in [
        ("AAA", 100.0, 2.0, 3_000_000),
        ("BBB", 50.0, 3.0, 800_000),
        ("CCC", 200.0, 1.0, 150_000),
    ]:
        close = base_price + np.cumsum(rng.normal(0, 0.5, size=len(dates)))
        high = close + rng.uniform(0.1, base_range, size=len(dates))
        low = close - rng.uniform(0.1, base_range, size=len(dates))
        volume = rng.uniform(0.5, 1.5, size=len(dates)) * base_volume
        panel[ticker] = pd.DataFrame(
            {"high": high, "low": low, "close": close, "volume": volume}, index=dates
        )
    return panel


def test_corwin_schultz_spread_matches_old_script_on_fixture():
    panel = _fixture_panel()
    for df in panel.values():
        old = _old_corwin_schultz_spread(df["high"], df["low"])
        new = corwin_schultz_spread(df["high"], df["low"])
        assert new == pytest.approx(old, abs=1e-9)


def test_capacity_ceiling_matches_old_script_arithmetic_on_fixture():
    panel = _fixture_panel()
    position_frac = 1 / 50  # old script's own hardcoded assumption

    result = make_backtest_result(net_returns=_net_returns())
    out = capacity_estimate(
        result,
        panel,
        position_frac=position_frac,
        participation_levels=(0.05, 0.10),
        adv_percentiles=(0.10, 0.25),
    )

    advs = pd.Series(
        {ticker: float((df["close"] * df["volume"]).median()) for ticker, df in panel.items()}
    )
    for participation in (0.05, 0.10):
        for adv_pctl in (0.10, 0.25):
            expected = _old_capacity(advs.quantile(adv_pctl), participation, position_frac)
            key = f"participation={participation:.0%},adv_p{int(adv_pctl * 100)}"
            assert out.capacity_ceilings[key] == pytest.approx(expected, rel=1e-9)


def test_spread_percentiles_match_old_script_quantiles_on_fixture():
    panel = _fixture_panel()
    result = make_backtest_result(net_returns=_net_returns())
    out = capacity_estimate(result, panel, position_frac=1 / 50)

    spreads = pd.Series(
        {t: _old_corwin_schultz_spread(df["high"], df["low"]) for t, df in panel.items()}
    ).dropna()
    full_bps = spreads * 10_000
    for label, q in [("p10", 0.10), ("p50", 0.50), ("p90", 0.90)]:
        assert out.spread_percentiles[label] == pytest.approx(full_bps.quantile(q), rel=1e-9)
