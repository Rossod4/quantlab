"""Strategy registration and YAML/dict instantiation.

`@register_strategy("name")` records a `Strategy` subclass under a string
name; `load_strategy` looks a name up and constructs an instance from a
config's `params` mapping. The registry is a plain module-level dict, not a
class - registration is a side effect of importing the plugin module that
owns the decorator, which `quantlab.strategies.__init__` does eagerly (see
its module docstring) so `load_strategy` never has to guess which modules
to import.
"""

from __future__ import annotations

from pathlib import Path
from typing import TypeVar

import yaml

from quantlab.core.errors import UnknownStrategyError
from quantlab.strategies.base import Strategy

_REGISTRY: dict[str, type[Strategy]] = {}

_StrategyT = TypeVar("_StrategyT", bound=type[Strategy])


def register_strategy(name: str):
    """Class decorator: record `name` -> the decorated `Strategy` subclass
    and stamp `cls.name = name` (so `Strategy.strategy_id` always has the
    registered name available, even if a subclass forgot to set it)."""

    def decorator(cls: _StrategyT) -> _StrategyT:
        cls.name = name
        _REGISTRY[name] = cls
        return cls

    return decorator


def known_strategy_names() -> list[str]:
    return sorted(_REGISTRY)


def load_strategy(config: str | Path | dict) -> Strategy:
    """Instantiate a strategy from a YAML file path or an already-loaded
    dict of the same shape:

        strategy: <registered name>
        params: {...}                # optional; defaults to {}

    Raises `UnknownStrategyError` (listing every registered name) if
    `strategy` names nothing in the registry.
    """
    if isinstance(config, dict):
        data = config
    else:
        path = Path(config)
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    strategy_name = data["strategy"]
    params = data.get("params", {})

    cls = _REGISTRY.get(strategy_name)
    if cls is None:
        raise UnknownStrategyError(
            f"unknown strategy {strategy_name!r}; known strategies: {known_strategy_names()}"
        )
    return cls(params)
