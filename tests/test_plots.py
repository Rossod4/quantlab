"""Unit tests for src/quantlab/reporting/plots.py. Every function must
return a non-empty PNG (`bytes` starting with the PNG magic number), never
touch a display, and never raise on the shapes `context.py`/`render.py`
actually feed it."""

from __future__ import annotations

import matplotlib
import pandas as pd

from quantlab.reporting import plots
from tests._validation_fixtures import _equity_with_synthetic_start

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _returns(n: int = 24) -> pd.Series:
    values = [0.05 if i % 2 == 0 else -0.01 for i in range(n)]
    return pd.Series(values, index=pd.date_range("2015-01-31", periods=n, freq="ME"))


def test_matplotlib_backend_is_agg():
    assert matplotlib.get_backend().lower() == "agg"


def test_plot_equity_curves_returns_nonempty_png():
    returns = _returns()
    gross = _equity_with_synthetic_start(returns)
    net = _equity_with_synthetic_start(returns * 0.9)
    bench = _equity_with_synthetic_start(returns * 0.2)
    png = plots.plot_equity_curves(gross, net, bench)
    assert isinstance(png, bytes)
    assert png.startswith(_PNG_MAGIC)
    assert len(png) > 0


def test_plot_drawdown_returns_nonempty_png():
    equity = _equity_with_synthetic_start(_returns())
    png = plots.plot_drawdown(equity)
    assert png.startswith(_PNG_MAGIC)


def test_plot_universe_size_returns_nonempty_png():
    sizes = pd.Series([10, 12, 11, 13], index=pd.date_range("2015-01-31", periods=4, freq="ME"))
    png = plots.plot_universe_size(sizes)
    assert png.startswith(_PNG_MAGIC)


def test_plot_rolling_sharpe_returns_nonempty_png():
    dates = pd.date_range("2015-01-31", periods=10, freq="ME")
    table = pd.DataFrame({"Sharpe Ratio": range(10), "CAGR": [0.1] * 10}, index=dates)
    png = plots.plot_rolling_sharpe({1: table, 3: table.iloc[:0]})
    assert png.startswith(_PNG_MAGIC)


def test_plot_rolling_sharpe_handles_empty_dict():
    png = plots.plot_rolling_sharpe({})
    assert png.startswith(_PNG_MAGIC)


def test_plot_subperiod_bars_returns_nonempty_png_with_nan_row():
    table = pd.DataFrame(
        {"CAGR": [0.1, -0.05, float("nan")]}, index=["first_half", "second_half", "covid"]
    )
    png = plots.plot_subperiod_bars(table)
    assert png.startswith(_PNG_MAGIC)


def test_plot_sensitivity_heatmap_1d_marks_base_point_and_nan():
    surface = pd.Series({(9,): 1.0, (12,): float("nan"), (15,): 1.5})
    png = plots.plot_sensitivity_heatmap(
        surface, param_axes={"lookback_months": [9, 12, 15]}, base_point={"lookback_months": 12}
    )
    assert png.startswith(_PNG_MAGIC)


def test_plot_sensitivity_heatmap_2d_marks_base_point():
    surface = pd.Series(
        {
            (9, 30): 1.0,
            (9, 50): 1.1,
            (12, 30): 1.2,
            (12, 50): 1.3,
            (15, 30): 1.4,
            (15, 50): 1.5,
        }
    )
    png = plots.plot_sensitivity_heatmap(
        surface,
        param_axes={"lookback_months": [9, 12, 15], "n_long": [30, 50]},
        base_point={"lookback_months": 12, "n_long": 30},
    )
    assert png.startswith(_PNG_MAGIC)


def test_plot_monte_carlo_fan_returns_nonempty_png():
    png = plots.plot_monte_carlo_fan(_returns(48), n_paths=20, block_len=3.0, seed=0)
    assert png.startswith(_PNG_MAGIC)


def test_plot_walk_forward_weights_returns_nonempty_png():
    dates = pd.date_range("2020-01-31", periods=5, freq="QE")
    chosen = pd.DataFrame(
        {"momentum": [1.0, 0.75, 0.5, 0.25, 0.0], "value": [0.0, 0.25, 0.5, 0.75, 1.0]}, index=dates
    )
    png = plots.plot_walk_forward_weights(chosen, ("momentum", "value"))
    assert png.startswith(_PNG_MAGIC)


def test_plot_walk_forward_weights_handles_no_children():
    png = plots.plot_walk_forward_weights(pd.DataFrame(), ())
    assert png.startswith(_PNG_MAGIC)
