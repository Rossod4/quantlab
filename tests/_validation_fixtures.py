"""Shared `BacktestResult` fixture builder for the M05 validation test
suite (tests/test_metrics.py, test_rolling.py, test_walk_forward.py,
test_sensitivity.py, test_validation_basic.py). Not itself a test module
(no `test_` prefix) so pytest does not try to collect it.
"""

from __future__ import annotations

import pandas as pd

from quantlab.backtest.result import BacktestResult, QualityFlags
from quantlab.data.survivorship import CoverageReport


class Exploding:
    """A value that raises on essentially any use - for asserting a field
    is never touched (e.g. `BacktestResult.snapshots` by `metrics.summary`,
    per the carried M04 verdict item 1)."""

    def _boom(self, *_args: object, **_kwargs: object) -> None:
        raise AssertionError("this field must not be accessed")

    __getattr__ = _boom
    __getitem__ = _boom
    __iter__ = _boom
    __len__ = _boom
    __bool__ = _boom


def _equity_with_synthetic_start(returns: pd.Series) -> pd.Series:
    """Mirrors `BacktestResult`'s own convention (result.py docstring):
    equity is prepended with a synthetic 1.0 entry at the run's first
    rebalance date's predecessor."""
    start_date = returns.index[0] - pd.Timedelta(days=1)
    equity = (1 + returns).cumprod()
    return pd.concat([pd.Series([1.0], index=[start_date]), equity])


def make_backtest_result(
    *,
    net_returns: pd.Series,
    gross_returns: pd.Series | None = None,
    benchmark_returns: pd.Series | None = None,
    turnover: pd.Series | None = None,
    rebalance_freq: str = "month_end",
    quality_flags: QualityFlags | None = None,
    coverage_bound: float = 0.0,
    snapshots: object = None,
    strategy_id: str = "momentum-0000000000",
    data_semantics_version: str = "m03b",
    initial_capital: float = 1_000_000.0,
    known_caveats: list[str] | None = None,
    holdings_history: dict | None = None,
    dirty: bool | None = None,
    start: str | None = None,
    end: str | None = None,
    strategy_config: str | None = None,
) -> BacktestResult:
    """Build a minimal, real `BacktestResult` for offline validation tests.
    Every field the validation suite is allowed to read is populated
    honestly; `snapshots` (never read by any validation code - carried M04
    verdict item 1) defaults to empty/exploding rather than realistic data.

    `strategy_id`/`data_semantics_version`/`initial_capital`/`known_caveats`
    (new for M06 - registry.py/report_card.py read `result.provenance` for
    these) default to fixed, deterministic values so existing M05 callers
    (which never inspected them) are unaffected. `holdings_history` (new for
    M06 - capacity.py derives `position_frac` from it) defaults to `{}`,
    same as before. `dirty` (new for M06b): when given, written into
    `provenance["dirty"]` so `registry.py` can prefer it over its own
    `git status` fallback; omitted (`None`, the default) leaves the key out
    of `provenance` entirely, exercising the fallback path. `start`/`end`
    (new for M06's `--full` capacity wiring) default to `net_returns`'s own
    first/last dates. `strategy_config` (new for M06 cycle-1 finding 5's
    CLI sensitivity wiring): when given, written into
    `provenance["backtest_config"]["strategy_config"]` so
    `cli._build_sensitivity_result` has enough to reconstruct a
    `BacktestConfig`; omitted (the default) leaves the key out.
    """
    if gross_returns is None:
        gross_returns = net_returns
    if benchmark_returns is None:
        benchmark_returns = net_returns * 0.0

    net_equity = _equity_with_synthetic_start(net_returns)
    gross_equity = _equity_with_synthetic_start(gross_returns)
    benchmark_equity = _equity_with_synthetic_start(benchmark_returns)

    if turnover is None:
        turnover = pd.Series(0.1, index=net_returns.index)
    cost_drag = pd.Series(0.0, index=net_returns.index)

    provenance: dict[str, object] = {
        "strategy_id": strategy_id,
        "data_semantics_version": data_semantics_version,
        "quantlab_git_sha": "test-sha",
        "known_caveats": known_caveats or [],
        "backtest_config": {
            "rebalance_freq": rebalance_freq,
            "initial_capital": initial_capital,
            "start": start or str(net_returns.index[0].date()),
            "end": end or str(net_returns.index[-1].date()),
        },
    }
    if dirty is not None:
        provenance["dirty"] = dirty
    if strategy_config is not None:
        provenance["backtest_config"]["strategy_config"] = strategy_config

    return BacktestResult(
        gross_returns=gross_returns,
        net_returns=net_returns,
        gross_equity=gross_equity,
        net_equity=net_equity,
        benchmark_returns=benchmark_returns,
        benchmark_equity=benchmark_equity,
        turnover=turnover,
        cost_drag=cost_drag,
        holdings_history={} if holdings_history is None else holdings_history,
        snapshots={} if snapshots is None else snapshots,
        quality_flags=quality_flags if quality_flags is not None else QualityFlags(),
        coverage_report=CoverageReport(
            by_year=pd.Series(dtype=float), overall_bound=coverage_bound, masked_tickers={}
        ),
        provenance=provenance,
    )
