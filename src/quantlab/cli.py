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


data_app = typer.Typer(name="data", help="Fetch, refresh, scan and inspect cached market data.")
app.add_typer(data_app, name="data")


@data_app.command("prefetch")
def data_prefetch(
    start: str = typer.Option(..., "--start", help="Window start date (YYYY-MM-DD)."),
    end: str = typer.Option(..., "--end", help="Window end date (YYYY-MM-DD)."),
    universe: str = typer.Option(
        "sp500_history", "--universe", help="Universe to prefetch (only sp500_history today)."
    ),
    platform: Path = typer.Option(
        Path("configs/platform.yaml"), "--platform", help="Path to platform.yaml."
    ),
) -> None:
    """Prefetch prices, corporate actions and EDGAR fundamentals for every
    point-in-time constituent over [--start, --end] plus the benchmark -
    formalises the orchestrator's ad hoc prefetch script
    (`quantlab.data.ops.prefetch`). Idempotent; writes a per-ticker failure
    summary to `<cache_dir>/prefetch_report.json`."""
    from quantlab.core.config import load_platform_config
    from quantlab.data.ops import prefetch as run_prefetch

    platform_config = load_platform_config(platform)
    report = run_prefetch(platform_config, start, end, universe=universe)
    typer.echo(
        f"prefetched {report.universe_size} ticker(s) over [{report.start}, {report.end}] "
        f"in {report.wall_seconds:.1f}s - "
        f"price failures: {len(report.price_failures)}, "
        f"actions failures: {len(report.actions_failures)}, "
        f"fundamentals failures: {len(report.fundamentals_failures)}"
    )


@data_app.command("refresh")
def data_refresh(
    tickers: str | None = typer.Option(
        None, "--tickers", help="Comma-separated ticker list to act on."
    ),
    all_: bool = typer.Option(
        False, "--all", help="Act on every ticker with any price sidecar in the cache."
    ),
    actions: bool = typer.Option(
        False, "--actions", help="Force a fresh corporate-actions download (clears staleness)."
    ),
    prices: bool = typer.Option(
        False, "--prices", help="Re-fetch prices through --as-of (default: today)."
    ),
    fundamentals: bool = typer.Option(
        False, "--fundamentals", help="Force a fresh EDGAR companyfacts download."
    ),
    clear_negative_cache: bool = typer.Option(
        False,
        "--clear-negative-cache",
        help="Force-clear a no_data sidecar (scoped to --tickers, else every no_data ticker).",
    ),
    unquarantine: str | None = typer.Option(
        None, "--unquarantine", help="Clear one ticker's quarantine, re-fetch, and re-scan it."
    ),
    as_of: str | None = typer.Option(
        None, "--as-of", help="As-of date for --prices/--unquarantine (default: today)."
    ),
    platform: Path = typer.Option(
        Path("configs/platform.yaml"), "--platform", help="Path to platform.yaml."
    ),
) -> None:
    """Operational data-refresh command - wires up `refresh_actions_cache`
    (the only way to clear a StaleActionsCacheError), the negative-cache
    force-clear, and quarantine re-scan (`quantlab.data.ops.refresh`)."""
    from quantlab.core.config import load_platform_config
    from quantlab.data.ops import refresh as run_refresh

    platform_config = load_platform_config(platform)
    ticker_list = [t.strip() for t in tickers.split(",") if t.strip()] if tickers else None
    report = run_refresh(
        platform_config,
        tickers=ticker_list,
        do_all=all_,
        actions=actions,
        prices=prices,
        fundamentals=fundamentals,
        clear_negative_cache=clear_negative_cache,
        unquarantine=unquarantine,
        as_of=as_of,
    )
    typer.echo(f"refreshed {len(report.tickers)} ticker(s)")
    if actions:
        typer.echo(
            f"  actions: {len(report.actions_refreshed)} refreshed, "
            f"{len(report.actions_failures)} failed"
        )
    if prices:
        typer.echo(
            f"  prices: {len(report.prices_refreshed)} refreshed, "
            f"{len(report.prices_failures)} failed"
        )
    if fundamentals:
        typer.echo(
            f"  fundamentals: {len(report.fundamentals_refreshed)} refreshed, "
            f"{len(report.fundamentals_failures)} failed"
        )
    if clear_negative_cache:
        typer.echo(f"  negative-cache cleared: {len(report.negative_cache_cleared)}")
    if unquarantine is not None:
        typer.echo(f"  unquarantine {unquarantine}: {report.unquarantine_result}")


