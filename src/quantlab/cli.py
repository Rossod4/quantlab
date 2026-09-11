"""QuantLab command-line entrypoint.

Each subcommand is a stub in this milestone (M00); later milestones fill in
the real implementations.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import typer

from quantlab import __version__

if TYPE_CHECKING:
    from quantlab.backtest.result import QualityFlags
    from quantlab.validation.metrics import MetricsSummary

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
def validate(
    result: Path = typer.Option(
        ..., "--result", exists=True, file_okay=False, help="Directory of a saved BacktestResult."
    ),
    out: Path = typer.Option(..., "--out", help="Directory to write the validation report to."),
    benchmark: Path | None = typer.Option(
        None,
        "--benchmark",
        exists=True,
        file_okay=False,
        help="Directory of a saved benchmark BacktestResult (overrides the embedded benchmark).",
    ),
    config: Path = typer.Option(
        Path("configs/validation.yaml"), "--config", help="Path to validation.yaml."
    ),
) -> None:
    """Run basic-tier validation (metrics, rolling, sub-periods, flags) on a
    saved `BacktestResult` and write the report to `--out`.

    Walk-forward and parameter-sensitivity checks are not run by this
    command (they need inputs beyond one saved result - see
    `validation/basic.py`'s module docstring); it covers the "basic" tier
    only (`plans/M05-validation-1.md`)."""
    import json

    from quantlab.backtest.result import BacktestResult
    from quantlab.validation.basic import load_validation_config, validate_basic

    bt_result = BacktestResult.load(result)
    bench_result = BacktestResult.load(benchmark) if benchmark is not None else None
    validation_config = load_validation_config(config)

    basic = validate_basic(bt_result, bench_result, validation_config)

    out.mkdir(parents=True, exist_ok=True)
    (out / "validation_basic.json").write_text(json.dumps(basic.to_json(), sort_keys=True))

    typer.echo(_validate_one_liner(basic.metrics, bt_result.quality_flags))
    for flag in basic.flags:
        typer.echo(f"  - {flag}")


def _validate_one_liner(metrics: MetricsSummary, quality_flags: QualityFlags) -> str:
    """The `validate` command's one-line summary. Quant-gate VERDICT.md
    finding 4 (carried M04 verdict item 2, binding): a nonzero
    extreme-return count must appear in this one-liner, with the
    long/short breakdown - M04's `backtest` one-liner (above) prints only
    the combined count, and may run in a different session from whoever
    later runs `validate` on the saved result, so it does not discharge
    this for `validate`'s own output."""
    m = metrics
    line = (
        f"net CAGR={m.net_cagr:.2%}  Sharpe={m.net_sharpe:.2f}  Sortino={m.net_sortino:.2f}  "
        f"Calmar={m.net_calmar:.2f}  maxDD={m.net_max_drawdown:.2%}  hit_rate={m.hit_rate:.1%}"
    )
    qf = quality_flags
    if qf.extreme_returns_long or qf.extreme_returns_short:
        line += (
            f"  extreme_returns_long={qf.extreme_returns_long} "
            f"extreme_returns_short={qf.extreme_returns_short}"
        )
    return line


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
