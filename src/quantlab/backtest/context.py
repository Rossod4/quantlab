"""The ONE shared way any code path in this platform builds a decision-path
`PITDataContext` (data/pit.py) for a strategy.

Before this module, `backtest/engine.py`'s `run_backtest` built its decision
context inline (wrapping `constituents_provider` in
`_FilteringConstituentsProvider` whenever a strategy declares
`needs_universe` alongside price/fundamentals needs, dropping and counting
any ticker whose corporate-actions probe fails, aborting the whole run past
`max_dropped_fraction`), while `paper/runner.py` built its OWN context with
none of that - a strategy's paper-trading targets could therefore diverge
from what the SAME strategy would have done in a backtest on the exact same
degraded data (quant-gate VERDICT.md M08 cycle-1 finding 2). This module is
the fix: `build_decision_context` is now the ONLY place either caller
constructs a decision-path context, so a future change to the filtering
policy can never again silently apply to one caller and not the other.

`_FilteringConstituentsProvider` is moved here VERBATIM from
`backtest/engine.py` (see that module's own history) - it now raises
`core.errors.BacktestAbortError` (moved to `core/errors.py` for exactly this
reason: this module must not import `backtest.engine`, and `backtest.engine`
imports THIS module, so the error type needs a home neither depends on the
other for)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pandas as pd

from quantlab.core.errors import ActionsFetchError, BacktestAbortError, StaleActionsCacheError
from quantlab.core.types import normalize_timestamp
from quantlab.data.interfaces import (
    ConstituentsProvider,
    CorporateActionsProvider,
    FundamentalsProvider,
    PriceProvider,
)
from quantlab.data.pit import PITDataContext
from quantlab.data.requirements import DataRequirements

if TYPE_CHECKING:
    from quantlab.backtest.panel_store import PricePanelStore

__all__ = ["DecisionProviders", "actions_fetched_at", "build_decision_context"]

# "Everything up to asof" stand-in, mirroring data/pit.py's own `_EPOCH`.
_EPOCH = pd.Timestamp("1900-01-01")


def actions_fetched_at(cache_dir: object, tickers: set[str]) -> dict[str, str | None]:
    """Read the `fetched_at` sidecar (data/corporate_actions.py's staleness
    metadata) for each ticker directly - a documented, read-only duplication
    of that module's private path convention
    (`<cache_dir>/actions/<ticker>.meta.json`), not a second caching
    implementation. Moved here from `backtest/engine.py` (quant-gate
    VERDICT.2.md M08 cycle-2 finding 1) so `paper/runner.py`'s PROACTIVE
    refresh check can read the same sidecar `engine.py`'s own provenance
    section already did, without either module reaching into the other's
    private namespace."""
    from pathlib import Path

    from quantlab.data.cache import read_json_meta

    result: dict[str, str | None] = {}
    for ticker in tickers:
        meta = read_json_meta(Path(cache_dir) / "actions" / f"{ticker}.meta.json")
        result[ticker] = meta.get("fetched_at") if meta else None
    return result


class _FilteringConstituentsProvider(ConstituentsProvider):
    """Wraps a real `ConstituentsProvider`; `membership()` drops any ticker
    whose corporate-actions fetch fails, recording each drop via `on_drop`
    and aborting the whole run if drops exceed `max_dropped_fraction`. See
    module docstring - moved verbatim from `backtest/engine.py`."""

    def __init__(
        self,
        inner: ConstituentsProvider,
        corporate_actions_provider: CorporateActionsProvider,
        max_dropped_fraction: float,
        on_drop,
    ):
        self._inner = inner
        self._actions = corporate_actions_provider
        self._max_dropped_fraction = max_dropped_fraction
        self._on_drop = on_drop

    def membership(self, asof: object) -> list[str]:
        asof_ts = normalize_timestamp(asof)
        raw = self._inner.membership(asof_ts)
        good: list[str] = []
        dropped: list[str] = []
        for ticker in raw:
            try:
                self._actions.get_actions(ticker, _EPOCH, asof_ts)
            except (StaleActionsCacheError, ActionsFetchError) as exc:
                dropped.append(ticker)
                self._on_drop(ticker, exc)
                continue
            good.append(ticker)

        if raw and len(dropped) / len(raw) > self._max_dropped_fraction:
            raise BacktestAbortError(
                f"{len(dropped)}/{len(raw)} tickers "
                f"({100 * len(dropped) / len(raw):.1f}%) failed a data-availability probe "
                f"at asof={asof_ts.date()}, exceeding max_dropped_fraction="
                f"{self._max_dropped_fraction:.0%}: {sorted(dropped)[:10]}"
            )
        return good

    def membership_history(self, start: object, end: object) -> pd.DataFrame:
        return self._inner.membership_history(start, end)


@dataclass(frozen=True)
class DecisionProviders:
    """The four raw providers `build_decision_context` needs - the same
    shape as `backtest.engine.BacktestProviders`, duplicated here
    (structurally, not by import) so this module has no dependency on
    `backtest.engine` (which depends on THIS module, not the reverse)."""

    price: PriceProvider
    constituents: ConstituentsProvider
    fundamentals: FundamentalsProvider
    corporate_actions: CorporateActionsProvider


def build_decision_context(
    *,
    asof: object,
    requirements: DataRequirements,
    providers: DecisionProviders,
    max_dropped_fraction: float,
    on_drop: Callable[[str, Exception], None],
    panel_store: PricePanelStore | None = None,
    actions_store: dict[str, pd.DataFrame] | None = None,
) -> PITDataContext:
    """Build ONE decision-path `PITDataContext` - see module docstring.
    `accounting` is never passed (always the decision-path default `False` -
    data/pit.py). Wraps `providers.constituents` in
    `_FilteringConstituentsProvider` under the EXACT condition
    `backtest/engine.py` always has: `requirements.needs_universe and
    (requirements.price_lookback_days > 0 or requirements.fundamental_fields)`.
    `on_drop(ticker, exc)` is called for every ticker the probe drops - the
    caller decides what to do with that (the engine accumulates it into
    `quality_flags.dropped_tickers_by_date`; the paper runner accumulates it
    into the journal). Raises `BacktestAbortError` if the dropped fraction
    exceeds `max_dropped_fraction`."""
    constituents: ConstituentsProvider = providers.constituents
    if requirements.needs_universe and (
        requirements.price_lookback_days > 0 or requirements.fundamental_fields
    ):
        constituents = _FilteringConstituentsProvider(
            inner=providers.constituents,
            corporate_actions_provider=providers.corporate_actions,
            max_dropped_fraction=max_dropped_fraction,
            on_drop=on_drop,
        )
    return PITDataContext(
        asof=asof,
        requirements=requirements,
        price_provider=providers.price,
        constituents_provider=constituents,
        fundamentals_provider=providers.fundamentals,
        corporate_actions_provider=providers.corporate_actions,
        panel_store=panel_store,
        actions_store=actions_store,
    )
