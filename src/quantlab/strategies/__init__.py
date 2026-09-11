"""The strategy plugin framework: `Strategy` ABC, the `@register_strategy`/
`load_strategy` registry, and the ported momentum/value/blend plugins.

Importing this package eagerly imports every plugin module below so their
`@register_strategy` decorators run and `load_strategy` can find them by
name without the caller having to know which module defines which
strategy.
"""

from __future__ import annotations

from quantlab.data.requirements import DataRequirements
from quantlab.strategies import blend as _blend  # noqa: F401  (registration side effect)
from quantlab.strategies import momentum as _momentum  # noqa: F401  (registration side effect)
from quantlab.strategies import value as _value  # noqa: F401  (registration side effect)
from quantlab.strategies.base import Strategy
from quantlab.strategies.registry import known_strategy_names, load_strategy, register_strategy

__all__ = [
    "DataRequirements",
    "Strategy",
    "known_strategy_names",
    "load_strategy",
    "register_strategy",
]
