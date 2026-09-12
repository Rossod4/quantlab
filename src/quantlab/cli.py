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
    (out / "validation_basic.json").write_text(json.dumps(basic.to_json(), sort_keys=True))

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

        (out / "report_card.json").write_text(json.dumps(report_card.to_json(), sort_keys=True))
        (out / "report_card.md").write_text(_report_card_markdown(report_card))

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


def _format_fraction(value: float | None) -> str:
    return f"{value:.0%}" if value is not None else "n/a"


def _report_card_markdown(report_card: ReportCard) -> str:
    """Markdown summary of a `ReportCard` - the full HTML report is M07's
    job (work packet's "Out of scope"); this is a plain-text-ish stopgap so
    `--full`'s output is human-readable without JSON tooling. Prints the
    full `ReportCardProvenance` section (quant-gate VERDICT.md M06 cycle-1
    finding 6)."""
    p = report_card.provenance
    m = report_card.basic.metrics
    dirty_badge = " **DIRTY TREE**" if p.dirty else ""
    lines = [
        f"# QuantLab Report Card - verdict: {report_card.verdict}",
        "",
        "## Provenance",
        f"- strategy_id: `{p.strategy_id}`",
        f"- data_semantics_version: `{p.data_semantics_version}`",
        f"- quantlab_git_sha: `{p.quantlab_git_sha}`{dirty_badge} (source: {p.dirty_source})",
        f"- N trials: {p.n_trials} distinct (raw key count: {p.n_trials_raw}, "
        f"{p.dirty_trial_count} dirty)",
        f"- Reality Check / SPA realised trial count K: "
        f"{p.rc_trial_count if p.rc_trial_count is not None else 'n/a'}",
        f"- Reality Check / SPA benchmark: {p.rc_spa_benchmark_source}",
        f"- Headline trial's own retained fraction in the RC/SPA common date range: "
        f"{_format_fraction(p.headline_retained_fraction)}",
        f"- {p.untrusted_fraction_line}",
        "",
        "## Headline metrics",
        f"- net CAGR: {m.net_cagr:.2%}  |  net max drawdown: {m.net_max_drawdown:.2%}  |  "
        f"Calmar: {m.net_calmar:.2f}  |  hit rate: {m.hit_rate:.1%}",
        f"- Sharpe: {m.net_sharpe:.2f}  |  Sortino: {m.net_sortino:.2f}",
        f"  ({p.sharpe_sortino_convention})",
        "",
        "## Gates",
        "| Gate | Kind | Value | Threshold | Result | Reason |",
        "|---|---|---|---|---|---|",
    ]
    for gate in report_card.gates:
        status = "PASS" if gate.passed else "FAIL"
        lines.append(
            f"| {gate.name} | {gate.kind} | {gate.value!r} | {gate.threshold!r} | {status} | "
            f"{gate.reason} |"
        )
    lines.append("")
    lines.append("## Known caveats")
    for caveat in report_card.known_caveats:
        lines.append(f"- {caveat}")
    return "\n".join(lines) + "\n"


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


paper_app = typer.Typer(help="Paper trading: run a strategy against a paper broker on a schedule.")
app.add_typer(paper_app, name="paper")


def _make_broker(name: str):
    if name == "mock":
        from quantlab.paper.broker import BrokerCapabilities
        from quantlab.paper.mock import MockBroker

        return MockBroker(capabilities_=BrokerCapabilities(True, False, False), prices={})
    if name == "alpaca":
        from quantlab.paper.alpaca import AlpacaPaperBroker

        return AlpacaPaperBroker()
    raise typer.BadParameter(f"unknown broker {name!r} (choose 'mock' or 'alpaca')")


