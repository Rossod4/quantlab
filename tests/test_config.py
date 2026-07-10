from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from quantlab.core.config import PlatformConfig, load_platform_config
from quantlab.core.errors import ConfigError

_PLATFORM_YAML = Path(__file__).resolve().parents[1] / "configs" / "platform.yaml"


def test_load_platform_config_round_trips() -> None:
    config = load_platform_config(_PLATFORM_YAML)

    assert isinstance(config, PlatformConfig)
    assert config.calendar == "XNYS"
    assert config.benchmark == "SPY"
    assert config.providers.prices == "yfinance"
    assert config.providers.constituents == "sp500_community"
    assert config.providers.fundamentals == "edgar"
    # Paths resolve relative to the repo root, not the cwd.
    repo_root = _PLATFORM_YAML.parents[1]
    assert config.cache_dir == repo_root / "data" / "cache"
    assert config.reports_dir == repo_root / "reports"


def test_load_platform_config_round_trips_through_dump(tmp_path: Path) -> None:
    first = load_platform_config(_PLATFORM_YAML)

    dumped_path = tmp_path / "platform.yaml"
    payload = {
        "cache_dir": str(first.cache_dir),
        "reports_dir": str(first.reports_dir),
        "providers": first.providers.model_dump(),
        "calendar": first.calendar,
        "benchmark": first.benchmark,
    }
    dumped_path.write_text(yaml.safe_dump(payload), encoding="utf-8")

    second = load_platform_config(dumped_path)
    assert second == first


def test_load_platform_config_bogus_key_raises_config_error(tmp_path: Path) -> None:
    bad_path = tmp_path / "bad_platform.yaml"
    bad_path.write_text(
        yaml.safe_dump(
            {
                "cache_dir": "data/cache",
                "reports_dir": "reports",
                "providers": {
                    "prices": "yfinance",
                    "constituents": "sp500_community",
                    "fundamentals": "edgar",
                },
                "not_a_real_key": True,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="not_a_real_key"):
        load_platform_config(bad_path)


def test_load_platform_config_bogus_nested_key_raises_config_error(tmp_path: Path) -> None:
    bad_path = tmp_path / "bad_platform.yaml"
    bad_path.write_text(
        yaml.safe_dump(
            {
                "cache_dir": "data/cache",
                "reports_dir": "reports",
                "providers": {
                    "prices": "yfinance",
                    "constituents": "sp500_community",
                    "fundamentals": "edgar",
                    "extra_provider": "nope",
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="extra_provider"):
        load_platform_config(bad_path)


def test_load_platform_config_missing_file_raises_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_platform_config(tmp_path / "does_not_exist.yaml")