@data_app.command("scan")
def data_scan(
    platform: Path = typer.Option(
        Path("configs/platform.yaml"), "--platform", help="Path to platform.yaml."
    ),
    with_membership: bool = typer.Option(
        True,
        "--with-membership/--no-membership",
        help="Also run the membership-aware symbol-reuse detector (needs the constituents "
        "provider; slower, more thorough).",
    ),
) -> None:
    """Scan the on-disk price cache for corrupt/reused-symbol tickers
    (`data/quality.py`'s `scan_price_cache`) and quarantine any that fail.
    Offline; writes/updates each quarantined ticker's sidecar plus a
    cache-level scan-coverage manifest."""
    from quantlab.core.config import load_platform_config
    from quantlab.data.interfaces import build_provider
    from quantlab.data.ops import scan as run_scan

    platform_config = load_platform_config(platform)
    constituents_provider = None
    if with_membership:
        constituents_provider = build_provider(
            "constituents", platform_config.providers.constituents, platform_config
        )
    report = run_scan(platform_config, constituents_provider=constituents_provider)
    typer.echo(f"scanned {report.scanned_count} ticker(s); quarantined {len(report.quarantined)}")
    for ticker, reasons in sorted(report.quarantined.items()):
        typer.echo(f"  {ticker}: {'; '.join(reasons)}")


