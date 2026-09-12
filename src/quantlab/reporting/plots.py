"""Report plots. Every function returns PNG **bytes** (never shows a
figure, never touches a display) so `render.py` can embed them as base64 in
the HTML report and write them as sibling files beside the markdown twin.

`matplotlib.use("Agg")` is called at import time, BEFORE `pyplot` is
imported, so this module is safe to import in a headless test/CI run
regardless of what backend matplotlib would otherwise auto-select.

`plot_equity_curves`, `plot_drawdown`, `plot_universe_size` are ported from
`..\\MomentumValueStrategy\\src\\evaluation\\plots.py` (work packet: "port
... returning bytes rather than showing"). The port is intentionally
minimal: same series, same framing, same defaults - only the return type
(bytes, not a `Figure`) and the color/line conventions below change.
`plot_universe_size`'s original argument was a live point-in-time S&P 500
membership count with no equivalent field on `BacktestResult` (which
records per-YEAR coverage, not a per-rebalance size series) - `context.py`
feeds it the number of nonzero-weight names in `holdings_history` per
rebalance date instead, documented at the call site as a portfolio-size
proxy, not the original universe-size series.

Dataviz conventions (binding across every plot in this module):
  - ONE color system: the benchmark is always the same neutral grey
    (`_BENCHMARK_COLOR`), the strategy is always the same accent
    (`_STRATEGY_COLOR`); a second series (e.g. a walk-forward child) gets
    `_ACCENT_2`.
  - Gross is always a DASHED line, net is always SOLID - matching the old
    repo's own convention (`plot_equity_curves` above).
  - Readable in light and dark: no pure black/white, a neutral grey grid at
    low alpha, and colors chosen for contrast against either background
    (matplotlib's default white figure/axes face would disappear or clash
    against a dark HTML page, so every figure here sets an explicit light
    face color - the PNG is always composited onto a white card by the
    report template, in both themes, rather than trying to make the PNG
    itself theme-aware).
  - No chart junk: no 3-D, no gratuous gridlines on both axes, no legend
    when there is only one series, `tight_layout()` on every figure.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

from typing import Any  # noqa: E402

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from quantlab.validation.monte_carlo import block_bootstrap_paths  # noqa: E402

_BENCHMARK_COLOR = "#6b7280"  # neutral grey, always the benchmark
_STRATEGY_COLOR = "#2563eb"  # accent blue, always the strategy
_ACCENT_2 = "#d97706"  # second accent (e.g. a walk-forward child, base point)
_GRID_KW = {"alpha": 0.25, "color": "#9ca3af", "linewidth": 0.6}
_FACE_COLOR = "#ffffff"


def _fig_to_png_bytes(fig: plt.Figure) -> bytes:
    import io

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, facecolor=fig.get_facecolor())
    plt.close(fig)
    return buf.getvalue()


def _new_ax(figsize: tuple[float, float]) -> tuple[plt.Figure, plt.Axes]:
    fig, ax = plt.subplots(figsize=figsize, facecolor=_FACE_COLOR)
    ax.set_facecolor(_FACE_COLOR)
    ax.grid(True, **_GRID_KW)
    ax.set_axisbelow(True)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    return fig, ax


def plot_equity_curves(
    strategy_gross_equity: pd.Series,
    strategy_net_equity: pd.Series,
    benchmark_equity: pd.Series,
    log_scale: bool = True,
) -> bytes:
    """Overlay strategy (gross & net of costs) vs. benchmark equity curves.
    Log scale by default (port of the old repo's own default and rationale:
    a multi-year run likely grows several-fold, and a linear scale would
    compress the early years to an unreadable flat line)."""
    fig, ax = _new_ax((10, 5))
    ax.plot(
        benchmark_equity.index,
        benchmark_equity,
        label="Benchmark",
        color=_BENCHMARK_COLOR,
        linewidth=1.5,
    )
    ax.plot(
        strategy_gross_equity.index,
        strategy_gross_equity,
        label="Strategy (gross)",
        color=_STRATEGY_COLOR,
        linestyle="--",
        linewidth=1.5,
    )
    ax.plot(
        strategy_net_equity.index,
        strategy_net_equity,
        label="Strategy (net of costs)",
        color=_STRATEGY_COLOR,
        linewidth=2.0,
    )
    if log_scale:
        ax.set_yscale("log")
    ax.set_xlabel("Date")
    ax.set_ylabel("Growth of $1")
    ax.set_title("Equity curve: strategy vs. benchmark")
    ax.legend(frameon=False)
    fig.tight_layout()
    return _fig_to_png_bytes(fig)


def plot_drawdown(equity_curve: pd.Series, title: str = "Drawdown") -> bytes:
    """Underwater plot: drawdown from the running peak over time."""
    running_max = equity_curve.cummax()
    drawdown = equity_curve / running_max - 1

    fig, ax = _new_ax((10, 3))
    ax.fill_between(drawdown.index, drawdown, 0, color="#b91c1c", alpha=0.45, linewidth=0)
    ax.plot(drawdown.index, drawdown, color="#b91c1c", linewidth=0.8)
    ax.set_xlabel("Date")
    ax.set_ylabel("Drawdown")
    ax.set_title(title)
    fig.tight_layout()
    return _fig_to_png_bytes(fig)


def plot_universe_size(size_history: pd.Series) -> bytes:
    """Point-in-time portfolio/universe size over the backtest window - a
    direct visual sanity check that the tracked set of names is genuinely
    varying over time, not static. See module docstring for what feeds this
    on `BacktestResult` (a portfolio-size proxy, not the original repo's
    live index-membership count)."""
    fig, ax = _new_ax((10, 3))
    ax.plot(size_history.index, size_history, color=_STRATEGY_COLOR, linewidth=1.5)
    ax.set_xlabel("Date")
    ax.set_ylabel("Number of names")
    ax.set_title("Portfolio size over time")
    fig.tight_layout()
    return _fig_to_png_bytes(fig)


def plot_rolling_sharpe(rolling: dict[int, pd.DataFrame]) -> bytes:
    """One line per configured rolling-window length, each the window's
    `Sharpe Ratio` column indexed by window END date. Frozen-convention
    caveat (first return omitted from CAGR/drawdown) does not affect Sharpe,
    which is computed directly from the sliced returns - see
    `rolling.rolling_window_metrics`'s own docstring."""
    fig, ax = _new_ax((10, 4))
    colors = [_STRATEGY_COLOR, _ACCENT_2, "#059669", "#7c3aed"]
    for i, (years, table) in enumerate(sorted(rolling.items())):
        if table.empty or "Sharpe Ratio" not in table:
            continue
        ax.plot(
            table.index,
            table["Sharpe Ratio"],
            label=f"{years}y rolling",
            color=colors[i % len(colors)],
            linewidth=1.5,
        )
    ax.axhline(0.0, color="#9ca3af", linewidth=0.8)
    ax.set_xlabel("Window end date")
    ax.set_ylabel("Sharpe ratio")
    ax.set_title("Rolling Sharpe ratio")
    if rolling:
        ax.legend(frameon=False)
    fig.tight_layout()
    return _fig_to_png_bytes(fig)


