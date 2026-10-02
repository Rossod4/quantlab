"""validation/netted_grid.py treats a blend with weight 1.0 on one child as
EXACTLY that child's standalone run (costs included), so the standalone child
runs can serve as the (1, 0) and (0, 1) endpoints of the netted-book grid.
That equivalence is an assumption about the blend strategy and the engine;
this pins it on the real engine."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantlab.backtest.engine import run_backtest
from quantlab.core.calendar import trading_days
from quantlab.strategies.registry import load_strategy
from tests.test_engine import _config, _providers

CHILD_A = {"strategy": "engine-test-fixed-weight", "params": {"weights": {"AAA": 0.6, "BBB": 0.4}}}
CHILD_B = {"strategy": "engine-test-fixed-weight", "params": {"weights": {"CCC": 0.7, "DDD": 0.3}}}


def _panel(sessions: pd.DatetimeIndex) -> pd.DataFrame:
    rng = np.random.default_rng(11)
    frames = []
    for ticker in ("AAA", "BBB", "CCC", "DDD", "BENCH"):
        close = 50.0 * np.cumprod(1 + rng.normal(0.0005, 0.02, len(sessions)))
        frames.append(
            pd.DataFrame(
                {
                    "ticker": ticker,
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "adj_close": close,
                    "volume": 1_000_000,
                },
                index=sessions,
            )
        )
    return pd.concat(frames).sort_index()


def _blend(weight_a: float):
    return load_strategy(
        {
            "strategy": "blend",
            "params": {
                "children": [dict(CHILD_A, weight=weight_a), dict(CHILD_B, weight=1.0 - weight_a)]
            },
        }
    )


@pytest.mark.parametrize("weight_a, child", [(1.0, CHILD_A), (0.0, CHILD_B)])
def test_a_one_hot_blend_reproduces_the_standalone_child_run_with_costs(weight_a, child):
    sessions = trading_days("2019-06-01", "2020-12-31")
    providers = _providers(_panel(sessions), ["AAA", "BBB", "CCC", "DDD"])
    config = _config(start="2020-01-01", end="2020-12-31", one_way_cost_bps=10.0)

    blend_result = run_backtest(_blend(weight_a), config, providers)
    child_result = run_backtest(load_strategy(child), config, providers)

    assert child_result.cost_drag.abs().sum() > 0, "fixture must actually incur costs"
    pd.testing.assert_series_equal(
        blend_result.net_returns, child_result.net_returns, check_names=False, atol=1e-12, rtol=0
    )
    pd.testing.assert_series_equal(
        blend_result.gross_returns,
        child_result.gross_returns,
        check_names=False,
        atol=1e-12,
        rtol=0,
    )
