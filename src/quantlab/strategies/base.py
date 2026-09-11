"""`Strategy`: the ABC every plugin in this package implements.

A strategy is a PURE function from a `PITDataContext` (data/pit.py) plus a
decision date to a `TargetWeights` instance. "Pure" here means specifically:

- No I/O. A strategy never touches a network, file, or provider directly -
  `PITDataContext` is the ONLY data-access surface it is ever handed
  (CLAUDE.md invariant #1), and it is never extended or reached around.
- No state mutation between calls. Calling `generate_targets` twice with
  the same `(ctx, date)` must return equal `TargetWeights` - no cached
  running state, no clock reads, no randomness without a fixed seed passed
  through `params`.
- `params` are frozen at construction (validated by a per-strategy pydantic
  model - see each plugin's `*Params` class) and never mutated afterward.

Price-signal discipline (binding, carried from the M02b verdict - see
plans/QUANT-NOTES.md "From M02b verdict" and plans/state/M02b/VERDICT.md):

1. Any signal that compares a price ACROSS TIME (a return, a momentum
   score, a moving average) MUST be computed on `ctx.prices()["close"]` -
   the as-of adjustment replay - and NEVER on `ctx.prices()["raw_close"]`,
   which still carries the full split/dividend discontinuity `close` exists
   to remove (the M02 verdict's -90%-momentum hazard). See
   tests/canaries/ for a standing adversarial check of this rule for the
   momentum plugin.
2. Any LEVEL metric evaluated at a single date - a P/E, a P/B, a market
   cap, a penny-price floor - must instead use the true traded price at
   that date: either `ctx.prices()`'s `raw_close` column, or the `close`
   column's most recent (asof) row, where the as-of adjustment factor is
   always exactly 1.0. A pre-split filing's per-share figure never
   reconciles with a split-adjusted historical price level; pairing raw
   price at t with the filing in force at t is the only consistent
   combination. See strategies/value.py.
3. `volume` in `ctx.prices()` is NEVER adjusted for splits (documented
   limitation of data/adjustment.py). No strategy may compute a
   dollar-volume or turnover screen spanning a gated ex-date from it.
4. `ctx.prices()` does not retain raw open/high/low (only `raw_close`) -
   a strategy needing the true traded intraday range (a stop level, a gap
   check) has no accessor for it. `ctx.prices_for_returns()` is the
   accounting path for equity-curve bookkeeping ONLY (see data/pit.py's
   module docstring); it is off-limits to strategy signal logic and no
   plugin in this package calls it. A strategy that finds it needs
   `prices_for_returns()`-only data must STOP and escalate rather than
   reach for it - see plans/state/M03/HANDOFF.md for a worked example.
5. `PITDataContext` is frozen as of M02/M02b and must not be casually
   extended by a strategy or by this package - if a strategy needs data
   the context cannot provide, that is an escalation (flagged in the
   milestone handoff), not a reason to add a method to `pit.py` from here.
   The sole exception is the orchestrator-authorised, restrict-only
   `filing_lag_sessions` parameter on `fundamentals()` (M03, see
   strategies/value.py's module docstring and plans/state/M03/HANDOFF.md) -
   an explicitly reviewed and narrowly-scoped addition, not a precedent for
   reaching around this rule unilaterally.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import BaseModel

from quantlab.data.requirements import DataRequirements

if TYPE_CHECKING:
    import pandas as pd

    from quantlab.core.types import TargetWeights
    from quantlab.data.pit import PITDataContext

__all__ = ["DataRequirements", "Strategy"]


class Strategy(ABC):
    """One registered strategy plugin, instantiated from validated params.

    Subclasses set the class attribute `name` (also set automatically by
    `@register_strategy` - see registry.py) and implement `params_model`,
    `requires`, and `generate_targets`.
    """

    name: ClassVar[str] = ""

    def __init__(self, params: dict[str, Any] | None = None):
        model = self.params_model().model_validate(params or {})
        self._params: BaseModel = model

    @classmethod
    @abstractmethod
    def params_model(cls) -> type[BaseModel]:
        """The pydantic model (frozen, `extra='forbid'`) that validates this
        strategy's `params` dict."""

    @property
    def params(self) -> dict[str, Any]:
        """The validated, frozen param set as a plain dict (JSON-serializable
        by `model_dump(mode="json")` on every subclass's params model - the
        param models in this package use only JSON-safe types)."""
        return self._params.model_dump(mode="json")

    @property
    def strategy_id(self) -> str:
        """`{name}-{10 hex char hash of the canonical param JSON}`. Stable
        across runs and processes: the same YAML always hashes to the same
        id (dict key order does not matter - `sort_keys=True`), and any
        param change - including one that doesn't affect a hand-typed YAML
        file's key order - changes the hash. The M06 multiple-testing trials
        registry keys on this id, so it must never depend on anything
        non-deterministic (wall clock, object identity, dict insertion
        order)."""
        canonical = json.dumps(self.params, sort_keys=True)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:10]
        return f"{self.name}-{digest}"

    @abstractmethod
    def requires(self) -> DataRequirements:
        """This strategy's declared data footprint - see
        data/requirements.py. Must be a pure function of `self.params`
        (constant for a given instance): the platform gates every
        `PITDataContext` accessor against whatever this returns, so it must
        not vary from call to call."""

    @abstractmethod
    def generate_targets(self, ctx: PITDataContext, date: pd.Timestamp) -> TargetWeights:
        """Compute this strategy's target portfolio weights as of `date`.

        Pure: no I/O, no provider access beyond `ctx`, no mutation of `ctx`,
        `self.params`, or any instance state between calls - see this
        module's docstring. `date` is the nominal decision date recorded on
        the returned `TargetWeights.asof`; a correct caller passes a `ctx`
        bound to `date` (a strategy needing a fundamentals filing lag
        applies it itself via `ctx.fundamentals(..., filing_lag_sessions=)`
        - see strategies/value.py's module docstring - rather than needing
        a `ctx` bound to an earlier date).
        """
