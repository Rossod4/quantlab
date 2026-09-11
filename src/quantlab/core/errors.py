from __future__ import annotations


class QuantLabError(Exception):
    """Base class for all QuantLab errors."""


class LookaheadError(QuantLabError):
    """Raised when a code path would let a strategy read data timestamped
    after its asof date."""


class UndeclaredDataError(QuantLabError):
    """Raised when a strategy accesses data it never declared needing via
    its `DataRequirements` (an undeclared fundamental field, more price
    lookback than declared, or a universe() call with membership not
    requested)."""


class DataQualityError(QuantLabError):
    """Raised when input data fails a quality/integrity check."""


class StaleActionsCacheError(DataQualityError):
    """Raised when a corporate-actions cache is asked for events through an
    `asof`/`end` date later than (or when there is no known) fetch date for
    that ticker's cache. The actions cache is fetch-once-forever (see
    data/corporate_actions.py): a cache fetched at date T is blind to any
    split/dividend announced after T, which would silently reintroduce the
    raw-discontinuity bug the M02b as-of adjustment replay exists to close.
    A missing fetch date (a cache file written before this check existed)
    is treated the same as a known-stale one - never silently trusted.
    Call `refresh_actions_cache()` to clear this."""


class ActionsFetchError(DataQualityError):
    """Raised when fetching a ticker's corporate actions fails (network or
    vendor error) and there is no usable cache to fall back on. Before
    M02b an empty actions result was benign metadata; after M02b it means
    "no as-of adjustment", so a transient failure must never be silently
    swallowed into an empty frame - that would make `PITDataContext.prices()`
    return the raw, split-distorted series with no error at all. Nothing is
    written to the cache when this is raised, so the next call retries."""


class ConfigError(QuantLabError):
    """Raised when platform configuration is missing, malformed, or
    contains an unrecognized key."""


class UnknownStrategyError(QuantLabError):
    """Raised when a requested strategy id has no registered implementation."""
