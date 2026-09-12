from __future__ import annotations

import math
from enum import StrEnum

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator


def normalize_timestamp(value: object) -> pd.Timestamp:
    """Coerce to a timezone-naive pandas Timestamp normalized to midnight.

    Shared by the core type validators and `core.calendar`; all QuantLab dates
    are tz-naive and midnight-aligned (see CLAUDE.md conventions).
    """
    ts = pd.Timestamp(value)
    if ts.tzinfo is not None:
        ts = ts.tz_localize(None)
    return ts.normalize()


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class DelistingReason(StrEnum):
    ACQUISITION = "ACQUISITION"
    BANKRUPTCY = "BANKRUPTCY"
    UNKNOWN = "UNKNOWN"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)


class Bar(_FrozenModel):
    date: pd.Timestamp
    open: float
    high: float
    low: float
    close: float
    adj_close: float
    volume: int

    @field_validator("date", mode="before")
    @classmethod
    def _v_date(cls, v: object) -> pd.Timestamp:
        return normalize_timestamp(v)


class TargetWeights(_FrozenModel):
    asof: pd.Timestamp
    weights: dict[str, float]
    strategy_id: str
    # M04b quant-gate VERDICT.md cycle 1 finding 3 (blocking, additive):
    # ticker -> a short human reason the strategy ITSELF tried to score this
    # name and could not (e.g. "missing lookback price"). Before this,
    # `backtest/engine.py`'s `quality_flags.unscored_by_date` inferred
    # "unscored" as `ctx.universe() - weights.keys()`, which conflates a
    # genuinely unscoreable name with one the strategy simply didn't select
    # into a top-N book - on a real ~500-name universe with a 30-name book,
    # that made the flag ~473 names wide at every rebalance, useless as a
    # data-quality signal. Empty by default so every pre-existing
    # strategy/test that never populates it is unaffected.
    unscored: dict[str, str] = Field(default_factory=dict)

    @field_validator("asof", mode="before")
    @classmethod
    def _v_asof(cls, v: object) -> pd.Timestamp:
        return normalize_timestamp(v)

    @field_validator("weights")
    @classmethod
    def _v_weights_finite(cls, v: dict[str, float]) -> dict[str, float]:
        for ticker, weight in v.items():
            if not math.isfinite(weight):
                raise ValueError(f"weight for {ticker!r} is not finite: {weight}")
        return v


class Order(_FrozenModel):
    client_order_id: str
    ticker: str
    side: Side
    qty: float
    order_type: OrderType

    @field_validator("qty")
    @classmethod
    def _v_qty_positive(cls, v: float) -> float:
        if not math.isfinite(v) or v <= 0:
            raise ValueError(f"qty must be a positive finite number, got {v}")
        return v


class Fill(_FrozenModel):
    client_order_id: str
    ticker: str
    qty: float
    price: float
    date: pd.Timestamp
    commission: float

    @field_validator("date", mode="before")
    @classmethod
    def _v_date(cls, v: object) -> pd.Timestamp:
        return normalize_timestamp(v)

    @field_validator("qty")
    @classmethod
    def _v_qty_positive(cls, v: float) -> float:
        if not math.isfinite(v) or v <= 0:
            raise ValueError(f"qty must be a positive finite number, got {v}")
        return v

    @field_validator("commission")
    @classmethod
    def _v_commission_nonneg(cls, v: float) -> float:
        if not math.isfinite(v) or v < 0:
            raise ValueError(f"commission must be a non-negative finite number, got {v}")
        return v


class Position(_FrozenModel):
    ticker: str
    qty: float
    avg_cost: float


class PortfolioSnapshot(_FrozenModel):
    date: pd.Timestamp
    cash: float
    positions: dict[str, Position]
    equity: float

    @field_validator("date", mode="before")
    @classmethod
    def _v_date(cls, v: object) -> pd.Timestamp:
        return normalize_timestamp(v)


class DelistingEvent(_FrozenModel):
    ticker: str
    last_trade_date: pd.Timestamp
    reason: DelistingReason

    @field_validator("last_trade_date", mode="before")
    @classmethod
    def _v_last_trade_date(cls, v: object) -> pd.Timestamp:
        return normalize_timestamp(v)
