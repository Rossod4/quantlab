"""QuantLab command-line entrypoint.

Each subcommand is a stub in this milestone (M00); later milestones fill in
the real implementations.
"""

from __future__ import annotations

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
def backtest() -> None:
    """Run a strategy backtest."""
    _not_implemented("M0X")


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
