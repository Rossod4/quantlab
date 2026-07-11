"""`DataRequirements`: a strategy's declared data footprint.

`PITDataContext` (data/pit.py) is the ONLY object a strategy ever sees, and
it gates every accessor against a `DataRequirements` instance supplied at
construction: asking for more than was declared here raises
`UndeclaredDataError` rather than silently handing over extra data. This
keeps the declaration honest - a strategy can't quietly expand its data
footprint at runtime without the platform knowing about it up front.

Deliberately a tiny, dependency-free dataclass (no imports from
data/providers/* or data/pit.py) so M03's Strategy ABC can import and
re-export it without pulling in the whole data layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DataRequirements:
    """What a strategy declares it needs, up front.

    `price_lookback_days`: the maximum number of trading sessions of price
        history `PITDataContext.prices()` / `.prices_for_returns()` may be
        asked for; a call requesting more raises `UndeclaredDataError`.
    `fundamental_fields`: the `PointInTimeFundamentals` field names (see
        data/providers/edgar_fundamentals.py) the strategy needs.
        `fundamentals()` returns only this subset; an empty set means the
        strategy never declared a fundamentals need, so any call to
        `fundamentals()` raises `UndeclaredDataError`.
    `needs_universe`: whether `universe()` may be called at all.
    `needs_actions`: whether `actions()` may be called at all. Added on M02
        review advice (beyond the packet's original three-field spec) so
        every `PITDataContext` accessor is declaration-gated before M03's
        Strategy ABC freezes this surface - without it, `actions()` would
        be the only accessor callable with a fully-empty declaration.
    """

    price_lookback_days: int = 0
    fundamental_fields: frozenset[str] = field(default_factory=frozenset)
    needs_universe: bool = False
    needs_actions: bool = False
