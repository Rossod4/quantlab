"""Unit tests for src/quantlab/validation/capacity.py. Numeric parity
against the old script lives in tests/parity/test_capacity_parity.py."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantlab.core.types import TargetWeights
from quantlab.validation.capacity import (
    _position_frac_from_holdings,
    capacity_estimate,
    corwin_schultz_spread,
)
from tests._validation_fixtures import make_backtest_result


def _flat_hl(n: int, high: float, low: float) -> tuple[pd.Series, pd.Series]:
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    return pd.Series(high, index=dates), pd.Series(low, index=dates)


def _net_returns(n: int = 10) -> pd.Series:
    return pd.Series([0.01] * n, index=pd.date_range("2020-01-31", periods=n, freq="ME"))


def test_corwin_schultz_spread_wider_range_gives_larger_spread():
    high_narrow, low_narrow = _flat_hl(30, 101.0, 100.0)
    high_wide, low_wide = _flat_hl(30, 110.0, 100.0)
    narrow = corwin_schultz_spread(high_narrow, low_narrow)
    wide = corwin_schultz_spread(high_wide, low_wide)
    assert wide > narrow >= 0.0


def test_corwin_schultz_spread_zero_when_high_equals_low():
    high, low = _flat_hl(20, 100.0, 100.0)
    result = corwin_schultz_spread(high, low)
    assert result == pytest.approx(0.0, abs=1e-9)


def test_corwin_schultz_spread_nan_on_empty_input():
    empty = pd.Series([], dtype=float)
    assert np.isnan(corwin_schultz_spread(empty, empty))


# --- position_frac derivation ---------------------------------------------


def _tw(weights: dict[str, float]) -> TargetWeights:
    return TargetWeights(asof=pd.Timestamp("2020-01-31"), weights=weights, strategy_id="momentum-x")


def test_position_frac_from_holdings_equal_weight_book():
    holdings = {
        pd.Timestamp("2020-01-31"): _tw({"A": 0.5, "B": 0.5}),
        pd.Timestamp("2020-02-29"): _tw({"A": 0.5, "B": 0.5}),
    }
    assert _position_frac_from_holdings(holdings) == pytest.approx(0.5)


def test_position_frac_from_holdings_empty_is_nan():
    assert np.isnan(_position_frac_from_holdings({}))


def test_position_frac_from_holdings_all_zero_weights_is_nan():
    holdings = {pd.Timestamp("2020-01-31"): _tw({"A": 0.0, "B": 0.0})}
    assert np.isnan(_position_frac_from_holdings(holdings))


# --- capacity_estimate integration -----------------------------------------


def _price_df(n: int, high: float, low: float, close: float, volume: float) -> pd.DataFrame:
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        },
        index=dates,
    )


def test_capacity_estimate_requires_position_frac_when_holdings_empty():
    result = make_backtest_result(net_returns=_net_returns())
    panel = {"AAA": _price_df(90, 101.0, 99.0, 100.0, 1_000_000)}
    with pytest.raises(ValueError):
        capacity_estimate(result, panel)


def test_capacity_estimate_with_explicit_position_frac():
    result = make_backtest_result(net_returns=_net_returns())
    panel = {
        "AAA": _price_df(90, 101.0, 99.0, 100.0, 2_000_000),
        "BBB": _price_df(90, 105.0, 95.0, 100.0, 500_000),
    }
    out = capacity_estimate(
        result, panel, position_frac=1 / 50, participation_levels=(0.05,), adv_percentiles=(0.5,)
    )
    assert out.n_tickers == 2
    assert out.position_frac == pytest.approx(0.02)
    assert set(out.capacity_ceilings) == {"participation=5%,adv_p50"}
    assert out.capacity_ceiling_min == out.capacity_ceiling_max


def test_capacity_estimate_skips_tickers_with_too_little_history():
    result = make_backtest_result(net_returns=_net_returns())
    panel = {
        "TOO_SHORT": _price_df(10, 101.0, 99.0, 100.0, 1_000_000),
        "LONG_ENOUGH": _price_df(90, 101.0, 99.0, 100.0, 1_000_000),
    }
    out = capacity_estimate(result, panel, position_frac=1 / 50)
    assert out.n_tickers == 1


def test_capacity_estimate_uses_holdings_derived_position_frac_by_default():
    holdings = {pd.Timestamp("2020-01-31"): _tw({"A": 0.25, "B": 0.25, "C": 0.25, "D": 0.25})}
    result = make_backtest_result(net_returns=_net_returns(), holdings_history=holdings)
    panel = {"AAA": _price_df(90, 101.0, 99.0, 100.0, 1_000_000)}
    out = capacity_estimate(result, panel, participation_levels=(0.1,), adv_percentiles=(0.5,))
    assert out.position_frac == pytest.approx(0.25)


def test_capacity_result_json_round_trips():
    import json

    result = make_backtest_result(net_returns=_net_returns())
    panel = {"AAA": _price_df(90, 101.0, 99.0, 100.0, 1_000_000)}
    out = capacity_estimate(result, panel, position_frac=1 / 50)
    payload = json.loads(json.dumps(out.to_json()))
    assert payload["n_tickers"] == 1
