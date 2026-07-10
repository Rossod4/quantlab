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
