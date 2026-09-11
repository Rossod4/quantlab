"""QuantLab command-line entrypoint.

Each subcommand is a stub in this milestone (M00); later milestones fill in
the real implementations.
"""

from __future__ import annotations

from pathlib import Path

import typer

from quantlab import __version__

app = typer.Typer(
    name="quantlab",
    help="QuantLab: bias-free EOD systematic trading research platform.",
    no_args_is_help=True,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"quantlab {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the quantlab version and exit.",
    ),
) -> None:
    """QuantLab command-line interface."""


def _not_implemented(milestone: str) -> None:
    typer.echo(f"not implemented ({milestone})")
    raise typer.Exit()


@app.command()
def data() -> None:
    """Fetch and cache market data."""
    _not_implemented("M0X")


@app.command()
def backtest(
    config: Path = typer.Option(
        ..., "--config", exists=True, readable=True, help="Backtest config YAML."
    ),
    out: Path = typer.Option(..., "--out", help="Directory to save the BacktestResult to."),
    platform: Path = typer.Option(
        Path("configs/platform.yaml"), "--platform", help="Path to platform.yaml."
    ),
) -> None:
    """Run a strategy backtest and save the result to `--out`.

    Prints a one-line summary (net CAGR, Sharpe, maxDD, survivorship
    coverage bound, quality-flag totals) - full metrics reporting is M05's
    job (`plans/M04-backtest-engine.md`'s "Out of scope" section)."""
    from quantlab.backtest.config import load_backtest_config
    from quantlab.backtest.engine import build_backtest_providers, run_backtest
    from quantlab.core.calendar import RebalanceFreq
    from quantlab.core.config import load_platform_config
    from quantlab.strategies.registry import load_strategy

    platform_config = load_platform_config(platform)
    backtest_config = load_backtest_config(config, platform_config)
    strategy = load_strategy(backtest_config.strategy_config)
    providers = build_backtest_providers(platform_config)

    result = run_backtest(strategy, backtest_config, providers)
    result.save(out)

    net_equity = result.net_equity
    n_years = (net_equity.index[-1] - net_equity.index[0]).days / 365.25
    if n_years > 0:
        cagr = (net_equity.iloc[-1] / net_equity.iloc[0]) ** (1 / n_years) - 1
    else:
        cagr = float("nan")
    periods_per_year: dict[RebalanceFreq, float] = {
        "daily": 252.0,
        "weekly": 52.0,
        "month_end": 12.0,
    }
    ppy = periods_per_year[backtest_config.rebalance_freq]
    mean_r, std_r = result.net_returns.mean(), result.net_returns.std()
    sharpe = (mean_r / std_r) * (ppy**0.5) if std_r else float("nan")
    running_max = net_equity.cummax()
    max_dd = ((net_equity / running_max) - 1).min()
    qf = result.quality_flags

    typer.echo(
        f"net CAGR={cagr:.2%}  Sharpe={sharpe:.2f}  maxDD={max_dd:.2%}  "
        f"coverage_bound={result.coverage_report.overall_bound:.1f}%  "
        f"forced_exits={qf.forced_exits}  extreme_returns={qf.extreme_returns}  "
        f"unscoreable_dates={len(qf.unscoreable_dates)}"
    )


@app.command()
def validate() -> None:
    """Run validation checks on a backtest result."""
    _not_implemented("M0X")


@app.command()
def report() -> None:
    """Generate a report from a backtest result."""
    _not_implemented("M0X")


@app.command()
def paper() -> None:
    """Run paper trading."""
    _not_implemented("M0X")


if __name__ == "__main__":
    app()
