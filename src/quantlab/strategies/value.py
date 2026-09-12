"""Composite value signal: ported, frozen ratio/ranking math plus the
`Strategy` glue.

`_PointInTimeFundamentals`, `compute_value_ratios`, `_rank_lower_is_better`,
`compute_composite_score`, and `select_top_n` below are a port of
...\\MomentumValueStrategy\\src\\strategy\\value.py. The only change from the
original is the input TYPE for `compute_value_ratios` - a small local
dataclass (`_PointInTimeFundamentals`) built from `ctx.fundamentals()`'s
plain dict instead of the old repo's `PointInTimeFundamentals` class import
- the field names and every line of arithmetic are otherwise byte-identical.
See tests/parity/test_signal_parity.py for the 1e-10 golden-number pin
against the old repo's own function, called directly on the same fixture.

Design decisions carried from the old repo (do not "improve" - see
CLAUDE.md invariant #4):

  - Percentile ranks, not z-scores (robust to earnings-like-denominator
    outliers - a P/E of 500 isn't rare for an S&P 500 name in a weak
    quarter).
  - Loss-making companies are NOT filtered out; a non-positive ratio ranks
    as the LEAST attractive end of that metric (see _rank_lower_is_better),
    not sorted in with positive values.
  - The fourth factor ("growth-adjusted value") is realized trailing EPS
    growth, not a forward analyst estimate - explicitly not called PEG.

## Price levels (M02b VERDICT.md carried item 1, binding)

Every ratio here needs a per-share PRICE LEVEL (market cap = price x shares
outstanding), not a return. `ctx.prices()`'s `close` column is a total-return
LEVEL for any row before the last gated ex-date - correct for momentum's
cross-time ratio, wrong for a level metric, because a pre-split filing's
per-share figures were never reported in split-adjusted terms. This module
therefore prices every ticker off `ctx.prices()`'s `raw_close` column on the
single most-recent (asof) row - the true traded price at the same date the
fundamentals gate ("filed <= asof") is evaluated at, which is exactly the
"pair raw price at t with the filing in force at t" rule VERDICT.md
mandates. (`close`'s own asof row would give the identical number, since the
as-of adjustment factor is always 1.0 there - `raw_close` is used anyway, as
the more obviously-correct, self-documenting choice per the verdict.)

M03b (plans/M03b-share-terms.md) closed the residual hazard VERDICT.md
flagged in this pairing: `ctx.fundamentals()`'s `shares_outstanding` and
`ttm_eps` are now themselves delivered already restated into the share
terms in force at `asof` (see data/pit.py's module docstring and
`fundamentals()`), not the share terms in force when they were filed. So
`market_cap = raw_close(asof) * shares_outstanding` and
`pe = raw_close(asof) / ttm_eps` below are now a consistent pairing across
a split, not merely a consistent PRICE-LEVEL pairing - this module makes no
other numerical change and declares nothing new to get that.

## The one-session filing lag (M03 orchestrator-authorised extension)

plans/QUANT-NOTES.md's M02/M03 carried item DECIDES a one-session lag on
fundamentals availability: `filed <= prev_trading_day(asof)`, exposed as a
`filing_lag_sessions` param (default 1; the parity test pins 0 for old-repo
comparability). This was initially flagged as an escalation - the frozen
M02/M02b `PITDataContext.fundamentals()` had no way to gate on anything but
`filed <= ctx.asof`, and a strategy cannot rebind `ctx.asof` itself - and
the orchestrator authorised the one additive, restrict-only extension that
closes it: `PITDataContext.fundamentals(ticker, *, filing_lag_sessions=0)`
(data/pit.py), which steps the gate back N further NYSE sessions before
applying `filed <= effective_asof`. `filing_lag_sessions=0` is identical to
every pre-existing caller's gate for a session `asof`, and strictly
narrower (never wider) for a non-session `asof`; a negative value raises
`ValueError`. This parameter can only ever narrow what's visible, never
expand it, so it cannot introduce look-ahead. This module simply forwards
its own `filing_lag_sessions` param through to `ctx.fundamentals()`. See
plans/state/M03/HANDOFF.md for the restrict-only argument in full and
tests/canaries/test_lookahead.py canary (g) for the standing adversarial
check that any lag >= 0 only ever shrinks (never grows) the set of visible
filings.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from quantlab.core.types import TargetWeights, normalize_timestamp
from quantlab.data.requirements import DataRequirements
from quantlab.strategies.base import Strategy
from quantlab.strategies.registry import register_strategy

if TYPE_CHECKING:
    from quantlab.data.pit import PITDataContext

# -- ported, frozen signal math (do not modify - see module docstring) ------

MIN_AVAILABLE_METRICS = 2

VALUE_METRIC_COLUMNS = ["pb", "pe", "ev_ebitda", "growth_adjusted_value"]

# The full set of `ctx.fundamentals()` field names this strategy needs -
# exactly `data/providers/edgar_fundamentals.py`'s `PointInTimeFundamentals`
# field names (see data/requirements.py's docstring on that contract).
FUNDAMENTAL_FIELDS = frozenset(
    {
        "shares_outstanding",
        "stockholders_equity",
        "ttm_eps",
        "ttm_ebitda",
        "total_debt",
        "cash",
        "annual_eps_growth",
    }
)


@dataclass(frozen=True)
class _PointInTimeFundamentals:
    """Local stand-in for the old repo's `PointInTimeFundamentals` (same
    field names, same optionality) so `compute_value_ratios` below can stay
    a verbatim, attribute-access port. Built fresh from `ctx.fundamentals()`'s
    dict for each ticker - see `_fundamentals_from_ctx`."""

    shares_outstanding: float | None
    stockholders_equity: float | None
    ttm_eps: float | None
    ttm_ebitda: float | None
    total_debt: float
    cash: float | None
    annual_eps_growth: float | None


def compute_value_ratios(
    fundamentals_by_ticker: dict[str, _PointInTimeFundamentals],
    prices: dict[str, float],
) -> pd.DataFrame:
    """Raw (not yet ranked) value ratios for every ticker with both a price
    and usable fundamental data, as a DataFrame indexed by ticker with
    columns VALUE_METRIC_COLUMNS.

    Every ratio follows a "lower is more attractive" convention. A missing
    underlying input (e.g. no EBITDA data at all for a bank) produces NaN
    for that one ratio - that ticker is simply not scored on that metric,
    not penalized for it (see compute_composite_score). A non-positive
    ratio is a real computed number, not a missing one, and is handled by
    the ranking step's least-attractive rule instead.
    """
    rows = {}
    for ticker, f in fundamentals_by_ticker.items():
        price = prices.get(ticker)
        if price is None or not f.shares_outstanding:
            continue  # can't establish market cap at all - not scorable this period

        market_cap = price * f.shares_outstanding

        pb = market_cap / f.stockholders_equity if f.stockholders_equity else float("nan")
        pe = price / f.ttm_eps if f.ttm_eps else float("nan")

        if f.ttm_ebitda:
            enterprise_value = market_cap + f.total_debt - (f.cash or 0.0)
            ev_ebitda = enterprise_value / f.ttm_ebitda
        else:
            ev_ebitda = float("nan")

        # The growth-adjusted ratio needs BOTH a positive P/E and positive
        # trailing growth to mean anything as "cheap relative to growth" -
        # e.g. a P/E of -5 divided by growth of -2 gives +2.5, which LOOKS
        # like a plausible ratio but is economically meaningless (both
        # ingredients are actually bad news). Rather than let that kind of
        # sign-cancellation slip through as a false-positive result, both
        # legs are checked explicitly before dividing, and the ambiguous
        # case is marked least-attractive (+inf) directly - a company
        # that's either unprofitable or shrinking shouldn't score well on
        # "cheap relative to growth", regardless of how the raw division
        # happens to come out.
        if f.ttm_eps is None or f.annual_eps_growth is None:
            growth_adjusted_value = float("nan")
        elif pe > 0 and f.annual_eps_growth > 0:
            growth_adjusted_value = pe / f.annual_eps_growth
        else:
            growth_adjusted_value = float("inf")

        rows[ticker] = {
            "pb": pb,
            "pe": pe,
            "ev_ebitda": ev_ebitda,
            "growth_adjusted_value": growth_adjusted_value,
        }

    return pd.DataFrame.from_dict(rows, orient="index", columns=VALUE_METRIC_COLUMNS)


def _rank_lower_is_better(values: pd.Series) -> pd.Series:
    """Cross-sectional percentile rank for one metric, where a LOWER raw
    value is more attractive (cheaper) and a lower percentile is better.

    Non-positive values are shifted to +inf before ranking, which forces
    them to tie for the worst percentile as a group, entirely separate from
    (and always worse than) every positive value's ordering - implementing
    the "negative ratios are least attractive, not artificially cheap" rule
    from this module's docstring. NaN (genuinely missing data) is left as
    NaN, which pandas' rank() naturally excludes rather than penalizes.

    KNOWN LIMITATION: for EV/EBITDA specifically, a non-positive result can
    come from either negative EBITDA (distress - correctly penalized here)
    OR a negative enterprise value, i.e. a company holding more net cash
    than its market cap plus debt (a classic deep-value "net-net" signal -
    arguably one of the CHEAPEST possible situations, not a bad one). This
    rule can't distinguish the two cases and treats both as least
    attractive. This is a deliberate simplification, not an oversight.
    """
    sortable = values.where(~(values <= 0), other=np.inf)
    return sortable.rank(pct=True, ascending=True)


def compute_composite_score(raw_ratios: pd.DataFrame) -> pd.Series:
    """Combine the four value ratios into one composite score per ticker.

    Each column is percentile-ranked independently (see
    _rank_lower_is_better), then averaged across whichever ranks are
    available for that ticker. The result runs 0 (cheapest across
    available metrics) to 1 (most expensive) - lower is more attractive,
    matching every individual metric's convention.

    Tickers with fewer than MIN_AVAILABLE_METRICS available ratios get NaN
    (excluded from selection that period) rather than a score built from
    too little information - see MIN_AVAILABLE_METRICS above.
    """
    ranks = raw_ratios[VALUE_METRIC_COLUMNS].apply(_rank_lower_is_better)
    available_count = ranks.notna().sum(axis=1)
    composite = ranks.mean(axis=1, skipna=True)
    composite = composite.where(available_count >= MIN_AVAILABLE_METRICS)
    return composite


def select_top_n(composite_scores: pd.Series, n: int) -> list[str]:
    """Pick the `n` tickers with the lowest (cheapest) composite score.

    Tickers with no score (NaN - insufficient data, see
    compute_composite_score) are dropped before ranking. If fewer than `n`
    scored tickers are available, returns all of them rather than erroring,
    mirroring strategies/momentum.py's select_top_n for the same reason.
    """
    valid = composite_scores.dropna()
    return valid.sort_values(ascending=True).head(n).index.tolist()


# -- Strategy glue (new in this milestone) -----------------------------------


class ValueParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    n_holdings: int = Field(default=30, gt=0)
    # See module docstring's "one-session filing lag" section: forwarded to
    # `ctx.fundamentals(..., filing_lag_sessions=...)` (data/pit.py).
    filing_lag_sessions: int = Field(default=1, ge=0)


def _fundamentals_from_ctx(
    ctx: PITDataContext, ticker: str, filing_lag_sessions: int
) -> _PointInTimeFundamentals:
    raw: dict[str, Any] = ctx.fundamentals(ticker, filing_lag_sessions=filing_lag_sessions)
    return _PointInTimeFundamentals(
        shares_outstanding=raw.get("shares_outstanding"),
        stockholders_equity=raw.get("stockholders_equity"),
        ttm_eps=raw.get("ttm_eps"),
        ttm_ebitda=raw.get("ttm_ebitda"),
        total_debt=raw.get("total_debt") or 0.0,
        cash=raw.get("cash"),
        annual_eps_growth=raw.get("annual_eps_growth"),
    )


def _asof_raw_price(ctx: PITDataContext, ticker: str) -> float | None:
    """The true traded price at ctx.asof for one ticker, per the module
    docstring's price-level rule: `raw_close` on the single most-recent
    (asof) row of `ctx.prices()`. None if the ticker has no price row."""
    panel = ctx.prices([ticker], 1)
    if panel.empty:
        return None
    return float(panel["raw_close"].iloc[-1])


@register_strategy("value_composite")
class ValueStrategy(Strategy):
    """Composite value (P/B, P/E, EV/EBITDA, growth-adjusted), quarterly
    signal - see module docstring."""

    @classmethod
    def params_model(cls) -> type[BaseModel]:
        return ValueParams

    def requires(self) -> DataRequirements:
        return DataRequirements(
            price_lookback_days=1,
            fundamental_fields=FUNDAMENTAL_FIELDS,
            needs_universe=True,
        )

    def generate_targets(self, ctx: PITDataContext, date: pd.Timestamp) -> TargetWeights:
        p: ValueParams = self._params
        date = normalize_timestamp(date)
        tickers = ctx.universe()

        fundamentals_by_ticker = {
            t: _fundamentals_from_ctx(ctx, t, p.filing_lag_sessions) for t in tickers
        }
        prices = {}
        for ticker in tickers:
            price = _asof_raw_price(ctx, ticker)
            if price is not None:
                prices[ticker] = price

        ratios = compute_value_ratios(fundamentals_by_ticker, prices)
        scores = compute_composite_score(ratios)
        selected = select_top_n(scores, p.n_holdings)

        weights: dict[str, float] = {}
        if selected:
            per_holding = 1.0 / len(selected)
            for ticker in selected:
                weights[ticker] = per_holding

        # M04b quant-gate VERDICT.md cycle 1 finding 3: record ONLY names
        # this strategy itself could not score - a declared-universe name
        # with no valid (non-NaN) composite score, per
        # `compute_composite_score`'s own MIN_AVAILABLE_METRICS guard - not
        # a name that scored fine but wasn't picked into the top `n_holdings`.
        # The reason distinguishes WHERE the name fell out: no price at all,
        # no `shares_outstanding` (can't establish market cap -
        # `compute_value_ratios` skips it entirely, so it never even gets a
        # `ratios` row), or a `ratios` row with too few of the four metrics
        # available to average into a composite.
        scored = set(scores.dropna().index)
        priced = set(prices)
        has_ratio_row = set(ratios.index)
        unscored: dict[str, str] = {}
        for ticker in tickers:
            if ticker in scored:
                continue
            if ticker not in priced:
                unscored[ticker] = "missing price"
            elif ticker not in has_ratio_row:
                unscored[ticker] = "missing shares_outstanding"
            else:
                unscored[ticker] = "insufficient fundamentals for a composite score"

        return TargetWeights(
            asof=date, weights=weights, strategy_id=self.strategy_id, unscored=unscored
        )
