"""`BacktestResult`: the immutable, serializable output of `engine.run_backtest`.

Consumed by M05-M07 (metrics, walk-forward, validation, reporting) - so it
must round-trip through disk losslessly (`save`/`load`) rather than only
existing as an in-memory object for one process's lifetime.

A plain frozen dataclass, not a pydantic model (the work packet allows
either): several fields are `pandas.Series`/`dict[..., pydantic model]`,
which pydantic's default `__eq__`/`__hash__` machinery handles awkwardly for
arbitrary types, and this module writes its own explicit JSON/parquet
(de)serialization anyway (see `save`/`load`) rather than relying on
pydantic's. `eq=False` is deliberate: the dataclass-generated `__eq__` would
compare `pandas.Series` fields with `==`, which returns an element-wise
Series and raises `ValueError` ("truth value of a Series is ambiguous") the
moment Python's tuple-equality machinery tries to coerce it to `bool` -
tests compare individual fields (`pandas.testing.assert_series_equal`,
plain dict `==`) instead, per the work packet's acceptance criterion 10.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from quantlab.core.types import PortfolioSnapshot, TargetWeights
from quantlab.data.survivorship import CoverageReport


@dataclass(frozen=True)
class QualityFlags:
    """Every data-quality exclusion/adjustment the engine made, so a result
    is never silently "cleaner" than the data actually was (CLAUDE.md
    invariant #2's spirit, extended from survivorship to run-time quality).

    `forced_exits` / `missing_forward_prices`: count together every time a
    held name's price series ended before the period end it was supposed to
    be marked at (CLAUDE.md invariant #3's forced-exit path) - the two
    counters are currently always equal (M04 unifies the old repo's separate
    "missing forward price" and "forced exit" concepts into one trigger; see
    engine.py's module docstring), kept as two fields to match the field
    names the work packet specifies.
    `extreme_returns`: count of held-name returns flagged by the upside-only
    extreme-return guard (engine.py port of EXTREME_MONTHLY_RETURN_BOUND) =
    `extreme_returns_long + extreme_returns_short`. Counted PER BOOK
    (quant-gate VERDICT.md finding 4(a), matching the old repo's
    `long_short_engine.py` long_extreme/short_extreme convention) because
    the guard's bias direction flips by book: excluding a flagged LONG
    name is conservative (it discards a spurious gain), but excluding a
    flagged SHORT name discards precisely the adverse move a short book
    must not be allowed to hide - see engine.py's module docstring. Under
    `BacktestConfig.extreme_return_policy="flag_only"` these still count
    every trigger, but nothing is excluded/renormalized.
    `unscoreable_dates`: rebalance dates where the strategy itself raised
    (e.g. momentum's disjoint-books guard) and `abort_on_unscoreable=False`
    caused the engine to record-and-hold-prior instead of aborting.
    `dropped_tickers_by_date`: date (ISO) -> tickers excluded from that
    rebalance's eligible universe by a per-ticker data failure (a stale/
    unfetchable actions cache - see engine.py's `_FilteringConstituentsProvider`).
    `unscored_by_date`: date (ISO) -> tickers that were in the strategy's
    declared universe but did not appear in its returned weights (the value
    leg's silent unpriceable-name drops, generalized to any strategy).
    `degenerate_excluded_book_dates`: date (ISO) -> sign-books ("long"/
    "short") where EVERY name was excluded that period under
    `extreme_return_policy="exclude_legacy"`, silently changing the
    period's net exposure (quant-gate VERDICT.md finding 4, "related, same
    function" note) - e.g. a market-neutral book briefly reading 100% net
    short. Exceedingly unlikely at the default 300% bound; recorded, never
    silently absorbed, when it happens.
    """

    forced_exits: int = 0
    extreme_returns: int = 0
    extreme_returns_long: int = 0
    extreme_returns_short: int = 0
    missing_forward_prices: int = 0
    unscoreable_dates: tuple[str, ...] = field(default_factory=tuple)
    dropped_tickers_by_date: dict[str, list[str]] = field(default_factory=dict)
    unscored_by_date: dict[str, list[str]] = field(default_factory=dict)
    degenerate_excluded_book_dates: dict[str, list[str]] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "forced_exits": self.forced_exits,
            "extreme_returns": self.extreme_returns,
            "extreme_returns_long": self.extreme_returns_long,
            "extreme_returns_short": self.extreme_returns_short,
            "missing_forward_prices": self.missing_forward_prices,
            "unscoreable_dates": list(self.unscoreable_dates),
            "dropped_tickers_by_date": self.dropped_tickers_by_date,
            "unscored_by_date": self.unscored_by_date,
            "degenerate_excluded_book_dates": self.degenerate_excluded_book_dates,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> QualityFlags:
        return cls(
            forced_exits=data["forced_exits"],
            extreme_returns=data["extreme_returns"],
            extreme_returns_long=data.get("extreme_returns_long", 0),
            extreme_returns_short=data.get("extreme_returns_short", 0),
            missing_forward_prices=data["missing_forward_prices"],
            unscoreable_dates=tuple(data.get("unscoreable_dates", [])),
            dropped_tickers_by_date=dict(data.get("dropped_tickers_by_date", {})),
            unscored_by_date=dict(data.get("unscored_by_date", {})),
            degenerate_excluded_book_dates=dict(data.get("degenerate_excluded_book_dates", {})),
        )


def _series_to_parquet(series: pd.Series, path: Path) -> None:
    frame = series.rename("value").to_frame()
    frame.index.name = "date"
    frame.to_parquet(path)


def _series_from_parquet(path: Path) -> pd.Series:
    frame = pd.read_parquet(path)
    series = frame["value"]
    series.index = pd.DatetimeIndex(series.index, name="date")
    return series


_SERIES_FIELDS = (
    "gross_returns",
    "net_returns",
    "gross_equity",
    "net_equity",
    "benchmark_returns",
    "benchmark_equity",
    "turnover",
    "cost_drag",
)


@dataclass(frozen=True, eq=False)
class BacktestResult:
    """See module docstring. All `pandas.Series` fields are indexed by
    tz-naive `pd.Timestamp`; `gross_equity`/`net_equity`/`benchmark_equity`
    are prepended with a synthetic 1.0 entry at the run's first rebalance
    date (work packet: "start 1.0")."""

    gross_returns: pd.Series
    net_returns: pd.Series
    gross_equity: pd.Series
    net_equity: pd.Series
    benchmark_returns: pd.Series
    benchmark_equity: pd.Series
    turnover: pd.Series
    cost_drag: pd.Series
    holdings_history: dict[pd.Timestamp, TargetWeights]
    snapshots: dict[pd.Timestamp, PortfolioSnapshot]
    quality_flags: QualityFlags
    coverage_report: CoverageReport
    provenance: dict[str, Any]

    def save(self, out_dir: str | Path) -> None:
        """Serialize to `out_dir` (created if missing): one parquet file per
        Series field, one JSON file per dict/dataclass field. `load(out_dir)`
        is the exact inverse."""
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)

        for name in _SERIES_FIELDS:
            _series_to_parquet(getattr(self, name), out / f"{name}.parquet")

        holdings_json = {
            str(pd.Timestamp(d).date()): tw.model_dump(mode="json")
            for d, tw in self.holdings_history.items()
        }
        (out / "holdings_history.json").write_text(json.dumps(holdings_json))

        snapshots_json = {
            str(pd.Timestamp(d).date()): snap.model_dump(mode="json")
            for d, snap in self.snapshots.items()
        }
        (out / "snapshots.json").write_text(json.dumps(snapshots_json))

        (out / "quality_flags.json").write_text(json.dumps(self.quality_flags.to_json()))

        coverage_json = {
            "by_year": {str(y): v for y, v in self.coverage_report.by_year.items()},
            "overall_bound": self.coverage_report.overall_bound,
            "masked_tickers": {str(y): v for y, v in self.coverage_report.masked_tickers.items()},
            "quarantined_tickers": {
                str(y): v for y, v in self.coverage_report.quarantined_tickers.items()
            },
            "masked_start_tickers": {
                str(y): v for y, v in self.coverage_report.masked_start_tickers.items()
            },
        }
        (out / "coverage_report.json").write_text(json.dumps(coverage_json))

        (out / "provenance.json").write_text(json.dumps(self.provenance, sort_keys=True))

    @classmethod
    def load(cls, out_dir: str | Path) -> BacktestResult:
        out = Path(out_dir)
        series = {name: _series_from_parquet(out / f"{name}.parquet") for name in _SERIES_FIELDS}

        holdings_json = json.loads((out / "holdings_history.json").read_text())
        holdings_history = {
            pd.Timestamp(d): TargetWeights.model_validate(v) for d, v in holdings_json.items()
        }

        snapshots_json = json.loads((out / "snapshots.json").read_text())
        snapshots = {
            pd.Timestamp(d): PortfolioSnapshot.model_validate(v) for d, v in snapshots_json.items()
        }

        quality_flags = QualityFlags.from_json(json.loads((out / "quality_flags.json").read_text()))

        coverage_data = json.loads((out / "coverage_report.json").read_text())
        by_year = pd.Series(
            {int(y): v for y, v in coverage_data["by_year"].items()},
            name="pct_lacking_coverage",
            dtype=float,
        ).sort_index()
        coverage_report = CoverageReport(
            by_year=by_year,
            overall_bound=coverage_data["overall_bound"],
            masked_tickers={int(y): v for y, v in coverage_data["masked_tickers"].items()},
            quarantined_tickers={
                int(y): v for y, v in coverage_data.get("quarantined_tickers", {}).items()
            },
            masked_start_tickers={
                int(y): v for y, v in coverage_data.get("masked_start_tickers", {}).items()
            },
        )

        provenance = json.loads((out / "provenance.json").read_text())

        return cls(
            **series,
            holdings_history=holdings_history,
            snapshots=snapshots,
            quality_flags=quality_flags,
            coverage_report=coverage_report,
            provenance=provenance,
        )
