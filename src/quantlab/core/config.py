"""Platform configuration: pydantic models plus a YAML loader.

All relative paths in the config (`cache_dir`, `reports_dir`) are resolved
against the repository root (the nearest ancestor directory containing
`pyproject.toml`), not against the current working directory.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from quantlab.core.errors import ConfigError


class ProvidersConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prices: str
    constituents: str
    fundamentals: str


class PlatformConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cache_dir: Path
    reports_dir: Path
    providers: ProvidersConfig
    calendar: str = "XNYS"
    benchmark: str = "SPY"
    # M04b work packet item 3: how many days a negative price-cache sidecar
    # (`no_data: true` - data/cache.py) is trusted before being retried. The
    # M01 hazard this guards against: a ticker download returning zero rows
    # could be a genuine delisting (permanent - Yahoo will never serve it
    # again) or a one-off transient vendor hiccup (temporary). Never caching
    # "no data" at all re-fetches every failed ticker on every rebalance
    # (the M04b-fixed bug); caching it forever would silently freeze a
    # transient blip as permanent. A TTL is the middle ground: skip
    # re-fetching for `retry_after_days`, then try again once.
    retry_after_days: int = 30
    # M04b quant-gate VERDICT.md cycle 1 finding 2: thresholds for
    # `data/quality.py`'s `scan_price_cache` cache-level quarantine checks -
    # see that module's docstring for what each one guards against
    # (zero-volume sessions, unexplained day-over-day price jumps, and a
    # price-level jump across a gap in trading days, evidence of a reused
    # ticker symbol).
    quality_zero_volume_fraction_threshold: float = 0.20
    # Cycle 2: a HIGH bar that quarantines on zero-volume fraction ALONE
    # (CCE/MHS-style genuinely dead series), and the ratio a price level
    # must differ from its own trailing-year median by to count as
    # "implausible" - the companion condition for the softer threshold
    # above (a live large cap's yfinance-padding-inflated fraction, e.g.
    # EA/EQR/FERG/AMCR, must NOT quarantine on the soft threshold alone).
    quality_zero_volume_hard_threshold: float = 0.50
    quality_level_implausible_ratio: float = 20.0
    quality_jump_ratio_threshold: float = 4.0
    # Cycle 2: a genuine corporate action can be recorded by the vendor's
    # actions feed a session or two off from where its price effect lands;
    # a split within this many sessions of a jump excuses it.
    quality_jump_excuse_window_sessions: int = 3
    # Cycle 2: a single unexplained jump is as often a real, un-split
    # corporate event (KDP's 2018 merger) as contamination; require several.
    quality_min_unexplained_jumps: int = 3
    quality_jump_gap_sessions: int = 5
    # Cycle 2 (second review round): a ticker whose cached price history
    # starts more than this many TRADING SESSIONS after its point-in-time
    # index membership began is presumed to belong to a DIFFERENT, newly
    # listed company reusing a delisted constituent's symbol (Yahoo silently
    # reassigns delisted ticker symbols) - see data/quality.py's
    # `symbol_reuse_new_listing_reason`.
    quality_new_listing_tolerance_sessions: int = 400


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    return Path.cwd()


def _offending_key(exc: ValidationError) -> str:
    errors = exc.errors()
    if not errors or not errors[0]["loc"]:
        return "<root>"
    return ".".join(str(part) for part in errors[0]["loc"])


def load_platform_config(path: str | Path) -> PlatformConfig:
    """Load and validate a `PlatformConfig` from a YAML file.

    Raises `ConfigError` (naming the offending key) if the file cannot be
    read, is not valid YAML, or contains an unrecognized key.
    """
    config_path = Path(path)
    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"could not read platform config at {config_path}: {exc}") from exc

    try:
        raw = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in platform config at {config_path}: {exc}") from exc

    try:
        config = PlatformConfig.model_validate(raw)
    except ValidationError as exc:
        key = _offending_key(exc)
        raise ConfigError(f"invalid platform config key {key!r} in {config_path}") from exc

    root = _repo_root()
    cache_dir = config.cache_dir if config.cache_dir.is_absolute() else root / config.cache_dir
    reports_dir = (
        config.reports_dir if config.reports_dir.is_absolute() else root / config.reports_dir
    )
    return config.model_copy(update={"cache_dir": cache_dir, "reports_dir": reports_dir})
