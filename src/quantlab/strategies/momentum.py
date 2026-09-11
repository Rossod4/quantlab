"""12-1 month momentum: ported, frozen signal math plus the `Strategy` glue.

`compute_momentum_signal`, `select_top_n`, and `select_bottom_n` below are a
VERBATIM port of
...\\MomentumValueStrategy\\src\\strategy\\momentum.py (renamed nothing,
reworded nothing but comments/imports) - see tests/parity/test_signal_parity.py
for the 1e-10 golden-number pin. Do not "improve" this arithmetic; see
CLAUDE.md invariant #4 and .claude/agents/developer.md.

Classic academic momentum specification (Jegadeesh & Titman-style): rank
stocks by their return from `lookback_months` ago to `skip_months` ago,
deliberately skipping the most recent month (short-term reversal would
otherwise contaminate the signal).

## Adapting the ported, month-end-indexed math to `PITDataContext`

The old repo fed `compute_momentum_signal` a WIDE month-end price panel
built directly from a monthly data pull. `PITDataContext.prices()` instead
returns a LONG DAILY panel. `_month_end_prices` (new in this milestone, not
ported) bridges the two: it groups the daily as-of-adjusted `close` column
by (ticker, calendar year, calendar month) and keeps each group's last
available row as that month's price - the standard construction of a
month-end bar from daily bars. `MomentumStrategy.generate_targets` treats
the LAST such group (whichever calendar month `date` falls in, complete or
not) as the formation month; a caller invoking this strategy exactly on
real month-end dates (e.g. `core.calendar.rebalance_dates(freq="month_end")`,
the walk-forward engine's job in M04) gets the textbook formation point.
This bridging is new adapter code, not part of the frozen signal math, and
is exercised directly by tests/test_momentum_strategy.py rather than the
parity tests.

Per the Strategy ABC docstring (strategies/base.py): this module reads
`ctx.prices()["close"]` for the momentum score - never `raw_close` - and
never `volume`. See tests/canaries/test_momentum_canary.py for the standing
adversarial check (mutation-tested: switching this module to `raw_close`
must fail that canary).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

from quantlab.core.types import TargetWeights, normalize_timestamp
from quantlab.data.requirements import DataRequirements
from quantlab.strategies.base import Strategy
from quantlab.strategies.registry import register_strategy

if TYPE_CHECKING:
    from quantlab.data.pit import PITDataContext

# -- ported, frozen signal math (do not modify - see module docstring) ------


def compute_momentum_signal(
    month_end_prices: pd.DataFrame,
    formation_date: pd.Timestamp,
    lookback_months: int = 12,
    skip_months: int = 1,
) -> pd.Series:
    """Compute the 12-1 momentum score for every ticker at `formation_date`.

    `month_end_prices` is a wide DataFrame (index=month-end dates,
    columns=tickers) of prices. `formation_date` must be one of its index
    values.

    momentum = Price[formation_date - skip_months] / Price[formation_date - lookback_months] - 1

    Only tickers with a valid (non-NaN) price at BOTH the lookback date and
    the skip date get a score - a ticker missing either point (e.g. it
    didn't exist yet, or has a data gap) is excluded rather than silently
    given a misleading score.

    Returns a Series indexed by ticker, containing only tickers with a
    valid score.
    """
    dates = month_end_prices.index
    formation_idx = dates.get_loc(formation_date)

    skip_idx = formation_idx - skip_months
    lookback_idx = formation_idx - lookback_months

    if skip_idx < 0 or lookback_idx < 0:
        raise ValueError(
            f"Not enough price history before {formation_date.date()} to "
            f"compute a {lookback_months}-{skip_months} momentum signal "
            f"(need {lookback_months} months of prior month-end data)."
        )

    skip_prices = month_end_prices.iloc[skip_idx]
    lookback_prices = month_end_prices.iloc[lookback_idx]

    valid = skip_prices.notna() & lookback_prices.notna() & (lookback_prices != 0)
    momentum = (skip_prices[valid] / lookback_prices[valid]) - 1
    return momentum.dropna()


def select_top_n(scores: pd.Series, n: int) -> list[str]:
    """Rank momentum scores descending and return the top `n` tickers.

    If fewer than `n` tickers have valid scores, returns all of them
    (rather than erroring), since the eligible universe can occasionally
    be a little thin, especially in the earliest years of the backtest.
    """
    return scores.sort_values(ascending=False).head(n).index.tolist()


def select_bottom_n(scores: pd.Series, n: int) -> list[str]:
    """Rank momentum scores ascending and return the bottom `n` tickers -
    the LOWEST-momentum names, i.e. the short book of the long-short
    strategy.

    Exact mirror of select_top_n, including the same lenient behavior when
    fewer than `n` tickers have valid scores. Note that if the scored
    universe ever held fewer than (top-n + bottom-n) names, the two
    selections could overlap - `MomentumStrategy.generate_targets` below
    checks for that and fails loudly rather than silently holding a stock
    long and short at the same time (mirroring the old repo's
    long_short_engine.py check, ported as a guard here since that engine
    itself is M04/out of scope for this milestone).
    """
    return scores.sort_values(ascending=True).head(n).index.tolist()


# -- Strategy glue (new in this milestone) -----------------------------------

# Total book weights per `book` variant. long_only is fully invested long;
# long_short is dollar-neutral (net 0, gross 2.0); "130_30" is the classic
# 130% long / 30% short active-extension book (net 1.0, gross 1.6). These
# are fixed by the book choice, not independently configurable - a
# strategy_id changes when `book` changes, which is what acceptance
# criterion 7 exercises.
_BOOK_WEIGHTS: dict[str, tuple[float, float]] = {
    "long_only": (1.0, 0.0),
    "long_short": (1.0, -1.0),
    "130_30": (1.3, -0.3),
}

_Book = Literal["long_only", "long_short", "130_30"]


class MomentumParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    book: _Book = "long_only"
    n_long: int = Field(default=30, gt=0)
    n_short: int = Field(default=30, ge=0)
    lookback_months: int = Field(default=12, gt=0)
    skip_months: int = Field(default=1, ge=0)

    @model_validator(mode="after")
    def _check_short_leg(self) -> MomentumParams:
        if self.book != "long_only" and self.n_short <= 0:
            raise ValueError(f"book={self.book!r} requires n_short > 0")
        return self


def _month_end_prices(daily_panel: pd.DataFrame) -> pd.DataFrame:
    """Wide (date x ticker) panel of each ticker's last available `close` in
    every calendar month present in `daily_panel` (a long panel as returned
    by `ctx.prices()`). See module docstring - this is new adapter code, not
    part of the frozen signal math.

    M04 engine fix (carried from the M03 verdict - plans/QUANT-NOTES.md
    "From M03 verdict": pivoting on calendar months PRESENT in the panel
    means a month with zero rows for every ticker (e.g. a data-source gap)
    silently vanishes from the index instead of producing an all-NaN row,
    so a 12-months-back lookup at `compute_momentum_signal` quietly reaches
    13 calendar months back for every name at once). The month index is
    reindexed to the FULL contiguous range between its first and last
    calendar month before returning, so a missing month reappears as an
    all-NaN row - `compute_momentum_signal` already treats a NaN price as
    "no valid score for that ticker" (its own `.notna()` guard), so this
    restores the old repo's `resample("ME").last()` semantics without
    touching the frozen signal math itself.
    """
    monthly = daily_panel.reset_index().rename(columns={"index": "date"})
    monthly["month"] = pd.PeriodIndex(monthly["date"], freq="M")
    wide = monthly.sort_values("date").pivot_table(
        index="month", columns="ticker", values="close", aggfunc="last"
    )
    if not wide.empty:
        full_months = pd.period_range(wide.index.min(), wide.index.max(), freq="M")
        wide = wide.reindex(full_months)
    wide.index = wide.index.to_timestamp(how="end").normalize()
    return wide.sort_index()


@register_strategy("momentum")
class MomentumStrategy(Strategy):
    """12-1 momentum, long-only / long-short / 130-30 - see module
    docstring. Equal weight within each book (as the old repo)."""

    @classmethod
    def params_model(cls) -> type[BaseModel]:
        return MomentumParams

    def requires(self) -> DataRequirements:
        p: MomentumParams = self._params
        months_needed = p.lookback_months + p.skip_months
        # Generous trading-day budget per calendar month (holidays/weekends
        # never remove more than a handful of sessions) plus a few spare
        # months so a short gap in the fixture/universe never starves
        # `_month_end_prices` of a real calendar month.
        lookback_days = 23 * (months_needed + 3)
        return DataRequirements(price_lookback_days=lookback_days, needs_universe=True)

    def generate_targets(self, ctx: PITDataContext, date: pd.Timestamp) -> TargetWeights:
        p: MomentumParams = self._params
        date = normalize_timestamp(date)
        tickers = ctx.universe()
        panel = ctx.prices(tickers, self.requires().price_lookback_days)

        month_end = _month_end_prices(panel)
        formation_date = month_end.index[-1]
        scores = compute_momentum_signal(
            month_end, formation_date, lookback_months=p.lookback_months, skip_months=p.skip_months
        )

        long_total, short_total = _BOOK_WEIGHTS[p.book]
        longs = select_top_n(scores, p.n_long)
        shorts = select_bottom_n(scores, p.n_short) if short_total != 0.0 else []

        overlap = set(longs) & set(shorts)
        if overlap:
            raise ValueError(
                f"momentum long and short selections overlap ({sorted(overlap)}) - the scored "
                f"universe ({len(scores)} names) is too thin for n_long={p.n_long} and "
                f"n_short={p.n_short} to stay disjoint"
            )

        weights: dict[str, float] = {}
        if longs:
            per_long = long_total / len(longs)
            for ticker in longs:
                weights[ticker] = per_long
        if shorts:
            per_short = short_total / len(shorts)
            for ticker in shorts:
                weights[ticker] = per_short

        return TargetWeights(asof=date, weights=weights, strategy_id=self.strategy_id)
