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
    import pandas as pd

    from quantlab.backtest.result import BacktestResult, QualityFlags
    from quantlab.core.config import PlatformConfig
    from quantlab.validation.basic import ValidationConfig
    from quantlab.validation.metrics import MetricsSummary
    from quantlab.validation.registry import TrialsRegistry
    from quantlab.validation.report_card import ReportCard
    from quantlab.validation.sensitivity import SensitivityResult, SensitivityRunner
    from quantlab.validation.walk_forward import WalkForwardResult

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
    full: bool = typer.Option(
        False,
        "--full",
        help=(
            "Also run the M06 report card: trials registry, PSR/DSR, purged/embargoed CV, "
            "White Reality Check / Hansen SPA, block-bootstrap Monte Carlo, capacity (built "
            "from platform.yaml's cache-backed price provider over every ticker the strategy "
            "ever held - offline when the cache is warm), and the "
            "REJECTED/RESEARCH_ONLY/ELIGIBLE_FOR_PAPER verdict."
        ),
    ),
    platform: Path = typer.Option(
        Path("configs/platform.yaml"), "--platform", help="Path to platform.yaml (used by --full)."
    ),
    no_sensitivity: bool = typer.Option(
        False,
        "--no-sensitivity",
        help="Skip the sensitivity grid for this run only (overrides validation.yaml's "
        "sensitivity_enabled=true). Only meaningful with --full.",
    ),
    child_result: list[Path] = typer.Option(
        [],
        "--child-result",
        help="Directory of a saved child-sleeve BacktestResult, for the walk-forward "
        "honesty check when the headline strategy is a blend (repeat for each child; "
        "at least 2 required). Only meaningful with --full.",
    ),
) -> None:
    """Run basic-tier validation (metrics, rolling, sub-periods, flags) on a
    saved `BacktestResult` and write the report to `--out`; with `--full`,
    also build and write the M06 report card (see `--full`'s help text)."""
    import json

    from quantlab.backtest.result import BacktestResult
    from quantlab.validation.basic import load_validation_config, validate_basic

    bt_result = BacktestResult.load(result)
    bench_result = BacktestResult.load(benchmark) if benchmark is not None else None
    validation_config = load_validation_config(config)

    sensitivity_result: SensitivityResult | None = None
    walk_forward_result: WalkForwardResult | None = None
    if full and validation_config.sensitivity_enabled and not no_sensitivity:
        sensitivity_result = _build_sensitivity_result(bt_result, platform, validation_config)
    if full and child_result:
        walk_forward_result = _build_walk_forward_result(bt_result, child_result, validation_config)

    basic = validate_basic(
        bt_result,
        bench_result,
        validation_config,
        walk_forward=walk_forward_result,
        sensitivity=sensitivity_result,
    )

    out.mkdir(parents=True, exist_ok=True)
    (out / "validation_basic.json").write_text(
        json.dumps(basic.to_json(), sort_keys=True), encoding="utf-8"
    )

    typer.echo(_validate_one_liner(basic.metrics, bt_result.quality_flags))
    for flag in basic.flags:
        typer.echo(f"  - {flag}")

    if full:
        from quantlab.core.config import load_platform_config
        from quantlab.validation.registry import TrialsRegistry
        from quantlab.validation.report_card import build_report_card

        platform_config = load_platform_config(platform)
        registry = TrialsRegistry(platform_config.reports_dir)
        # quant-gate VERDICT.md M06 cycle-1 finding 5(a): idempotent, so
        # calling it on every --full run is harmless (registry.py's own
        # `seed_historical_blend_trials` docstring).
        registry.seed_historical_blend_trials()

        price_panel, missing_tickers = _build_capacity_price_panel(bt_result, platform_config)

        strategy_id = bt_result.provenance.get("strategy_id", "")
        family = strategy_id.rsplit("-", 1)[0] if strategy_id else ""
        if sensitivity_result is not None:
            _record_sensitivity_result(bt_result, sensitivity_result, family, registry)

        report_card = build_report_card(
            bt_result,
            bench_result,
            registry,
            validation_config,
            walk_forward=walk_forward_result,
            sensitivity=sensitivity_result,
            price_panel=price_panel,
            price_panel_missing_tickers=missing_tickers,
        )

        (out / "report_card.json").write_text(
            json.dumps(report_card.to_json(), sort_keys=True), encoding="utf-8"
        )
        # explicit UTF-8: the M07 template's RC/SPA "measured size" note
        # (reporting/context.py's `_measured_size_note`) uses U+2248 (~=),
        # which Path.write_text's default locale encoding (cp1252 on
        # Windows) cannot represent - reproduced as a UnicodeEncodeError on
        # this exact command before this fix.
        (out / "report_card.md").write_text(
            _report_card_markdown(bt_result, report_card), encoding="utf-8"
        )

        typer.echo(f"\nverdict: {report_card.verdict}")
        for gate in report_card.gates:
            status = "PASS" if gate.passed else "FAIL"
            typer.echo(f"  [{gate.kind:4s} {status}] {gate.name}: {gate.reason}")