def plot_subperiod_bars(subperiods: pd.DataFrame) -> bytes:
    """One bar per named sub-period/regime, height = CAGR (from the
    corrected, rebased `subperiod_table`, not the frozen rolling path)."""
    fig, ax = _new_ax((10, 4))
    if not subperiods.empty and "CAGR" in subperiods:
        values = subperiods["CAGR"]
        colors = [_STRATEGY_COLOR if v >= 0 else "#b91c1c" for v in values.fillna(0.0)]
        ax.bar(values.index, values.fillna(0.0), color=colors)
        for i, v in enumerate(values):
            if pd.isna(v):
                ax.annotate("n/a", (i, 0), ha="center", va="bottom", fontsize=8, color="#6b7280")
        ax.set_xticks(range(len(values)))
        ax.set_xticklabels(values.index, rotation=30, ha="right")
    ax.axhline(0.0, color="#9ca3af", linewidth=0.8)
    ax.set_ylabel("CAGR")
    ax.set_title("Sub-period / regime CAGR")
    fig.tight_layout()
    return _fig_to_png_bytes(fig)


def plot_sensitivity_heatmap(
    surface: pd.Series,
    param_axes: dict[str, list[Any]],
    base_point: dict[str, Any],
) -> bytes:
    """Parameter-sensitivity surface over 1 or 2 axes (sensitivity.py's own
    limit). `surface` is indexed by a tuple of parameter values in
    `param_axes` order. The base point is marked with a star; NaN grid
    points are annotated rather than silently left blank, and an
    edge-truncated axis around the base point is noted in the title so a
    reader does not mistake a partial neighbourhood for a full one."""
    axis_names = list(param_axes)
    base_tuple = tuple(base_point[name] for name in axis_names)

    if len(axis_names) == 1:
        name = axis_names[0]
        xs = param_axes[name]
        ys = [surface.get((x,), float("nan")) for x in xs]
        fig, ax = _new_ax((8, 4))
        finite = [(x, y) for x, y in zip(xs, ys, strict=True) if pd.notna(y)]
        if finite:
            fx, fy = zip(*finite, strict=True)
            ax.plot(fx, fy, color=_STRATEGY_COLOR, marker="o", linewidth=1.5)
        for x, y in zip(xs, ys, strict=True):
            if pd.isna(y):
                ax.annotate("NaN", (x, 0), ha="center", color="#b91c1c", fontsize=8)
        if base_tuple[0] in xs:
            by = surface.get(base_tuple, float("nan"))
            if pd.notna(by):
                ax.scatter([base_tuple[0]], [by], color=_ACCENT_2, marker="*", s=180, zorder=5)
        ax.set_xlabel(name)
        ax.set_ylabel("net Sharpe")
        ax.set_title(f"Sensitivity: {name} (base point marked)")
        fig.tight_layout()
        return _fig_to_png_bytes(fig)

    # 2-D grid.
    name_x, name_y = axis_names[0], axis_names[1]
    xs, ys = param_axes[name_x], param_axes[name_y]
    grid = np.full((len(ys), len(xs)), np.nan)
    for i, y in enumerate(ys):
        for j, x in enumerate(xs):
            grid[i, j] = surface.get((x, y), float("nan"))

    fig, ax = plt.subplots(figsize=(8, 6), facecolor=_FACE_COLOR)
    ax.set_facecolor(_FACE_COLOR)
    im = ax.imshow(grid, aspect="auto", cmap="RdYlGn", origin="lower")
    ax.set_xticks(range(len(xs)))
    ax.set_xticklabels(xs)
    ax.set_yticks(range(len(ys)))
    ax.set_yticklabels(ys)
    ax.set_xlabel(name_x)
    ax.set_ylabel(name_y)
    for i in range(len(ys)):
        for j in range(len(xs)):
            v = grid[i, j]
            text = "NaN" if np.isnan(v) else f"{v:.2f}"
            ax.text(j, i, text, ha="center", va="center", fontsize=8, color="#111827")
    if base_tuple[0] in xs and base_tuple[1] in ys:
        ax.scatter(
            [xs.index(base_tuple[0])],
            [ys.index(base_tuple[1])],
            marker="*",
            s=220,
            color=_ACCENT_2,
            edgecolors="black",
            linewidths=0.5,
            zorder=5,
        )
    fig.colorbar(im, ax=ax, label="net Sharpe")
    ax.set_title(f"Sensitivity: {name_x} x {name_y} (base point marked)")
    fig.tight_layout()
    return _fig_to_png_bytes(fig)


