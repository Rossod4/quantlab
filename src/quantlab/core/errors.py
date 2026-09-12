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


class BacktestAbortError(QuantLabError):
    """Raised to abort an ENTIRE run outright - never caught or retried by
    the caller's rebalance/decision loop. Lives here (not in
    `backtest/engine.py`, where it originated) so `backtest/context.py`'s
    shared decision-context builder - used by both `backtest.engine.
    run_backtest` and `paper.runner.run_once` - can raise it without either
    module importing the other (quant-gate VERDICT.md M08 cycle-1 finding
    2). `backtest/engine.py` re-exports this name for backward
    compatibility with existing `from quantlab.backtest.engine import
    BacktestAbortError` call sites."""


class BrokerError(QuantLabError):
    """Raised for a paper/live broker adapter-level failure (network, auth,
    an unexpected account state) - see paper/broker.py's `Broker` ABC."""


class NotPaperAccountError(BrokerError):
    """Raised by a broker adapter's constructor when the resolved trading
    endpoint is not a paper-trading endpoint. `paper/alpaca.py`'s
    `AlpacaPaperBroker` raises this unconditionally rather than ever
    constructing a client pointed at a live endpoint - there is no code
    path in this platform to live money."""


class ReconcileError(QuantLabError):
    """Raised by `paper/reconcile.py`'s `reconcile()` when a broker
    account's actual cash/positions disagree with what the platform's own
    journal expected, beyond the supplied tolerances. The paper runner
    refuses to trade for the day when this is raised - a human must resolve
    the discrepancy before the next scheduled run.

    `report` (default `None`) carries the full `paper.reconcile.
    ReconcileReport` that triggered this error, so a caller (the runner) can
    record complete mismatch detail in the journal without recomputing it.
    Typed as `object` here (not `ReconcileReport`) deliberately: importing
    the `paper` package from `core/errors.py` would invert this platform's
    layering (core has no dependency on paper), mirroring the same
    core-errors-stay-dependency-free convention `StaleActionsCacheError`
    etc. already follow."""

    def __init__(self, message: str, report: object = None) -> None:
        super().__init__(message)
        self.report = report


class PromotionGateError(QuantLabError):
    """Raised by `paper/runner.py`'s `run_once()` when no `report_card.json`
    with verdict `ELIGIBLE_FOR_PAPER`, matching both this strategy's
    `strategy_id` and the platform's current `DATA_SEMANTICS_VERSION`, can
    be found under `PlatformConfig.reports_dir`. This is the promotion gate
    the work packet requires: paper trading a strategy that was never
    validated (or was validated against a data-semantics version this
    platform no longer represents) is refused, not merely warned about.
    `--force-research` (CLI) / `force_research=True` (`run_once`) bypasses
    this specific check - never any other safety gate - and leaves a loud,
    unmissable flag in the journal precisely because it was bypassed."""