def _make_sensitivity_runner(platform_config: PlatformConfig) -> SensitivityRunner:
    """Construct a REAL `SensitivityRunner` (sensitivity.py's own Protocol)
    backed by the actual backtest engine and the platform's configured
    providers. Module-level, called by name (not passed as a default
    argument) so `validate --full`'s CLI test can monkeypatch THIS function
    with a fake runner factory (quant-gate VERDICT.md M06 cycle-1 finding
    5's own test requirement) without touching a real cache/network.
    """
    import yaml

    from quantlab.backtest.engine import build_backtest_providers, run_backtest
    from quantlab.strategies.registry import load_strategy

    providers = build_backtest_providers(platform_config)

    def runner(strategy_config, params, backtest_config):
        data = yaml.safe_load(Path(strategy_config).read_text(encoding="utf-8"))
        merged_params = {**data.get("params", {}), **params}
        strategy = load_strategy({"strategy": data["strategy"], "params": merged_params})
        return run_backtest(strategy, backtest_config, providers)

    return runner


def _build_sensitivity_result(
    bt_result: BacktestResult, platform: Path, validation_config: ValidationConfig
) -> SensitivityResult | None:
    """Run the sensitivity grid for the headline strategy's family
    (quant-gate VERDICT.md M06 cycle-1 finding 5(c)) via
    `_make_sensitivity_runner`'s real engine. Returns `None` (never raises)
    when the family has no configured axes in `validation.yaml`'s
    `sensitivity` section, the saved result's provenance doesn't carry
    enough to reconstruct a `BacktestConfig`, or the grid itself fails for
    any reason (e.g. a cold cache) - `report_card.py`'s `no_cliff_score`
    gate already treats a missing sensitivity result as a documented
    failure, not a crash of the whole `--full` run.
    """
    strategy_id = bt_result.provenance.get("strategy_id", "")
    family = strategy_id.rsplit("-", 1)[0] if strategy_id else ""
    param_axes = validation_config.sensitivity.get(family)
    backtest_config_dict = bt_result.provenance.get("backtest_config")
    has_strategy_config = bool(backtest_config_dict and backtest_config_dict.get("strategy_config"))
    if not param_axes or not has_strategy_config:
        return None

    try:
        from quantlab.backtest.config import BacktestConfig
        from quantlab.core.config import load_platform_config
        from quantlab.validation.sensitivity import sensitivity_grid

        backtest_config = BacktestConfig.model_validate(backtest_config_dict)
        platform_config = load_platform_config(platform)
        runner = _make_sensitivity_runner(platform_config)
        return sensitivity_grid(
            backtest_config_dict["strategy_config"], param_axes, backtest_config, runner
        )
    except Exception as exc:  # noqa: BLE001 - degrade to "no sensitivity", never crash --full
        typer.echo(f"  (sensitivity grid skipped: {exc})", err=True)
        return None


