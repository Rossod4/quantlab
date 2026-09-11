"""Tests for backtest/result.py's `BacktestResult`/`QualityFlags`
save/load round-trip (work packet acceptance criterion 10)."""

from __future__ import annotations

import pandas as pd
import pytest

from quantlab.backtest.result import BacktestResult, QualityFlags
from quantlab.core.types import PortfolioSnapshot, Position, TargetWeights
from quantlab.data.survivorship import CoverageReport


def _series(values: dict[str, float]) -> pd.Series:
    return pd.Series({pd.Timestamp(k): v for k, v in values.items()}, dtype=float).sort_index()


def _sample_result() -> BacktestResult:
    dates = {"2020-01-31": 0.01, "2020-02-29": -0.02, "2020-03-31": 0.03}
    gross = _series(dates)
    net = gross - 0.001
    gross_equity = (1 + gross).cumprod()
    net_equity = (1 + net).cumprod()
    bench = _series({"2020-02-29": 0.005, "2020-03-31": 0.007})
    bench_equity = (1 + bench).cumprod()
    turnover = _series({"2020-01-31": 1.0, "2020-02-29": 0.3, "2020-03-31": 0.4})
    cost_drag = _series({"2020-01-31": 0.001, "2020-02-29": 0.001, "2020-03-31": 0.001})

    holdings_history = {
        pd.Timestamp("2020-01-31"): TargetWeights(
            asof="2020-01-31", weights={"AAA": 1.0}, strategy_id="momentum-abc0000000"
        ),
    }
    snapshots = {
        pd.Timestamp("2020-01-31"): PortfolioSnapshot(
            date="2020-01-31",
            cash=0.0,
            positions={"AAA": Position(ticker="AAA", qty=100.0, avg_cost=10.0)},
            equity=1000.0,
        )
    }
    quality_flags = QualityFlags(
        forced_exits=1,
        extreme_returns=2,
        missing_forward_prices=1,
        unscoreable_dates=("2020-02-29",),
        dropped_tickers_by_date={"2020-01-31": ["ZZZ"]},
        unscored_by_date={"2020-02-29": ["YYY"]},
    )
    coverage_report = CoverageReport(
        by_year=pd.Series({2020: 12.5}, dtype=float),
        overall_bound=12.5,
        masked_tickers={2020: ["MMM"]},
    )
    provenance = {
        "strategy_id": "momentum-abc0000000",
        "run_timestamp": "2024-01-01T00:00:00",
        "nested": {"a": 1, "b": [1, 2, 3]},
        "known_caveats": [],
    }

    return BacktestResult(
        gross_returns=gross,
        net_returns=net,
        gross_equity=gross_equity,
        net_equity=net_equity,
        benchmark_returns=bench,
        benchmark_equity=bench_equity,
        turnover=turnover,
        cost_drag=cost_drag,
        holdings_history=holdings_history,
        snapshots=snapshots,
        quality_flags=quality_flags,
        coverage_report=coverage_report,
        provenance=provenance,
    )


def test_save_load_round_trips_series_to_1e12(tmp_path):
    result = _sample_result()
    result.save(tmp_path)
    loaded = BacktestResult.load(tmp_path)

    for name in (
        "gross_returns",
        "net_returns",
        "gross_equity",
        "net_equity",
        "benchmark_returns",
        "benchmark_equity",
        "turnover",
        "cost_drag",
    ):
        pd.testing.assert_series_equal(
            getattr(result, name),
            getattr(loaded, name),
            check_exact=False,
            atol=1e-12,
            check_names=False,
        )


def test_save_load_round_trips_provenance_exactly(tmp_path):
    result = _sample_result()
    result.save(tmp_path)
    loaded = BacktestResult.load(tmp_path)

    assert loaded.provenance == result.provenance


def test_save_load_round_trips_holdings_and_snapshots(tmp_path):
    result = _sample_result()
    result.save(tmp_path)
    loaded = BacktestResult.load(tmp_path)

    assert loaded.holdings_history == result.holdings_history
    assert loaded.snapshots == result.snapshots


def test_save_load_round_trips_quality_flags(tmp_path):
    result = _sample_result()
    result.save(tmp_path)
    loaded = BacktestResult.load(tmp_path)

    assert loaded.quality_flags == result.quality_flags


def test_save_load_round_trips_coverage_report(tmp_path):
    result = _sample_result()
    result.save(tmp_path)
    loaded = BacktestResult.load(tmp_path)

    pd.testing.assert_series_equal(
        loaded.coverage_report.by_year, result.coverage_report.by_year, check_names=False
    )
    expected_bound = result.coverage_report.overall_bound
    assert loaded.coverage_report.overall_bound == pytest.approx(expected_bound)
    assert loaded.coverage_report.masked_tickers == result.coverage_report.masked_tickers


def test_save_creates_output_directory(tmp_path):
    out = tmp_path / "nested" / "dir"
    result = _sample_result()
    result.save(out)
    assert (out / "provenance.json").exists()
