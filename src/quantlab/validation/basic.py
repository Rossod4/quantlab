"""`validate_basic`: the first half of the validation report card - metrics,
rolling/sub-period robustness, and (when supplied) walk-forward and
sensitivity results, plus a `flags: list[str]` of plain-English
observations. No verdict here - M06 owns the verdict (gate thresholds live
in `configs/validation.yaml` as config, ready for M06 to read, but nothing
in this module compares against them).

Deviation from the packet's literal `validate_basic(result, benchmark_result
| None, config) -> ValidationBasic` signature, documented here and in the
handoff: walk-forward and sensitivity need inputs `validate_basic` doesn't
have access to from a single `BacktestResult` (walk-forward needs each
CHILD sleeve's own return series, not one blended result's; sensitivity
needs a strategy_config + an injected runner). Both are therefore accepted
as optional PRECOMPUTED results via keyword-only arguments and simply
carried through - `validate_basic` never calls `walk_forward_blend`/
`sensitivity_grid` itself. The three positional arguments match the packet
exactly.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from quantlab.backtest.result import BacktestResult
from quantlab.core.errors import ConfigError
from quantlab.validation.metrics import PERIODS_PER_YEAR, MetricsSummary, summary
from quantlab.validation.rolling import (
    first_second_half_splits,
    rolling_window_metrics,
    subperiod_table,
)
from quantlab.validation.sensitivity import SensitivityResult
from quantlab.validation.walk_forward import WalkForwardResult

# --- config (configs/validation.yaml) --------------------------------------


class RollingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window_years: list[int] = Field(default_factory=lambda: [3])


class WalkForwardAxisConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    train_years: int = 5
    test_years: int = 1
    weight_grid: list[list[float]] = Field(default_factory=list)


class ValidationConfig(BaseModel):
    """Rolling window years, regime splits, walk-forward train/test years
    and weight grid, sensitivity axes per strategy family, and the M06 gate
    thresholds - all config, not code, per the work packet."""

    model_config = ConfigDict(extra="forbid")

    rolling: RollingConfig = Field(default_factory=RollingConfig)
    regimes: dict[str, tuple[str, str]] = Field(default_factory=dict)
    walk_forward: WalkForwardAxisConfig = Field(default_factory=WalkForwardAxisConfig)
    sensitivity: dict[str, dict[str, list[Any]]] = Field(default_factory=dict)
    # M05 disclosure threshold (quant-gate VERDICT.md non-blocking finding
    # 6) - unlike `thresholds` below, THIS one IS read by M05's own logic:
    # validate_basic flags when the benchmark's overlap with net_returns
    # falls below this fraction.
    benchmark_overlap_min_fraction: float = Field(default=0.9, ge=0.0, le=1.0)
    # M06 gate thresholds - stored, never read by M05's own logic.
    thresholds: dict[str, Any] = Field(default_factory=dict)


def load_validation_config(path: str | Path) -> ValidationConfig:
    config_path = Path(path)
    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"could not read validation config at {config_path}: {exc}") from exc

    try:
        raw = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in validation config at {config_path}: {exc}") from exc

    try:
        return ValidationConfig.model_validate(raw)
    except ValidationError as exc:
        errors = exc.errors()
        has_loc = errors and errors[0]["loc"]
        key = ".".join(str(part) for part in errors[0]["loc"]) if has_loc else "<root>"
        raise ConfigError(f"invalid validation config key {key!r} in {config_path}") from exc


# --- result -----------------------------------------------------------------


class ValidationBasic:
    """Frozen result of `validate_basic`. A plain class (not
    `@dataclass(frozen=True)`) for the same reason as `BacktestResult`
    (result.py's module docstring): `rolling`/`subperiods` are `pandas`
    objects whose `==` is elementwise, so an auto-generated `__eq__` would
    misbehave under tuple/dataclass equality machinery. Tests compare
    fields individually."""

    def __init__(
        self,
        metrics: MetricsSummary,
        rolling: dict[int, pd.DataFrame],
        subperiods: pd.DataFrame,
        flags: list[str],
        walk_forward: WalkForwardResult | None = None,
        sensitivity: SensitivityResult | None = None,
    ) -> None:
        self.metrics = metrics
        self.rolling = rolling
        self.subperiods = subperiods
        self.flags = flags
        self.walk_forward = walk_forward
        self.sensitivity = sensitivity

    def to_json(self) -> dict[str, Any]:
        return {
            "metrics": self.metrics.to_json(),
            "rolling": {
                str(years): {str(d.date()): row.to_dict() for d, row in table.iterrows()}
                for years, table in self.rolling.items()
            },
            "subperiods": {name: row.to_dict() for name, row in self.subperiods.iterrows()},
            "flags": list(self.flags),
            "walk_forward": self.walk_forward.to_json() if self.walk_forward is not None else None,
            "sensitivity": self.sensitivity.to_json() if self.sensitivity is not None else None,
        }


def _coverage_and_selection_flag(result: BacktestResult) -> str:
    """States the RELATIONSHIP between the coverage bound and the
    unscored/dropped-ticker counts (carried M04 verdict item 4: a headline
    "how much of this book can't be trusted" figure must combine them and
    say they are separate selection effects) WITHOUT restating either
    count's number - the counts themselves are reported exactly once each,
    by their own standalone flags below (carried M04 verdict item 3;
    quant-gate VERDICT.md cycle-1 finding 3: the two used to appear here
    too, so `unscored_by_date`/`dropped_tickers_by_date` were each reported
    twice)."""
    return (
        f"coverage bound {result.coverage_report.overall_bound:.1f}% "
        f"(worst sampled year's uncached/masked universe fraction) - this bound and the "
        f"unscored-ticker / dropped-ticker counts reported separately below are SEPARATE "
        f"selection effects, not additive into one headline number"
    )


def _quality_flags(result: BacktestResult) -> list[str]:
    """Flags carried from the M04 verdict (plans/QUANT-NOTES.md): report
    `forced_exits`, `extreme_returns_long/short`, `unscored_by_date`,
    `dropped_tickers_by_date` EACH EXACTLY ONCE (as their own standalone
    flags below); never report `missing_forward_prices` as a second number
    (it duplicates `forced_exits`); state the coverage-bound/selection-
    effects relationship without repeating either count (see
    `_coverage_and_selection_flag`'s docstring)."""
    qf = result.quality_flags
    flags: list[str] = [_coverage_and_selection_flag(result)]

    if qf.forced_exits:
        flags.append(f"{qf.forced_exits} forced exit(s) booked at last available price (delisting)")
    if qf.extreme_returns_long:
        flags.append(
            f"{qf.extreme_returns_long} long-book extreme-return exclusion(s) "
            "(upside-only vendor-glitch guard)"
        )
    if qf.extreme_returns_short:
        flags.append(
            f"{qf.extreme_returns_short} short-book extreme-return exclusion(s) "
            "(upside-only guard - hides adverse moves for a short book)"
        )
    if qf.unscored_by_date:
        flags.append(
            f"{len(qf.unscored_by_date)} rebalance date(s) had declared-universe "
            "tickers left unscored (unpriceable) and dropped from weights"
        )
    if qf.dropped_tickers_by_date:
        flags.append(
            f"{len(qf.dropped_tickers_by_date)} rebalance date(s) had ticker(s) "
            "dropped by a data-availability failure"
        )
    return flags


def validate_basic(
    result: BacktestResult,
    benchmark_result: BacktestResult | None,
    config: ValidationConfig,
    *,
    walk_forward: WalkForwardResult | None = None,
    sensitivity: SensitivityResult | None = None,
) -> ValidationBasic:
    """Basic-tier validation report card for one `BacktestResult`. See the
    module docstring for why `walk_forward`/`sensitivity` are accepted
    precomputed rather than run here."""
    freq = result.provenance["backtest_config"]["rebalance_freq"]
    periods_per_year = PERIODS_PER_YEAR[freq]

    metrics_summary = summary(result, benchmark_result)

    rolling: dict[int, pd.DataFrame] = {}
    negative_window_flags: list[str] = []
    for window_years in config.rolling.window_years:
        try:
            table = rolling_window_metrics(result.net_returns, window_years, periods_per_year)
        except ValueError:
            negative_window_flags.append(
                f"insufficient history for a {window_years}-year rolling window - skipped"
            )
            continue
        rolling[window_years] = table
        negative_fraction = (table["CAGR"] < 0).mean()
        if negative_fraction > 0:
            negative_window_flags.append(
                f"{negative_fraction:.0%} of rolling {window_years}y windows negative (by CAGR)"
            )

    splits = dict(first_second_half_splits(result.net_returns.index))
    splits.update(config.regimes)
    subperiods = subperiod_table(result.net_returns, result.net_equity, splits, periods_per_year)

    flags = _quality_flags(result)
    # Quant-gate carried item 9: `benchmark_sharpe > net_sharpe` is
    # silently False whenever `benchmark_sharpe` is NaN (a zero-variance or
    # empty embedded benchmark), so the comparison used to abstain with no
    # indication a comparison was even attempted. State the NaN case
    # explicitly instead of falling through it.
    if math.isnan(metrics_summary.benchmark_sharpe):
        flags.append("no usable benchmark Sharpe (NaN) - cannot compare to strategy Sharpe")
    elif metrics_summary.benchmark_sharpe > metrics_summary.net_sharpe:
        flags.append("benchmark Sharpe exceeds strategy Sharpe")
    flags.extend(negative_window_flags)

    total_periods = len(result.net_returns)
    overlap = metrics_summary.benchmark_overlap_periods
    if total_periods > 0 and overlap / total_periods < config.benchmark_overlap_min_fraction:
        flags.append(
            f"benchmark covers {overlap} of {total_periods} periods "
            f"({overlap / total_periods:.0%}) - beta / information ratio / tracking error "
            "are computed on that overlap only"
        )

    if sensitivity is not None and sensitivity.neighbourhood_truncated:
        flags.append(
            f"sensitivity no_cliff_score's neighbourhood is truncated at a grid edge "
            f"(only {sensitivity.neighbourhood_size} point(s) examined) - treat the score "
            "as less reliable than an interior base point's"
        )
    if sensitivity is not None and sensitivity.nan_points > 0:
        flags.append(
            f"sensitivity no_cliff_score's neighbourhood had {sensitivity.nan_points} "
            "point(s) with a NaN Sharpe (e.g. zero volatility), excluded before scoring"
        )

    return ValidationBasic(
        metrics=metrics_summary,
        rolling=rolling,
        subperiods=subperiods,
        flags=flags,
        walk_forward=walk_forward,
        sensitivity=sensitivity,
    )