def plot_monte_carlo_fan(
    net_returns: pd.Series, n_paths: int, block_len: float, seed: int
) -> bytes:
    """5th/50th/95th percentile bootstrap EQUITY paths over time, redrawn
    from `net_returns` with `validation.monte_carlo.block_bootstrap_paths`
    (the SAME stationary-bootstrap primitive `monte_carlo_summary` uses,
    same `n_paths`/`block_len`) - illustrative only. `MonteCarloResult`
    itself stores only scalar percentiles of the CAGR/max-drawdown/Sharpe
    DISTRIBUTIONS across paths, not a time-indexed path, so this plot is a
    fresh (same-methodology) draw rather than a replay of the exact paths
    behind the report card's own numbers; treat it as showing the SHAPE of
    the resampling uncertainty, not as reproducing `monte_carlo.cagr_p50`
    etc. to the decimal."""
    path_returns = block_bootstrap_paths(net_returns, n_paths, block_len, seed)
    equity_paths = np.cumprod(1 + path_returns, axis=1)
    p5, p50, p95 = np.percentile(equity_paths, [5, 50, 95], axis=0)
    observed_equity = (1 + net_returns).cumprod().to_numpy()

    fig, ax = _new_ax((10, 5))
    x = range(len(observed_equity))
    ax.fill_between(
        x, p5, p95, color=_STRATEGY_COLOR, alpha=0.18, linewidth=0, label="5th-95th pct"
    )
    ax.plot(x, p50, color=_STRATEGY_COLOR, linewidth=1.5, label="Median resample")
    ax.plot(x, observed_equity, color=_ACCENT_2, linewidth=2.0, label="Observed")
    ax.set_yscale("log")
    ax.set_xlabel("Period #")
    ax.set_ylabel("Growth of $1")
    ax.set_title(f"Monte Carlo resampled equity fan (n={n_paths}, block_len={block_len})")
    ax.legend(frameon=False)
    fig.tight_layout()
    return _fig_to_png_bytes(fig)


def plot_walk_forward_weights(chosen_weights: pd.DataFrame, child_labels: tuple[str, ...]) -> bytes:
    """Chosen weight per walk-forward step, one line per child, so a reader
    can see the instability (or stability) directly rather than only via
    the `walk_forward_stability` gate's single fraction."""
    fig, ax = _new_ax((10, 4))
    colors = [_STRATEGY_COLOR, _ACCENT_2, "#059669", "#7c3aed"]
    for i, label in enumerate(child_labels):
        if label not in chosen_weights:
            continue
        ax.plot(
            chosen_weights.index,
            chosen_weights[label],
            label=label,
            marker="o",
            markersize=3,
            color=colors[i % len(colors)],
            linewidth=1.5,
        )
    ax.set_ylim(-0.05, 1.05)
    ax.set_xlabel("Step (first test-period date)")
    ax.set_ylabel("Chosen weight")
    ax.set_title("Walk-forward chosen weight per step")
    if child_labels:
        ax.legend(frameon=False)
    fig.tight_layout()
    return _fig_to_png_bytes(fig)