def _record_sensitivity_result(
    bt_result: BacktestResult,
    sensitivity_result: SensitivityResult,
    family: str,
    registry: TrialsRegistry,
) -> None:
    """Record every sensitivity grid point into the registry (quant-gate
    VERDICT.md M06 cycle-1 finding 5(c)) - `registry.record_sensitivity` is
    never called from product code before this."""
    from quantlab.validation.metrics import PERIODS_PER_YEAR

    backtest_config_dict = bt_result.provenance.get("backtest_config", {})
    rebalance_freq = backtest_config_dict.get("rebalance_freq")
    periods_per_year = PERIODS_PER_YEAR.get(rebalance_freq) if rebalance_freq else None
    registry.record_sensitivity(
        sensitivity_result, family=family or "unknown", periods_per_year=periods_per_year
    )


def _check_child_rebalance_frequencies(
    children: list[BacktestResult], child_result_dirs: list[Path]
) -> None:
    """Raise a clear `ValueError` when child sleeves were run at DIFFERENT
    rebalance frequencies (quant-gate VERDICT.md M06 cycle-1 addendum) -
    `walk_forward_blend` has no way to detect this itself: it just
    intersects whatever dates happen to coincide across the children's own
    indices, which for e.g. a monthly momentum sleeve and a quarterly value
    sleeve silently produces a "blend" over a near-arbitrary, far sparser
    date set (whichever month-ends happen to also be quarter-ends) with NO
    signal anything was wrong - the module's own docstring says a caller
    must pre-compound mismatched children to one frequency first
    (`compound_to`/`compound_to_quarterly`), so failing loudly here, before
    that silent misuse can happen, is the correct default."""
    freqs = {
        d.name: c.provenance.get("backtest_config", {}).get("rebalance_freq")
        for d, c in zip(child_result_dirs, children, strict=True)
    }
    if len(set(freqs.values())) > 1:
        raise ValueError(
            f"child sleeves have different rebalance frequencies: {freqs} - "
            "walk_forward_blend requires every child at the SAME frequency; "
            "compound the faster one(s) to match first (see "
            "validation/walk_forward.py's compound_to/compound_to_quarterly)"
        )


def _build_walk_forward_result(
    bt_result: BacktestResult, child_result_dirs: list[Path], validation_config: ValidationConfig
) -> WalkForwardResult | None:
    """Run the blend-weight walk-forward honesty check (quant-gate
    VERDICT.md M06 cycle-1 finding 5(d)) when the headline strategy is a
    `blend` and at least 2 `--child-result` sleeve directories were given.
    Returns `None` (never raises) otherwise, or if the children's return
    series share no common dates - `walk_forward_stability`'s gate already
    treats a missing walk-forward as vacuously satisfied ("if present"), not
    a crash.
    """
    strategy_id = bt_result.provenance.get("strategy_id", "")
    family = strategy_id.rsplit("-", 1)[0] if strategy_id else ""
    if family != "blend" or len(child_result_dirs) < 2:
        return None

    try:
        from quantlab.backtest.result import BacktestResult
        from quantlab.validation.walk_forward import walk_forward_blend

        children = [BacktestResult.load(d) for d in child_result_dirs]
        _check_child_rebalance_frequencies(children, child_result_dirs)
        wf = validation_config.walk_forward
        return walk_forward_blend(
            [c.net_returns for c in children],
            weight_grid=[tuple(w) for w in wf.weight_grid],
            train_years=wf.train_years,
            test_years=wf.test_years,
            child_labels=tuple(d.name for d in child_result_dirs),
        )
    except Exception as exc:  # noqa: BLE001 - degrade to "no walk-forward", never crash --full
        typer.echo(f"  (walk-forward skipped: {exc})", err=True)
        return None


