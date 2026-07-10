"""Provider-agnostic data interfaces.

Providers are dumb and cacheable: they fetch/read data for a requested
window and hand back a plain `pandas` object. They are NEVER handed to
strategies directly — `data/pit.py` (M02) wraps them in a `PITDataContext`
hard-bound to an `asof` date before any strategy code sees a row.

`build_provider` is the only place that maps a `PlatformConfig` provider
name (e.g. `"yfinance"`, `"norgate"`, `"sp500_community"`) to a concrete
class, so swapping vendors is a one-line config change.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

import pandas as pd

from quantlab.core.errors import ConfigError

if TYPE_CHECKING:
    from quantlab.core.config import PlatformConfig


class PriceProvider(ABC):
    """Provides historical daily OHLCV price panels for a list of tickers.

    `get_prices` returns a LONG-format panel: a `pandas.DataFrame` indexed
    by tz-naive, midnight-normalized `pd.Timestamp` trading dates (one row
    per (date, ticker) pair — the index itself carries only the date, the
    ticker is a column), with columns:

        ["ticker", "open", "high", "low", "close", "adj_close", "volume"]

    Both the raw `close` and the dividend/split-adjusted `adj_close` are
    included so downstream code (returns math vs. corporate-action-aware
    analysis) can pick the one it needs. Tickers with no usable data over
    the window are simply absent from the result — no NaN-filled rows or
    columns — so callers don't need to special-case failures.
    """

    @abstractmethod
    def get_prices(self, tickers: list[str], start: object, end: object) -> pd.DataFrame:
        """Return the long-format OHLCV panel for `tickers` over [start, end]."""


class ConstituentsProvider(ABC):
    """Provides point-in-time index membership (e.g. S&P 500)."""

    @abstractmethod
    def membership(self, asof: object) -> list[str]:
        """Tickers that were index constituents as of `asof`.

        Must be a strict as-of lookup: only membership changes recorded on
        or before `asof` may influence the result (no look-ahead).
        """

    @abstractmethod
    def membership_history(self, start: object, end: object) -> pd.DataFrame:
        """Membership change events recorded within [start, end].

        Returns a `pandas.DataFrame` indexed by the change-event date, with
        a `tickers` column (list[str]) holding the full membership as of
        that change.
        """


class FundamentalsProvider(ABC):
    """Point-in-time company fundamentals. Signature only in M01; the
    filed-date-gated implementation lands in M02 (`data/fundamentals.py`)."""

    @abstractmethod
    def get_pit_fundamentals(self, ticker: str, asof: object) -> dict[str, Any]:
        """Return the fundamentals known for `ticker` as of `asof`.

        Must gate on the SEC `filed` date, not the fiscal period end, so no
        figure is visible before it was actually public knowledge.
        """


class CorporateActionsProvider(ABC):
    """Splits/dividends/delistings. Signature only in M01; implemented in
    M02 (`data/corporate_actions.py`)."""

    @abstractmethod
    def get_actions(self, ticker: str, start: object, end: object) -> pd.DataFrame:
        """Return corporate actions for `ticker` within [start, end]."""


def build_provider(kind: str, name: str, config: PlatformConfig) -> object:
    """Instantiate a provider by `kind` ("prices" | "constituents") and
    vendor `name` (as recorded in `PlatformConfig.providers`).

    Provider classes are imported lazily inside each branch, since they in
    turn import the ABCs above — importing them eagerly at module scope
    would be circular.

    Raises `ConfigError` naming the offending value for an unknown `kind`
    or an unknown `name` within a known `kind`.
    """
    if kind == "prices":
        if name == "yfinance":
            from quantlab.data.providers.yfinance_prices import YFinancePriceProvider

            return YFinancePriceProvider(cache_dir=config.cache_dir)
        if name == "norgate":
            from quantlab.data.providers.norgate_prices import NorgatePriceProvider

            return NorgatePriceProvider()
        raise ConfigError(f"unknown prices provider: {name!r}")

    if kind == "constituents":
        if name == "sp500_community":
            from quantlab.data.providers.sp500_constituents import (
                SP500CommunityConstituentsProvider,
            )

            return SP500CommunityConstituentsProvider(cache_dir=config.cache_dir)
        raise ConfigError(f"unknown constituents provider: {name!r}")

    raise ConfigError(f"unknown provider kind: {kind!r}")