@paper_app.command("run")
def paper_run(
    strategy: Path = typer.Option(
        ..., "--strategy", exists=True, readable=True, help="Strategy config YAML."
    ),
    broker: str = typer.Option("mock", "--broker", help="'mock' or 'alpaca'."),
    asof: str | None = typer.Option(
        None, "--asof", help="Decision date override (default: last completed session)."
    ),
    platform: Path = typer.Option(
        Path("configs/platform.yaml"), "--platform", help="Path to platform.yaml."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Plan orders but never call broker.submit()."
    ),
    force_research: bool = typer.Option(
        False,
        "--force-research",
        help="Bypass the promotion gate (no ELIGIBLE_FOR_PAPER report card required) - for "
        "testing the plumbing only, never for real money.",
    ),
) -> None:
    """Run one paper-trading cycle for `--strategy` against `--broker`."""
    from quantlab.core.config import load_platform_config
    from quantlab.paper.runner import run_once

    platform_config = load_platform_config(platform)
    broker_instance = _make_broker(broker)

    if dry_run:
        from quantlab.backtest.context import DecisionProviders, build_decision_context
        from quantlab.backtest.engine import build_backtest_providers
        from quantlab.paper.rebalancer import plan_orders
        from quantlab.paper.runner import _last_prices_with_dates, _today, resolve_asof
        from quantlab.strategies.registry import load_strategy

        providers = build_backtest_providers(platform_config)
        strategy_obj = load_strategy(strategy)
        effective_asof = resolve_asof(_today(), asof, providers, platform_config.benchmark)
        decision_providers = DecisionProviders(
            price=providers.price,
            constituents=providers.constituents,
            fundamentals=providers.fundamentals,
            corporate_actions=providers.corporate_actions,
        )
        ctx = build_decision_context(
            asof=effective_asof,
            requirements=strategy_obj.requires(),
            providers=decision_providers,
            max_dropped_fraction=0.05,
            on_drop=lambda ticker, exc: None,
        )
        targets = strategy_obj.generate_targets(ctx, effective_asof)
        account = broker_instance.account()
        tickers = sorted(set(targets.weights) | set(account.positions))
        prices, _ = _last_prices_with_dates(providers, tickers, effective_asof)
        orders = plan_orders(targets, account, prices, broker_instance.capabilities())
        typer.echo(f"dry-run: asof={effective_asof.date()} strategy_id={strategy_obj.strategy_id}")
        for order in orders:
            typer.echo(f"  {order.side} {order.qty} {order.ticker} ({order.client_order_id})")
        if not orders:
            typer.echo("  (no orders - already within drift bands)")
        return

    record = run_once(
        strategy, platform_config, broker_instance, asof=asof, force_research=force_research
    )
    if record.refused_reason:
        typer.echo(f"REFUSED: {record.refused_reason}", err=True)
        raise typer.Exit(code=1)
    typer.echo(
        f"asof={record.asof} strategy_id={record.strategy_id} "
        f"planned_orders={len(record.planned_orders)} results={len(record.results)}"
    )


@paper_app.command("status")
def paper_status(
    strategy: Path = typer.Option(
        ..., "--strategy", exists=True, readable=True, help="Strategy config YAML."
    ),
    platform: Path = typer.Option(
        Path("configs/platform.yaml"), "--platform", help="Path to platform.yaml."
    ),
) -> None:
    """Print the most recent journal entry for `--strategy`."""
    from quantlab.core.config import load_platform_config
    from quantlab.paper.journal import read_journal
    from quantlab.strategies.registry import load_strategy

    platform_config = load_platform_config(platform)
    strategy_obj = load_strategy(strategy)
    records = read_journal(platform_config.reports_dir, strategy_obj.strategy_id)
    if not records:
        typer.echo(f"no journal entries yet for {strategy_obj.strategy_id}")
        return
    last = records[-1]
    typer.echo(
        f"strategy_id={strategy_obj.strategy_id} last_run={last['asof']} "
        f"refused={last['refused_reason'] is not None} "
        f"n_planned_orders={len(last['planned_orders'])} n_results={len(last['results'])}"
    )


@paper_app.command("journal")
def paper_journal(
    strategy: Path = typer.Option(
        ..., "--strategy", exists=True, readable=True, help="Strategy config YAML."
    ),
    platform: Path = typer.Option(
        Path("configs/platform.yaml"), "--platform", help="Path to platform.yaml."
    ),
) -> None:
    """Print the full journal history for `--strategy` as a table."""
    from quantlab.core.config import load_platform_config
    from quantlab.paper.journal import journal_to_frame
    from quantlab.strategies.registry import load_strategy

    platform_config = load_platform_config(platform)
    strategy_obj = load_strategy(strategy)
    frame = journal_to_frame(platform_config.reports_dir, strategy_obj.strategy_id)
    if frame.empty:
        typer.echo(f"no journal entries yet for {strategy_obj.strategy_id}")
        return
    typer.echo(frame.to_string())


@paper_app.command("rebaseline")
def paper_rebaseline(
    strategy: Path = typer.Option(
        ..., "--strategy", exists=True, readable=True, help="Strategy config YAML."
    ),
    broker: str = typer.Option("mock", "--broker", help="'mock' or 'alpaca'."),
    reason: str = typer.Option(
        ..., "--reason", help="Why this re-baseline is happening (recorded verbatim, required)."
    ),
    platform: Path = typer.Option(
        Path("configs/platform.yaml"), "--platform", help="Path to platform.yaml."
    ),
) -> None:
    """Explicitly accept the broker's CURRENT account as the new reconcile
    baseline (quant-gate VERDICT.md M08 cycle-1 finding 1) - for a mismatch
    `run_once`'s automatic corporate-action roll-forward cannot explain (a
    manual trade, a transfer, an action this platform's data does not
    carry). Writes a loud, journaled `kind="rebaseline"` record with the
    diff against what was previously expected; never trades."""
    from quantlab.core.config import load_platform_config
    from quantlab.paper.runner import accept_broker_state

    platform_config = load_platform_config(platform)
    broker_instance = _make_broker(broker)

    record = accept_broker_state(strategy, platform_config, broker_instance, reason=reason)
    typer.echo(f"re-baselined asof={record.asof} strategy_id={record.strategy_id}: {reason}")
    if record.reconcile_report:
        diff = record.reconcile_report
        typer.echo(
            f"  cash_diff={diff['cash_diff']:.2f}  "
            f"position_mismatches={len(diff['position_mismatches'])}"
        )


if __name__ == "__main__":
    app()
