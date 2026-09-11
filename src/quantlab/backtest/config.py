"""`BacktestConfig`: pydantic model + YAML loader for one backtest run,
mirroring `core/config.py`'s `PlatformConfig` pattern (relative paths
resolved against the repo root, `ConfigError` naming the offending key)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from quantlab.core.calendar import RebalanceFreq
from quantlab.core.config import PlatformConfig
from quantlab.core.errors import ConfigError
from quantlab.core.types import normalize_timestamp

CostModel = Literal["flat_bps", "corwin_schultz"]
ExecutionMode = Literal["close", "next_open"]
# "exclude_legacy" (default): the old repo's own guard - excludes a flagged
# name from its sign-book's weighted return and renormalizes the survivors
# (frozen parity; applied to shorts too, matching
# long_short_engine.py's per-book exclusion - an inherited asymmetry, not a
# new bug, see engine.py's module docstring). "flag_only": counts the same
# trigger but never excludes/renormalizes - see quant-gate VERDICT.md
# finding 4.
ExtremeReturnPolicy = Literal["exclude_legacy", "flag_only"]


class BacktestConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    start: pd.Timestamp
    end: pd.Timestamp
    strategy_config: Path
    rebalance_freq: RebalanceFreq = "month_end"
    initial_capital: float = Field(default=1_000_000.0, gt=0)
    execution: ExecutionMode = "close"
    cost_model: CostModel = "flat_bps"
    one_way_cost_bps: float = Field(default=10.0, ge=0)
    corwin_schultz_lookback_days: int = Field(default=60, gt=0)
    borrow_fee_annual_bps: float = Field(default=30.0, ge=0)
    # Fraction of last available (raw) close a forced exit is booked at, per
    # CLAUDE.md invariant #3 - it now genuinely reaches the reported return
    # series, not only the ledger (quant-gate VERDICT.md finding 2). 0.0
    # (default) = exit at the FULL last close - the LEAST conservative
    # setting for a long position (assumes a forced liquidation recovers
    # 100% of the last quoted price, which real forced sales rarely do); a
    # positive haircut is MORE conservative for a long (correctly
    # understates recovered value further - matching the packet's own
    # "document that >0 is the conservative setting", not the inverted
    # claim an earlier version of this comment made). For a SHORT position
    # a haircut in the same direction is anti-conservative (it reduces the
    # cost of covering), so re-examine the direction before using a
    # nonzero haircut on a short-heavy book.
    delisting_haircut: float = Field(default=0.0, ge=0.0, le=1.0)
    # Port of the old repo's EXTREME_MONTHLY_RETURN_BOUND=3.0 (300%),
    # upside-only vendor-glitch guard - see engine.py.
    extreme_return_bound: float = Field(default=3.0, gt=0)
    extreme_return_policy: ExtremeReturnPolicy = "exclude_legacy"
    # None defers to platform.yaml's `benchmark` - see load_backtest_config.
    benchmark: str | None = None
    max_dropped_fraction: float = Field(default=0.05, ge=0.0, le=1.0)
    abort_on_unscoreable: bool = True

    @field_validator("start", "end", mode="before")
    @classmethod
    def _v_dates(cls, v: object) -> pd.Timestamp:
        return normalize_timestamp(v)


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    return Path.cwd()


def load_backtest_config(
    path: str | Path, platform_config: PlatformConfig | None = None
) -> BacktestConfig:
    """Load and validate a `BacktestConfig` from a YAML file.

    `strategy_config` is resolved relative to the repo root if not absolute.
    `benchmark`, if omitted from the YAML, defaults to `platform_config.
    benchmark` (raises `ConfigError` if omitted and no `platform_config` was
    supplied to default it from).
    """
    config_path = Path(path)
    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"could not read backtest config at {config_path}: {exc}") from exc

    try:
        raw = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in backtest config at {config_path}: {exc}") from exc

    try:
        config = BacktestConfig.model_validate(raw)
    except ValidationError as exc:
        errors = exc.errors()
        has_loc = errors and errors[0]["loc"]
        key = ".".join(str(part) for part in errors[0]["loc"]) if has_loc else "<root>"
        raise ConfigError(f"invalid backtest config key {key!r} in {config_path}") from exc

    root = _repo_root()
    strategy_config = (
        config.strategy_config
        if config.strategy_config.is_absolute()
        else root / config.strategy_config
    )

    benchmark = config.benchmark
    if benchmark is None:
        if platform_config is None:
            raise ConfigError(
                f"backtest config at {config_path} omits 'benchmark' and no platform config "
                "was supplied to default it from"
            )
        benchmark = platform_config.benchmark

    return config.model_copy(update={"strategy_config": strategy_config, "benchmark": benchmark})