def _build_capacity_price_panel(
    bt_result: BacktestResult, platform_config: PlatformConfig
) -> tuple[dict[str, pd.DataFrame] | None, list[str]]:
    """Build `report_card.build_report_card`'s `price_panel` input for
    `validate --full`'s capacity gate: every ticker the strategy ever held
    (`bt_result.holdings_history`), fetched over the backtest's own window
    via `platform_config`'s configured price provider - cache-backed, so a
    warm cache never touches the network (see
    `data.providers.yfinance_prices.YFinancePriceProvider`'s docstring).

    Returns `(panel_or_None, missing_tickers)`: `missing_tickers` names
    every held ticker the provider could not supply data for (no cache, no
    network, or a config error), so `report_card.py`'s capacity gate can say
    which ones instead of a generic "no panel" message. `panel` is `None`
    only when there were no held tickers to look up, or the price provider
    itself could not be constructed at all (a config problem, not a
    per-ticker one).
    """
    held_tickers = sorted(
        {t for tw in bt_result.holdings_history.values() for t, w in tw.weights.items() if w != 0}
    )
    if not held_tickers:
        return None, []

    backtest_config = bt_result.provenance.get("backtest_config", {})
    start, end = backtest_config.get("start"), backtest_config.get("end")
    if start is None or end is None:
        return None, held_tickers

    from quantlab.data.interfaces import build_provider
    from quantlab.validation.capacity import price_panel_from_long

    try:
        price_provider = build_provider("prices", platform_config.providers.prices, platform_config)
        long_panel = price_provider.get_prices(held_tickers, start, end)
    except Exception:
        # A config error (unknown provider name) or a provider-level failure
        # (e.g. every ticker uncached and the network is unavailable) - the
        # capacity gate below treats an all-missing panel as a documented
        # failure, not a crash of the whole `--full` run.
        return None, held_tickers

    panel = price_panel_from_long(long_panel)
    missing = sorted(set(held_tickers) - set(panel))
    return (panel or None), missing


def _report_card_markdown(bt_result: BacktestResult, report_card: ReportCard) -> str:
    """Markdown summary of a `ReportCard`, rendered from the M07 reporting
    package's own `report.md.j2` template - replaces the M06 stopgap
    renderer this function used to be (quant-gate carried item: it used
    `{gate.value!r}`, which leaked `np.float64(1.0)` into the rendered
    table, and never surfaced N/K/capacity spread percentiles/Sortino
    convention). `report_card.json` remains the source of truth; this is
    presentation only, with no plots (unlike `quantlab report`, which also
    embeds them) so `validate --full` stays fast."""
    from quantlab.reporting.context import build_report_context
    from quantlab.reporting.render import _markdown_environment

    context = build_report_context(bt_result, report_card.to_json(), None)
    context["plot_files"] = {}
    context["plot_errors"] = {}
    return _markdown_environment().get_template("report.md.j2").render(**context)


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
def report(
    result: Path = typer.Option(
        ..., "--result", exists=True, file_okay=False, help="Directory of a saved BacktestResult."
    ),
    out: Path = typer.Option(..., "--out", help="Directory to write the report to."),
    card: Path | None = typer.Option(
        None,
        "--card",
        exists=True,
        file_okay=False,
        help="Directory holding report_card.json/validation_basic.json (default: --result).",
    ),
    format: str = typer.Option(
        "both", "--format", help="Which file(s) to write: html | md | both."
    ),
    config: Path = typer.Option(
        Path("configs/validation.yaml"),
        "--config",
        help=(
            "Path to validation.yaml - read for the Monte Carlo bootstrap seed so the "
            "fan plot uses the SAME draw as the quoted percentiles in report_card.json "
            "(quant-gate VERDICT.md M07 cycle-1 finding 11: a report built without this "
            "silently defaults to seed=1, which only coincidentally matches today's "
            "shipped config)."
        ),
    ),
) -> None:
    """Render a self-contained HTML report (inline CSS, base64 PNGs, no
    external assets) and/or its markdown twin from a saved `BacktestResult`
    and, if present, its `report_card.json`/`validation_basic.json`."""
    from quantlab.reporting.render import render_report
    from quantlab.validation.basic import load_validation_config

    if format not in ("html", "md", "both"):
        raise typer.BadParameter("--format must be one of: html, md, both")

    validation_config = load_validation_config(config) if config.exists() else None
    written = render_report(result, out, card_dir=card, config=validation_config, fmt=format)
    for kind, path in written.items():
        typer.echo(f"wrote {kind}: {path}")


@app.command()
def paper() -> None:
    """Run paper trading."""
    _not_implemented("M0X")


if __name__ == "__main__":
    app()
