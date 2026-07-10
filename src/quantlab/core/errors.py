from __future__ import annotations


class QuantLabError(Exception):
    """Base class for all QuantLab errors."""


class LookaheadError(QuantLabError):
    """Raised when a code path would let a strategy read data timestamped
    after its asof date."""


class DataQualityError(QuantLabError):
    """Raised when input data fails a quality/integrity check."""


class ConfigError(QuantLabError):
    """Raised when platform configuration is missing, malformed, or
    contains an unrecognized key."""


class UnknownStrategyError(QuantLabError):
    """Raised when a requested strategy id has no registered implementation."""