@data_app.command("status")
def data_status(
    platform: Path = typer.Option(
        Path("configs/platform.yaml"), "--platform", help="Path to platform.yaml."
    ),
) -> None:
    """Cache coverage report: per-kind ticker counts, the actions cache's
    fetched_at range, negative-cache/quarantine/masked-truncation counts,
    and how many cached tickers no scan has ever visited."""
    from quantlab.core.config import load_platform_config
    from quantlab.data.ops import status as run_status

    platform_config = load_platform_config(platform)
    report = run_status(platform_config)
    typer.echo(
        f"prices: {report.price_ticker_count}  actions: {report.actions_ticker_count}  "
        f"fundamentals: {report.fundamentals_ticker_count}"
    )
    typer.echo(
        f"actions fetched_at range: {report.actions_fetched_at_oldest} - "
        f"{report.actions_fetched_at_newest}"
    )
    typer.echo(f"no_data (negative cache): {report.no_data_count}")
    typer.echo(f"quarantined: {len(report.quarantined)}")
    for ticker, reasons in sorted(report.quarantined.items()):
        typer.echo(f"  {ticker}: {'; '.join(reasons)}")
    typer.echo(f"masked truncations: {report.masked_truncation_count}")
    typer.echo(
        f"never scanned: {report.never_scanned_count} "
        f"(last scan: {report.scan_checked_at or 'never'})"
    )


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
    netted_grid_result: list[str] = typer.Option(
        [],
        "--netted-grid-result",
        help="'w1,w2=<dir>': a saved blend BacktestResult at those INTERIOR weights, for the "
        "walk-forward ranking-agreement check (repeat per interior grid point; the one-hot "
        "endpoints come from --child-result). Only meaningful with --full and --child-result.",
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

    ranking_kwargs = _build_ranking_kwargs(
        bt_result, walk_forward_result, child_result, netted_grid_result, validation_config
    )

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
            **ranking_kwargs,
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
        result = sensitivity_grid(
            backtest_config_dict["strategy_config"],
            param_axes,
            backtest_config,
            runner,
            base_provider_calls=bt_result.provenance.get("total_provider_calls"),
        )
        # M09 fix ("make grid-point failures loud"): a PARTIAL grid failure
        # no longer aborts the whole result (see sensitivity.py's own
        # docstring), so it must not go unnoticed just because the overall
        # call succeeded - echo every per-point failure and provider-call
        # warning here, in addition to `sensitivity_grid`'s own immediate
        # logging, so a `--full` run's own console output names them too.
        for params, reason in result.failed_points.items():
            typer.echo(f"  (sensitivity grid point {params} failed: {reason})", err=True)
        for warning in result.provider_call_warnings:
            typer.echo(f"  (sensitivity {warning})", err=True)
        return result
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
    never called from product code before this.

    M09 fix (orchestrator-directed): forwards `sensitivity_result.
    net_returns_by_strategy_id` (populated by `sensitivity_grid` itself,
    from each grid point's OWN return series, not re-derived here) into
    `record_sensitivity`'s `net_returns_by_strategy_id` - before this fix,
    every sensitivity trial was recorded Sharpe-only (no stored series),
    which permanently starved `build_trial_matrix` (reality_check.py) of
    enough series-bearing trials to ever run White's Reality Check / Hansen
    SPA at all, regardless of how many grid points had actually run."""
    from quantlab.validation.metrics import PERIODS_PER_YEAR

    backtest_config_dict = bt_result.provenance.get("backtest_config", {})
    rebalance_freq = backtest_config_dict.get("rebalance_freq")
    periods_per_year = PERIODS_PER_YEAR.get(rebalance_freq) if rebalance_freq else None
    registry.record_sensitivity(
        sensitivity_result,
        family=family or "unknown",
        periods_per_year=periods_per_year,
        net_returns_by_strategy_id=sensitivity_result.net_returns_by_strategy_id,
        # The grid ran from the same tree as the headline backtest; use ITS
        # run-time state, not `git status` now (the run has since rewritten
        # its own tracked report artefacts).
        dirty=bt_result.provenance.get("dirty"),
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
        from quantlab.validation.metrics import PERIODS_PER_YEAR
        from quantlab.validation.walk_forward import walk_forward_blend

        children = [BacktestResult.load(d) for d in child_result_dirs]
        _check_child_rebalance_frequencies(children, child_result_dirs)
        wf = validation_config.walk_forward
        # M09 fix: this used to default to `walk_forward_blend`'s own
        # QUARTERS_PER_YEAR=4 unconditionally - correct for the OLD repo's
        # quarterly blend sweep (this module's own docstring), but WRONG
        # whenever the children actually rebalance monthly (quantlab's own
        # shipped momentum_12_1_2012_2026.yaml / value_composite_2012_2026.yaml
        # both use rebalance_freq: month_end) - `train_len`/`test_len` would
        # then count MONTHS as if they were quarters (a 5-year training
        # window becomes 20 months, not 20 quarters) and the Sharpe
        # annualization would use sqrt(4) instead of sqrt(12).
        # `_check_child_rebalance_frequencies` above already guarantees every
        # child shares ONE frequency, so deriving it from the first child is
        # exact, not a guess.
        rebalance_freq = children[0].provenance.get("backtest_config", {}).get("rebalance_freq")
        periods_per_year = PERIODS_PER_YEAR.get(rebalance_freq, 4)
        return walk_forward_blend(
            [c.net_returns for c in children],
            weight_grid=[tuple(w) for w in wf.weight_grid],
            train_years=wf.train_years,
            test_years=wf.test_years,
            periods_per_year=periods_per_year,
            child_labels=tuple(d.name for d in child_result_dirs),
        )
    except Exception as exc:  # noqa: BLE001 - degrade to "no walk-forward", never crash --full
        typer.echo(f"  (walk-forward skipped: {exc})", err=True)
        return None


def _build_ranking_kwargs(
    bt_result: BacktestResult,
    walk_forward: WalkForwardResult | None,
    child_result_dirs: list[Path],
    netted_grid_specs: list[str],
    validation_config: ValidationConfig,
) -> dict:
    """`build_report_card` kwargs for the walk-forward ranking-agreement
    check (`validation/netted_grid.py` owns the logic and the window choice).
    Empty when there is no walk-forward (nothing to rank); otherwise either
    the real netted-book Sharpes with their provenance, or an explicit
    "not checked: <reason>" - never a crash, never a silent None."""
    if walk_forward is None:
        if netted_grid_specs:
            return {
                "ranking_not_checked_reason": "--netted-grid-result supplied but no walk-forward "
                "was built (needs a blend headline and >= 2 loadable --child-result; see stderr)"
            }
        return {}
    from quantlab.backtest.result import BacktestResult
    from quantlab.validation.netted_grid import build_netted_book_grid, parse_grid_spec

    try:
        specs = [parse_grid_spec(s) for s in netted_grid_specs]
        children = [BacktestResult.load(d) for d in child_result_dirs]
        outcome = build_netted_book_grid(
            headline=bt_result,
            walk_forward=walk_forward,
            weight_grid=[tuple(w) for w in validation_config.walk_forward.weight_grid],
            child_results=children,
            child_dirs=list(child_result_dirs),
            grid_specs=specs,
        )
    except Exception as exc:  # noqa: BLE001 - degrade to "not checked", never crash --full
        return {"ranking_not_checked_reason": f"could not assemble inputs: {exc}"}
    if outcome.sharpes is None:
        return {"ranking_not_checked_reason": outcome.reason}
    return {
        "netted_book_grid_sharpes": outcome.sharpes,
        "ranking_agreement_detail": {"window": outcome.window, "inputs": outcome.inputs},
    }


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


_VERDICT_EXIT_CODES = {"ELIGIBLE_FOR_PAPER": 0, "RESEARCH_ONLY": 2, "REJECTED": 3}


@app.command()
def run(
    backtest: Path = typer.Option(..., "--backtest", exists=True, help="Backtest config YAML."),
    strategy: Path | None = typer.Option(
        None,
        "--strategy",
        exists=True,
        help="Strategy YAML - overrides the --backtest config's own strategy_config.",
    ),
    validation: Path = typer.Option(
        Path("configs/validation.yaml"), "--validation", help="Path to validation.yaml."
    ),
    out: Path = typer.Option(..., "--out", help="Directory for all three artefacts."),
    platform: Path = typer.Option(
        Path("configs/platform.yaml"), "--platform", help="Path to platform.yaml."
    ),
    child_result: list[Path] = typer.Option(
        [],
        "--child-result",
        help="Saved child-sleeve BacktestResult directory (blend only; repeat per child, at "
        "least 2) - enables the walk-forward weight check on the blend's card.",
    ),
    netted_grid_result: list[str] = typer.Option(
        [],
        "--netted-grid-result",
        help="'w1,w2=<dir>': saved blend BacktestResult at an INTERIOR grid weight (repeat), "
        "for the walk-forward ranking-agreement check; endpoints come from --child-result.",
    ),
) -> None:
    """One command: backtest -> validate --full -> report, writing the
    BacktestResult, `validation_basic.json`, `report_card.json`/`.md` and
    the rendered report into `--out`, and updating the trials registry.

    Exit code reflects the verdict, so a scheduler can branch on it:
    0 = ELIGIBLE_FOR_PAPER, 2 = RESEARCH_ONLY, 3 = REJECTED.

    For a blend, `--child-result` (twice) adds the walk-forward weight check
    and `--netted-grid-result` (once per interior grid weight) the ranking-
    agreement check under both cost conventions; both are optional, and a
    missing or mismatched input is reported on the card as "not checked:
    <reason>"."""
    import json
    import time

    from quantlab.backtest.config import load_backtest_config
    from quantlab.backtest.engine import build_backtest_providers
    from quantlab.backtest.engine import run_backtest as _run_backtest_engine
    from quantlab.core.config import load_platform_config
    from quantlab.reporting.render import render_report
    from quantlab.strategies.registry import load_strategy
    from quantlab.validation.basic import load_validation_config, validate_basic
    from quantlab.validation.registry import TrialsRegistry
    from quantlab.validation.report_card import build_report_card

    t0 = time.perf_counter()
    platform_config = load_platform_config(platform)
    backtest_config = load_backtest_config(backtest, platform_config)
    if strategy is not None:
        backtest_config = backtest_config.model_copy(update={"strategy_config": strategy.resolve()})
    strategy_obj = load_strategy(backtest_config.strategy_config)
    providers = build_backtest_providers(platform_config)
    out.mkdir(parents=True, exist_ok=True)

    typer.echo(f"[1/3] backtest: {backtest_config.strategy_config.name} ...")
    result = _run_backtest_engine(strategy_obj, backtest_config, providers)
    result.save(out)
    typer.echo(f"  done in {result.provenance['run_seconds']:.1f}s")

    typer.echo("[2/3] validate --full ...")
    validation_config = load_validation_config(validation)
    sensitivity_result = _build_sensitivity_result(result, platform, validation_config)
    walk_forward_result = None
    if child_result:
        walk_forward_result = _build_walk_forward_result(result, child_result, validation_config)
    ranking_kwargs = _build_ranking_kwargs(
        result, walk_forward_result, child_result, netted_grid_result, validation_config
    )
    basic = validate_basic(
        result,
        None,
        validation_config,
        walk_forward=walk_forward_result,
        sensitivity=sensitivity_result,
    )
    (out / "validation_basic.json").write_text(
        json.dumps(basic.to_json(), sort_keys=True), encoding="utf-8"
    )

    registry = TrialsRegistry(platform_config.reports_dir)
    registry.seed_historical_blend_trials()
    price_panel, missing_tickers = _build_capacity_price_panel(result, platform_config)
    strategy_id = result.provenance.get("strategy_id", "")
    family = strategy_id.rsplit("-", 1)[0] if strategy_id else ""
    if sensitivity_result is not None:
        _record_sensitivity_result(result, sensitivity_result, family, registry)

    report_card = build_report_card(
        result,
        None,
        registry,
        validation_config,
        walk_forward=walk_forward_result,
        sensitivity=sensitivity_result,
        price_panel=price_panel,
        price_panel_missing_tickers=missing_tickers,
        **ranking_kwargs,
    )
    (out / "report_card.json").write_text(
        json.dumps(report_card.to_json(), sort_keys=True), encoding="utf-8"
    )
    (out / "report_card.md").write_text(
        _report_card_markdown(result, report_card), encoding="utf-8"
    )
    typer.echo(f"  verdict: {report_card.verdict}")
    for gate in report_card.gates:
        status_str = "PASS" if gate.passed else "FAIL"
        typer.echo(f"    [{gate.kind:13s} {status_str}] {gate.name}: {gate.reason}")

    typer.echo("[3/3] report ...")
    written = render_report(out, out, card_dir=out, config=validation_config, fmt="both")
    for kind, path in written.items():
        typer.echo(f"  wrote {kind}: {path}")

    typer.echo(
        f"quantlab run finished in {time.perf_counter() - t0:.1f}s - verdict {report_card.verdict}"
    )
    raise typer.Exit(code=_VERDICT_EXIT_CODES[report_card.verdict])


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

    # M09 fix (quant-gate carried item): `--dry-run` used to be a hand-rolled
    # second decide-and-plan path that wired none of `set_context_factory`,
    # the proactive actions-cache refresh, forced exits, `attempt` numbering
    # or `PaperRunConfig` - measured to diverge from a real run on a stale
    # cache fixture. `run_once(..., dry_run=True)` now runs the IDENTICAL
    # pipeline and stops before `broker.submit()` (see its own docstring);
    # this branch is now purely about how the result is PRINTED.
    record = run_once(
        strategy,
        platform_config,
        broker_instance,
        asof=asof,
        force_research=force_research,
        dry_run=dry_run,
    )
    if record.refused_reason:
        typer.echo(f"REFUSED: {record.refused_reason}", err=True)
        raise typer.Exit(code=1)
    if dry_run:
        typer.echo(f"dry-run: asof={record.asof} strategy_id={record.strategy_id}")
        for order in record.planned_orders:
            typer.echo(
                f"  {order['side']} {order['qty']} {order['ticker']} ({order['client_order_id']})"
            )
        if not record.planned_orders:
            typer.echo("  (no orders - already within drift bands)")
        return
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


@paper_app.command("drift")
def paper_drift(
    strategy: Path = typer.Option(
        ..., "--strategy", exists=True, readable=True, help="Strategy config YAML."
    ),
    platform: Path = typer.Option(
        Path("configs/platform.yaml"), "--platform", help="Path to platform.yaml."
    ),
    max_records: int | None = typer.Option(
        None,
        "--max-records",
        help="Only check the N most recent journaled trading cycles (default: all).",
    ),
) -> None:
    """Forward-vs-backtest drift check (M09, carried from the M08 verdict):
    for every journaled, actually-traded cycle, recompute the strategy's
    targets for that SAME asof on today's cache and report target-weight
    agreement, the fill-vs-model price gap, and per-ticker data-asof lag.
    See `quantlab.paper.drift`'s module docstring for the timing convention
    this models and why it does not re-run a parallel backtest."""
    import json

    from quantlab.backtest.engine import build_backtest_providers
    from quantlab.core.config import load_platform_config
    from quantlab.paper.drift import compute_drift
    from quantlab.strategies.registry import load_strategy

    platform_config = load_platform_config(platform)
    strategy_obj = load_strategy(strategy)
    providers = build_backtest_providers(platform_config)

    report = compute_drift(
        platform_config.reports_dir, strategy_obj, providers, max_records=max_records
    )
    if not report.records:
        typer.echo(f"no journaled trading cycles yet for {strategy_obj.strategy_id}")
        return
    for rec in report.records:
        if rec.error:
            typer.echo(f"{rec.asof}: recompute failed - {rec.error}")
            continue
        agreement = (
            f"{rec.target_weight_agreement:.4f}"
            if rec.target_weight_agreement is not None
            else "n/a"
        )
        typer.echo(
            f"{rec.asof} (fill assumed {rec.assumed_fill_session}): "
            f"target_weight_agreement={agreement} "
            f"max_abs_weight_diff={rec.max_abs_weight_diff!r} "
            f"only_in_journal={rec.tickers_only_in_journal} "
            f"only_in_recomputed={rec.tickers_only_in_recomputed}"
        )
        if rec.fill_vs_model_price_gap_bps:
            typer.echo(f"  fill_vs_model_price_gap_bps={rec.fill_vs_model_price_gap_bps}")
        if rec.price_asof_lag_sessions:
            typer.echo(f"  price_asof_lag_sessions={rec.price_asof_lag_sessions}")
    typer.echo(json.dumps(report.to_json(), sort_keys=True))


if __name__ == "__main__":
    app()
