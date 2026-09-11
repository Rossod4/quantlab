"""`run_backtest`: one generic EOD backtest loop for ANY M03 `Strategy`.

## The rebalance loop

For each pair of consecutive rebalance dates `(t_k, t_{k+1})` (after
dropping a spurious terminal partial period - see `_drop_terminal_partial_period`,
CLAUDE.md/QUANT-NOTES M00 item):

1. Build a fresh `PITDataContext` at `asof=t_k` from the strategy's own
   `requires()` and call `strategy.generate_targets(ctx, t_k)`. The strategy
   never sees anything else - no raw provider, no future data (see
   `_FilteringConstituentsProvider` below for how a per-ticker data failure
   is kept OUT of what the strategy sees, not silently degraded).
2. Determine this rebalance's FILL DATE: `t_k` itself in `close` mode
   (parity with the old repo - both plugin and engine act on the same
   month-end print), or `next_trading_day(t_k)` in `next_open` mode (a
   position entered "at the next session's open" - a real, tradeable price
   the decision-maker could not have seen at decision time).
3. Settle the PRIOR period's holdings as of this fill date - forced exits
   (CLAUDE.md invariant #3) and the extreme-return guard - THEN charge this
   rebalance's transaction cost and re-book the ledger to the new targets.
4. At the end of the loop (fill date of `t_{k+1}`), realize this period's
   gross/net return.

## Two parallel tracks (why there are two "returns" concepts in this file)

`gross_returns`/`net_returns` (and their equity curves) are computed via the
DIRECT weight-return formula `Σ w_i * r_i`, with `net = gross - cost`
(additive - `costs.apply_transaction_costs`'s exact convention), because
`tests/parity/test_engine_parity.py` requires 1e-10 agreement with the OLD
REPO's engine, which used this same additive convention. `accounting.Ledger`
runs as a SEPARATE, genuinely-compounding track that produces
`BacktestResult.snapshots` (real cash/position dollar amounts for M05+ to
inspect), on the SAME forced-exit/extreme-guard EVENTS as the additive
track but on RAW (non-dividend-adjusted) prices throughout - the ledger
never credits a dividend paid during a holding period, while the return
series does (via `adj_close`). This is the DOMINANT source of divergence
between the two tracks (quant-gate VERDICT.md's non-blocking note,
corrected here: an earlier draft of this docstring wrongly attributed the
gap to a `cost * gross` cross term, which is real but small - a gate probe
measured the dividend gap at roughly the cumulative dividend yield over a
run, e.g. ~30% over the shipped 2012-2026 window at 2%/yr - not a rounding
effect). `snapshots`' cash/position values should therefore be read as
"what a real, non-dividend-reinvesting broker statement would show", NEVER
substituted for `net_equity` in a metrics computation - the two tracks do
NOT "agree to first order" (an earlier version of this sentence claimed
they did; they do not, for the dividend reason above). **M05 and every
downstream consumer must compute metrics from `net_returns`/`net_equity`
(or `gross_returns`/`gross_equity`) only, never from `snapshots`.**

## Turnover convention

`costs.compute_turnover` compares two CONSECUTIVE rebalances' TARGET weights
(`TargetWeights.weights`, as returned by the strategy) - NOT weights
"drifted" by interim price movement. The work packet's formula sketch reads
`w_new - w_old_drifted`; drift was deliberately not implemented for turnover
because the OLD REPO's reference turnover (`compute_turnover` on ticker
SETS) is itself undrifted, and exact 1e-10 parity requires matching it, not
a more realistic drift-aware figure that would differ from the old engine's
by an amount proportional to interim per-name return dispersion (not a
rounding-level difference). See `costs.py`'s module docstring for the full
algebra and `test_costs.py` for the proof this reduces to the old formula on
equal weights. Documented as an intentional convention choice, not an
oversight - a genuinely drift-aware turnover could be added later as a
non-default option without touching the parity path.

## Extreme-return guard, generalized (upside-only, inherited from the old
## repo's vendor-glitch filter - conservative on long books, ANTI-conservative
## on short books)

The old repo's guard EXCLUDES a glitched name from an EQUAL-WEIGHT mean,
implicitly redistributing its weight to survivors (shrinking the divisor
from N to N-k) - the work packet's own "In scope" wording is explicit:
"same semantics: upside-only, count and exclude". `_weighted_return_excluding`
generalizes "redistribute to survivors" to arbitrary `TargetWeights` by
renormalizing the excluded name's OWN sign-book (long weights renormalize
among surviving long weights, short among short - mirroring the old repo's
`long_short_engine.py`, which applies the identical guard to its short
BASKET's underlying price return, per-book counted: `long_extreme`/
`short_extreme`), which reduces EXACTLY to the old repo's `sum(survivors)/
(N-k)` for an equal-weight, single-sign book - proven against the old
repo's own function in tests/parity/test_engine_parity.py's single-period
extreme-return fixture. An EARLIER version of this engine shipped a
capped-at-0%-while-keeping-weight policy instead (code review REVIEW.md
finding 1, iteration 1) - fixed in iteration 2.

**The guard's trigger is the RAW PRICE return of the underlying, not the
POSITION's return, and this is INHERITED PARITY, not a new bug (quant-gate
VERDICT.md finding 4, an explicit ORCHESTRATOR DECISION - not re-litigated
in iteration 3):** a +400% price print on a shorted name is a genuine
short-squeeze loss to the POSITION, and this guard excludes it exactly as
it would exclude a +400% print on a long - the same asymmetry
`long_short_engine.py` carries. This is CONSERVATIVE on a long book (a
spurious gain is discarded, understating the reported return) and
ANTI-CONSERVATIVE on a short book (a genuine adverse move can be discarded,
overstating the reported return) - both are counted separately
(`quality_flags.extreme_returns_long`/`extreme_returns_short`, mirroring
`long_extreme`/`short_extreme`), and a nonzero short-book count adds a
`known_caveats` entry to the result's provenance so this is never silently
absorbed. `BacktestConfig.extreme_return_policy` selects between
`"exclude_legacy"` (default - the behavior above, frozen for parity) and
`"flag_only"` (counts every trigger identically but never excludes/
renormalizes anything - `quality_flags.extreme_returns_long`/`_short` are
populated the same way under either policy). Forced exits (below) are now
ALSO subject to this guard, on the same corrected basis, since finding 3
removed the reason they were previously exempted.

When EVERY name in one sign-book is excluded under `"exclude_legacy"`, that
book contributes 0 to the period's return and the period's net exposure
silently shifts (e.g. a market-neutral book reads as 100% net short that
period) - recorded, never silently absorbed, in
`quality_flags.degenerate_excluded_book_dates`.

## Forced exits, generalized

CLAUDE.md invariant #3: booked at "last available close x (1 - haircut)" on
the LAST bar's own date - for the LEDGER's cash proceeds, using the RAW
last close (a real, tradeable liquidation price). The REPORTED RETURN
series, independently, uses the SAME total-return basis every other name
uses (`exit_adj / entry_adj`, see "next_open return basis" below) with the
SAME haircut applied multiplicatively: `(exit_adj / entry_adj) * (1 -
haircut) - 1` (quant-gate VERDICT.md findings 2 and 3 - an earlier version
computed a RAW price ratio with NO haircut at all, which (a) let the
haircut dial move the ledger but never the reported return series M05+
actually consumes, and (b) let a corporate action inside the final holding
period - e.g. a reverse split ahead of a delisting - read as a fictitious
multi-hundred-percent gain, since a reverse split changes the RAW close
sharply while leaving `adj_close` correctly flat).

Trigger: this engine checks ONLY "the ticker's price series ends before the
period end" (via `prices_for_returns`), which is a STRICT SUPERSET of
`data.corporate_actions.infer_delisting()`'s heuristic (itself documented
to under-detect when index removal precedes the final trade - any ticker
`infer_delisting` would flag necessarily also has a price series ending
early). Checking the superset condition alone therefore satisfies the work
packet's "EITHER an inferred DelistingEvent OR ... price series ends"
without a second, weaker check; `infer_delisting` is not called in this hot
path (documented simplification, not a gap).

## next_open return basis (quant-gate VERDICT.md finding 5)

In `next_open` mode the ledger fills at the next session's OPEN
(`fill_column="open"`), but the REPORTED RETURN must be measured on the
SAME basis the position was actually entered/exited at - crediting the
fill day's intraday open-to-close move to whichever book held the position
BEFORE that session would be wrong (the outgoing book never saw that
move; the incoming book, which bought at the open, did). The total-return
basis price is therefore `row[fill_column] * row["adj_close"] /
row["close"]` - the raw fill price (open or close, by mode) scaled by the
SAME as-of adjustment ratio `adj_close` already carries. In `close` mode
this is `close * adj_close / close == adj_close` exactly (unchanged, still
frozen parity); in `next_open` mode it is the ADJUSTED OPEN, so the return
series is measured open-to-open, matching where the ledger actually filled.
An earlier version of this engine used `adj_close` for the return basis in
BOTH modes, which silently credited the fill-day close-to-open gap to the
wrong book.

## Coverage bound over the UNIVERSE, not the held names (quant-gate
## VERDICT.md finding 1)

`price_availability_from_cache` (data/survivorship.py) is fed the union of
`ctx.universe()` across every rebalance (`all_universe_tickers`) - every
point-in-time constituent the strategy could ever have seen - NOT the union
of `TargetWeights.weights.keys()` (`all_encountered_tickers`, the names it
actually held, still used for provenance's actions-fetched_at range). An
earlier version of this engine used the held-names set for BOTH purposes:
`coverage_gap` (data/survivorship.py) treats any point-in-time member
absent from `price_availability`'s keys as lacking data, so a strategy
holding a strict subset of a fully-cached universe (the common case)
reported a bound driven by "how selective is the strategy", not "how much
of the index is invisible to it" - CLAUDE.md invariant #2's whole point.

## Per-ticker data failure (M02b/M03b verdict carried items)

`_FilteringConstituentsProvider` wraps the real `ConstituentsProvider` at
context-construction time: before a strategy ever sees `ctx.universe()`, it
probes each candidate ticker's corporate-actions fetch (the ONE thing both
`prices()` and `fundamentals()` depend on - `StaleActionsCacheError`/
`ActionsFetchError`, closing the M03b verdict's "one data-failure policy for
both paths" item) and drops (recording, never silently) any ticker that
fails, so a bad ticker never reaches a strategy's own `prices()`/
`fundamentals()` calls (which would otherwise abort the ENTIRE panel fetch
for every ticker in the same call - see data/pit.py's `_gated_actions_by_ticker`).
If more than `BacktestConfig.max_dropped_fraction` of a rebalance's raw
membership fails, `BacktestAbortError` propagates uncaught, aborting the
whole run. A benchmark price/actions fetch failure is NOT wrapped at all -
any exception it raises propagates naturally, which already satisfies "a
failure of the benchmark ... aborts the run with a clear error."

Separately, `unscored_by_date` catches the OTHER kind of drop (M03 verdict,
value-leg silent drops, generalized to any strategy): after
`generate_targets` returns, this engine diffs the strategy's declared
`ctx.universe()` against `TargetWeights.weights.keys()` - any ticker in the
declared universe that never made it into the weights (whether dropped by
the value leg's own `not shares_outstanding` check or any other strategy's
internal filtering) is recorded, never silently absorbed.

**Why `unscored_by_date` is a separate `quality_flags` entry, not merged into
`coverage_report` (REVIEW.md finding 5, iteration 2):** the packet's own
wording ("counts them into the coverage report") was considered, but
`data.survivorship.CoverageReport`/`coverage_gap` model PRICE-DATA
availability, per TICKER, over a whole YEAR (`PriceAvailability.has_data`/
`masked_end`) - not "unscored at this one specific rebalance for this one
specific reason" (a rebalance-level, often non-price event: a missing
FUNDAMENTALS field is a common cause and has nothing to do with price
coverage). Marking an unscored ticker's `PriceAvailability.has_data=False`
for the whole year it happened in would be WRONG in the adverse direction
whenever that same ticker was priceable and scored on every OTHER rebalance
that year (the common case) - it would overstate the year's coverage gap
with information `coverage_gap`'s model has no slot to express correctly.
`unscored_by_date` is therefore surfaced as its own, undiluted, per-date
record in `quality_flags` (never silently absorbed - CLAUDE.md invariant 2's
spirit) rather than forced into a metric shape that would misrepresent it -
the packet's own extension point for `coverage_gap` (`sample_dates`) is
additive-only and does not accommodate a per-date/non-price reason code
without a further, out-of-scope change to `data/survivorship.py`. A
consumer wanting ONE combined "how much can I not trust this book" figure
should read both `coverage_report.overall_bound` AND
`quality_flags.unscored_by_date`/`dropped_tickers_by_date` - not
`coverage_report` alone.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from quantlab.backtest import costs as costs_mod
from quantlab.backtest.accounting import Ledger
from quantlab.backtest.config import BacktestConfig, ExtremeReturnPolicy
from quantlab.backtest.result import BacktestResult, QualityFlags
from quantlab.core.calendar import RebalanceFreq, next_trading_day, rebalance_dates, trading_days
from quantlab.core.config import PlatformConfig
from quantlab.core.errors import ActionsFetchError, QuantLabError, StaleActionsCacheError
from quantlab.core.semantics import DATA_SEMANTICS_VERSION
from quantlab.core.types import PortfolioSnapshot, TargetWeights, normalize_timestamp
from quantlab.data.interfaces import (
    ConstituentsProvider,
    CorporateActionsProvider,
    FundamentalsProvider,
    PriceProvider,
    build_provider,
)
from quantlab.data.pit import PITDataContext
from quantlab.data.requirements import DataRequirements
from quantlab.data.survivorship import coverage_gap, price_availability_from_cache
from quantlab.strategies.base import Strategy

# "Everything up to asof" stand-in, mirroring data/pit.py's own `_EPOCH` -
# duplicated locally (that one is module-private) rather than imported.
_EPOCH = pd.Timestamp("1900-01-01")

# A generous lookback (trading sessions) used ONLY to locate a held
# ticker's actual last traded bar once it has vanished from a tight
# lookback=1 probe at the period-end date - see `_last_available_row`. A
# forced exit is detected between two ADJACENT rebalances (at most a few
# months apart even at `month_end` freq), so the true last bar is never far
# back; kept well under a year of sessions (not, say, a decade) so this
# never risks requesting a window earlier than a calendar's own start bound
# for a backtest running near the start of its available history.
_LAST_PRICE_SEARCH_LOOKBACK_DAYS = 400

_PERIODS_PER_YEAR: dict[RebalanceFreq, float] = {"daily": 252.0, "weekly": 52.0, "month_end": 12.0}

_TTM_EPS_CAVEAT = (
    "TTM EPS can be a mixed-share-terms sum when a split falls between component "
    "filings and restated comparatives are not yet filed (bounded to the P/E leg; "
    "adverse direction - see plans/QUANT-NOTES.md 'From M03b verdict' item 1). The "
    "correct fix is a data-layer follow-on (per-component share terms) scheduled "
    "after M06; until then, treat any value/blend result touching ttm_eps with this "
    "caveat in mind."
)


class BacktestAbortError(QuantLabError):
    """Raised to abort an ENTIRE run outright - never caught or retried
    inside `run_backtest`. Distinct from an unscoreable-date event (a
    strategy-raised `ValueError`), which is recorded and, per
    `BacktestConfig.abort_on_unscoreable`, either also aborts or is
    tolerated (record-and-hold-prior)."""


@dataclass(frozen=True)
class BacktestProviders:
    """The four concrete providers a backtest run is wired to, plus the
    cache directory they share (needed for survivorship's cache-sidecar
    inspection and for provenance)."""

    price: PriceProvider
    constituents: ConstituentsProvider
    fundamentals: FundamentalsProvider
    corporate_actions: CorporateActionsProvider
    cache_dir: Path


def build_backtest_providers(platform_config: PlatformConfig) -> BacktestProviders:
    """Construct `BacktestProviders` from a `PlatformConfig` - the CLI's
    entry point into this module. `data.interfaces.build_provider` only
    knows "prices"/"constituents" kinds today; fundamentals/corporate-actions
    vendors are constructed directly here (there is exactly one
    implementation of each in this milestone, `EdgarFundamentalsProvider`
    and `YFinanceCorporateActionsProvider`) rather than extending that
    factory function, which is outside this packet's scope."""
    from quantlab.core.errors import ConfigError
    from quantlab.data.corporate_actions import YFinanceCorporateActionsProvider
    from quantlab.data.providers.edgar_fundamentals import EdgarFundamentalsProvider

    price = build_provider("prices", platform_config.providers.prices, platform_config)
    constituents = build_provider(
        "constituents", platform_config.providers.constituents, platform_config
    )
    fundamentals_name = platform_config.providers.fundamentals
    if fundamentals_name != "edgar":
        raise ConfigError(f"unknown fundamentals provider: {fundamentals_name!r}")
    fundamentals = EdgarFundamentalsProvider(cache_dir=platform_config.cache_dir)
    corporate_actions = YFinanceCorporateActionsProvider(cache_dir=platform_config.cache_dir)

    return BacktestProviders(
        price=price,
        constituents=constituents,
        fundamentals=fundamentals,
        corporate_actions=corporate_actions,
        cache_dir=platform_config.cache_dir,
    )


# -- rebalance-date hygiene (QUANT-NOTES M00 carried item) -------------------


def _is_genuine_period_boundary(date: pd.Timestamp, freq: RebalanceFreq) -> bool:
    """True if `date` is really the last trading day of its own week/month
    (for `freq="weekly"`/`"month_end"`) - i.e. the NEXT trading day falls in
    a different period. Always True for `freq="daily"`."""
    if freq == "daily":
        return True
    nxt = next_trading_day(date)
    if freq == "weekly":
        d_iso, n_iso = date.isocalendar(), nxt.isocalendar()
        return (d_iso[0], d_iso[1]) != (n_iso[0], n_iso[1])
    if freq == "month_end":
        return (date.year, date.month) != (nxt.year, nxt.month)
    raise ValueError(f"unknown freq: {freq!r}")


def _drop_terminal_partial_period(dates: pd.DatetimeIndex, freq: RebalanceFreq) -> pd.DatetimeIndex:
    """`core.calendar.rebalance_dates` always includes the last trading day
    in range as its final entry, even when that day is NOT a genuine
    period boundary (e.g. a `month_end`-freq range ending 2023-06-15 books a
    spurious rebalance on 6/15 itself - QUANT-NOTES M00). Drop it when it
    isn't a genuine boundary; a real boundary (the range happens to end
    exactly on a month-end) is kept."""
    if len(dates) == 0 or _is_genuine_period_boundary(dates[-1], freq):
        return dates
    return dates[:-1]


# -- per-ticker data-failure filtering (M02b/M03b verdict carried items) -----


class _FilteringConstituentsProvider(ConstituentsProvider):
    """See module docstring's "Per-ticker data failure" section. Wraps a
    real `ConstituentsProvider`; `membership()` drops any ticker whose
    corporate-actions fetch fails, recording each drop via `on_drop` and
    aborting the whole run if drops exceed `max_dropped_fraction`."""

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


# -- accounting-path price helpers (prices_for_returns() only - never prices()) --


def _accounting_context(
    providers: BacktestProviders, asof: pd.Timestamp, lookback_days: int
) -> PITDataContext:
    """The engine's OWN context for fill/settlement/benchmark bookkeeping -
    `accounting=True` (data/pit.py) is what actually authorizes calling
    `prices_for_returns()` below; this context is never handed to a
    strategy (see `context_factory` in `run_backtest`, which always
    constructs the DECISION-path context with the default `accounting=False`)."""
    return PITDataContext(
        asof=asof,
        requirements=DataRequirements(price_lookback_days=lookback_days),
        price_provider=providers.price,
        constituents_provider=providers.constituents,
        fundamentals_provider=providers.fundamentals,
        corporate_actions_provider=providers.corporate_actions,
        accounting=True,
    )


def _rows_at_exact_session(
    providers: BacktestProviders, tickers: list[str], asof: pd.Timestamp
) -> dict[str, pd.Series]:
    """Each ticker's row on the EXACT trading session `asof` snaps to (via
    `prices_for_returns(tickers, 1)`) - absent if the ticker has no bar
    there (e.g. it stopped trading earlier). Used both to fetch a normal
    fill/mark price and to DETECT the forced-exit condition (a ticker
    missing here needs `_last_available_row` instead)."""
    if not tickers:
        return {}
    panel = _accounting_context(providers, asof, 1).prices_for_returns(tickers, 1)
    return {
        t: panel[panel["ticker"] == t].iloc[-1] for t in tickers if (panel["ticker"] == t).any()
    }


def _last_available_row(
    providers: BacktestProviders, ticker: str, asof: pd.Timestamp
) -> pd.Series | None:
    """The most recent bar for `ticker` on or before `asof`, searched over a
    generous lookback - used ONLY once `_rows_at_exact_session` has already
    shown the ticker has no bar exactly at `asof` (a forced-exit candidate),
    to find the actual last-traded price to book the exit at."""
    ctx = _accounting_context(providers, asof, _LAST_PRICE_SEARCH_LOOKBACK_DAYS)
    panel = ctx.prices_for_returns([ticker], _LAST_PRICE_SEARCH_LOOKBACK_DAYS)
    sub = panel[panel["ticker"] == ticker]
    return sub.iloc[-1] if not sub.empty else None


def _corwin_schultz_one_way_bps(
    providers: BacktestProviders, tickers: list[str], asof: pd.Timestamp, lookback_days: int
) -> dict[str, float]:
    """Per-ticker one-way cost (bps) from the Corwin-Schultz spread
    estimator, over the trailing `lookback_days` sessions ending at `asof`.
    One-way = HALF the estimated full spread (a full round-trip crosses the
    spread once each way); a ticker with insufficient history to estimate a
    spread gets 0bps (better than aborting a whole rebalance over one thin
    name - this cost model is explicitly optional/approximate, per the work
    packet)."""
    if not tickers:
        return {}
    panel = _accounting_context(providers, asof, lookback_days).prices_for_returns(
        tickers, lookback_days
    )
    result: dict[str, float] = {}
    for ticker in tickers:
        sub = panel[panel["ticker"] == ticker]
        if len(sub) < 2:
            result[ticker] = 0.0
            continue
        spread = costs_mod.corwin_schultz_spread(sub["high"], sub["low"])
        result[ticker] = 0.0 if pd.isna(spread) else spread * 10_000 / 2.0
    return result


def _benchmark_returns(
    providers: BacktestProviders, benchmark: str, fill_dates: list[pd.Timestamp]
) -> pd.Series:
    """Buy-and-hold benchmark returns over the EXACT SAME (entry, exit) date
    pairs the strategy's own realized returns use (old repo Fix 2: first
    benchmark return date == first strategy return date - satisfied by
    construction here, not just by a regression test). Raises
    `BacktestAbortError` if the benchmark is missing a price on any fill
    date - "a failure of the benchmark ... aborts the run with a clear
    error"."""
    # Enough TRADING SESSIONS to span from the first to the last fill date
    # (not just "one session per fill date" - consecutive fill dates are
    # typically weeks/months apart, not adjacent sessions).
    lookback_days = len(trading_days(fill_dates[0], fill_dates[-1])) + 30
    panel = _accounting_context(providers, fill_dates[-1], lookback_days).prices_for_returns(
        [benchmark], lookback_days
    )
    panel = panel[panel["ticker"] == benchmark]
    prices: dict[pd.Timestamp, float] = {}
    for d in fill_dates:
        row = panel.loc[panel.index == d]
        if row.empty:
            raise BacktestAbortError(f"benchmark {benchmark!r} has no price data on {d.date()}")
        prices[d] = float(row["adj_close"].iloc[0])

    returns = {
        fill_dates[i + 1]: prices[fill_dates[i + 1]] / prices[fill_dates[i]] - 1.0
        for i in range(len(fill_dates) - 1)
    }
    return pd.Series(returns, dtype=float).sort_index()


def _weighted_return_excluding(
    weights: dict[str, float],
    realized: dict[str, float],
    excluded: set[str],
    policy: ExtremeReturnPolicy,
) -> tuple[float, list[str]]:
    """Weighted period return under the extreme-return guard's policy.

    `policy="exclude_legacy"` (default, frozen parity): `excluded` names are
    DROPPED and the remaining names in their own sign-book (long vs short)
    RENORMALIZED to preserve that book's total exposure - the old repo's
    extreme-return guard (`compute_holding_period_return`) excludes a
    flagged name from its equal-weight mean, shrinking the divisor from N to
    N-k; this is the generalization to arbitrary weight vectors (code review
    REVIEW.md finding 1 - an earlier capped-at-0%-while-keeping-weight
    policy was NOT equivalent: it changed every subsequent equity value by a
    factor of N/(N-k) whenever k>=1). `policy="flag_only"` (quant-gate
    VERDICT.md finding 4(c)): every `realized` value is included at its full
    original weight regardless of `excluded` - the guard still COUNTS a
    trigger (the caller increments `extreme_returns_long`/`_short` either
    way) but never changes the reported return. Splitting into signed books
    generalizes "the equal-weight mean" to a long-short/130-30 book exactly
    the way the old repo's `long_short_engine.py` does (separate long/short
    `compute_holding_period_return` calls, each with its OWN exclusion) -
    this is INHERITED PARITY, including its asymmetry on shorts (a
    genuinely adverse short-squeeze move can be excluded too - see
    engine.py's module docstring), not something this function decides.

    For an equal-weight, single-sign (long-only) book with N names and k
    excluded under `exclude_legacy`: every survivor's weight is 1/N,
    `book_total` (sum of the full book's weights) is N*(1/N)=1,
    `survivor_total` is (N-k)/N, so `scale = book_total / survivor_total =
    N/(N-k)`, and each survivor's rescaled weight is `(1/N)*(N/(N-k)) =
    1/(N-k)` - EXACTLY the old repo's `sum(survivor_returns) / (N-k)`.
    Proven in tests/parity/test_engine_parity.py's single-period extreme-
    return fixture (1e-10 agreement with the old repo's own function).

    Returns `(period_return, degenerate_books)`: under `exclude_legacy`,
    a sign-book where EVERY name is excluded contributes 0 to the return
    (no survivors to renormalize onto) and is named in `degenerate_books`
    ("long"/"short") - quant-gate VERDICT.md finding 4's "related, same
    function" note: this silently changes the period's net exposure (e.g. a
    market-neutral book reads 100% net short that period), so the caller
    records it in `quality_flags.degenerate_excluded_book_dates` rather than
    absorbing it. Exceedingly unlikely at the default 300% bound.
    """
    if policy == "flag_only" or not excluded:
        return sum(weights[t] * realized[t] for t in weights), []

    total = 0.0
    degenerate_books: list[str] = []
    for is_long_book in (True, False):
        names = [t for t, w in weights.items() if (w > 0) == is_long_book and w != 0]
        if not names:
            continue
        survivors = [t for t in names if t not in excluded]
        if not survivors:
            degenerate_books.append("long" if is_long_book else "short")
            continue
        book_total = sum(weights[t] for t in names)
        survivor_total = sum(weights[t] for t in survivors)
        scale = book_total / survivor_total
        total += sum(weights[t] * scale * realized[t] for t in survivors)
    return total, degenerate_books


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    return Path.cwd()


def _git_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=_repo_root(),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except OSError:
        pass
    return "unknown"


def _actions_fetched_at(cache_dir: Path, tickers: set[str]) -> dict[str, str | None]:
    """Read the `fetched_at` sidecar (data/corporate_actions.py's staleness
    metadata) for each ticker directly, for provenance's fetched_at min/max
    - a documented, read-only duplication of that module's private path
    convention (`<cache_dir>/actions/<ticker>.meta.json`), not a second
    caching implementation."""
    from quantlab.data.cache import read_json_meta

    result: dict[str, str | None] = {}
    for ticker in tickers:
        meta = read_json_meta(Path(cache_dir) / "actions" / f"{ticker}.meta.json")
        result[ticker] = meta.get("fetched_at") if meta else None
    return result


# -- the engine ---------------------------------------------------------------


def run_backtest(
    strategy: Strategy, config: BacktestConfig, providers: BacktestProviders
) -> BacktestResult:
    requirements = strategy.requires()

    raw_dates = rebalance_dates(config.start, config.end, config.rebalance_freq)
    reb_dates = _drop_terminal_partial_period(raw_dates, config.rebalance_freq)
    if len(reb_dates) < 2:
        raise BacktestAbortError(
            f"only {len(reb_dates)} usable rebalance date(s) between {config.start.date()} and "
            f"{config.end.date()} at freq={config.rebalance_freq!r} after dropping a terminal "
            "partial period - need at least 2 to realize one holding period"
        )

    dropped_tickers_by_date: dict[str, list[str]] = {}
    unscored_by_date: dict[str, list[str]] = {}
    unscoreable_dates: list[str] = []
    degenerate_excluded_book_dates: dict[str, list[str]] = {}
    forced_exits = 0
    extreme_returns = 0
    extreme_returns_long = 0
    extreme_returns_short = 0
    all_encountered_tickers: set[str] = set()
    # Every point-in-time UNIVERSE member ever seen (quant-gate VERDICT.md
    # finding 1) - NOT the same set as `all_encountered_tickers` (held
    # names only). The coverage bound must measure what the strategy could
    # SEE, not what it happened to buy; a name the strategy never selected
    # is invisible to `all_encountered_tickers` and, before this fix, was
    # therefore always reported as "no price data" by `price_availability_
    # from_cache` regardless of its real, complete cache on disk.
    all_universe_tickers: set[str] = set()

    asof_box: dict[str, pd.Timestamp] = {"value": reb_dates[0]}

    def context_factory(reqs: DataRequirements) -> PITDataContext:
        asof = asof_box["value"]
        constituents: ConstituentsProvider = providers.constituents
        if reqs.needs_universe and (reqs.price_lookback_days > 0 or reqs.fundamental_fields):

            def _on_drop(ticker: str, exc: Exception, _asof=asof) -> None:
                dropped_tickers_by_date.setdefault(str(_asof.date()), []).append(ticker)

            constituents = _FilteringConstituentsProvider(
                inner=providers.constituents,
                corporate_actions_provider=providers.corporate_actions,
                max_dropped_fraction=config.max_dropped_fraction,
                on_drop=_on_drop,
            )
        # `accounting` omitted (defaults False, data/pit.py): this is the
        # DECISION-path context - the only one a strategy, or a blend
        # child via `set_context_factory`, ever receives. Calling
        # `prices_for_returns()` on it now raises `UndeclaredDataError` by
        # construction (M04 HANDOFF.3 follow-up to quant-gate VERDICT.md).
        return PITDataContext(
            asof=asof,
            requirements=reqs,
            price_provider=providers.price,
            constituents_provider=constituents,
            fundamentals_provider=providers.fundamentals,
            corporate_actions_provider=providers.corporate_actions,
        )

    if hasattr(strategy, "set_context_factory"):
        strategy.set_context_factory(context_factory)

    ledger = Ledger(config.initial_capital)
    holdings_history: dict[pd.Timestamp, TargetWeights] = {}
    snapshots: dict[pd.Timestamp, PortfolioSnapshot] = {}
    turnover_hist: dict[pd.Timestamp, float] = {}
    gross_returns: dict[pd.Timestamp, float] = {}
    net_returns: dict[pd.Timestamp, float] = {}
    cost_drag_hist: dict[pd.Timestamp, float] = {}

    prior_weights: dict[str, float] = {}
    fill_dates: list[pd.Timestamp] = []

    periods_per_year = _PERIODS_PER_YEAR[config.rebalance_freq]

    # `fill_column` is the RAW, tradeable price used for Ledger bookkeeping
    # (position sizing, turnover-dollar reporting) - "close" in `close` mode
    # (parity with the old repo, which acts and fills on the same print),
    # "open" in `next_open` mode (the next session's real opening print).
    # This is DELIBERATELY separate from the return series below: the
    # Ledger runs entirely in raw, non-dividend-adjusted terms (a documented
    # simplification - see this module's docstring's "Two parallel tracks"
    # section), while `gross_returns`/`net_returns` use `adj_close` (total-
    # return) at the SAME two fill dates, regardless of mode - only the
    # DATE the return is measured at changes between modes, never the
    # column. Conflating the two (using one column for both purposes) was
    # an actual bug caught by test_engine.py's next_open/close divergence
    # test during development - the two price bases must stay separate.
    fill_column = "close" if config.execution == "close" else "open"

    prior_fill_prices: dict[str, float] = {}
    prior_return_prices: dict[str, float] = {}
    prior_cost_fraction = 0.0

    def _settle(fill_date: pd.Timestamp) -> tuple[dict[str, float], dict[str, float]]:
        """Settle the period that just ended AT `fill_date`: for every
        ticker in `prior_weights`, determine its realized return (forced-
        exit / extreme-guard adjusted per this module's docstring) from
        `prior_return_prices` (its entry total-return basis price), update
        the ledger (using `prior_fill_prices`, the RAW entry price)
        accordingly, and record `gross_returns[fill_date]`/
        `net_returns[fill_date]`/`cost_drag[fill_date]`. Returns
        `(mark_prices, exit_return_prices)`: `mark_prices` (RAW column, for
        `rebalance_to`'s `equity_before` valuation of the ledger's
        now-current, post-force-exit holdings) and `exit_return_prices`
        (the total-return basis price at this same fill date - the fresh
        entry-basis for the UPCOMING period if a ticker is held again,
        computed once here rather than re-fetched).

        Total-return basis price (quant-gate VERDICT.md finding 5): NOT
        always `adj_close` - in `next_open` mode it is the ADJUSTED OPEN
        (`row[fill_column] * row["adj_close"] / row["close"]`), so the
        return is measured open-to-open on the SAME basis the position was
        actually filled at, rather than crediting the fill day's intraday
        close-to-open move to the OUTGOING book. In `close` mode this
        reduces to exactly `adj_close` (`fill_column == "close"`, so the
        ratio is `close * adj_close / close == adj_close`) - unchanged,
        still frozen parity.

        Forced exits (CLAUDE.md invariant #3) are booked via the ledger at
        the RAW last close (haircut applied there for cash-proceeds
        realism) and, independently, contribute to the return series at
        `(exit_adj / entry_adj) * (1 - haircut) - 1` (quant-gate VERDICT.md
        findings 2/3: the haircut now genuinely reaches the reported
        series, and the basis is the SAME total-return basis every other
        name uses - a reverse split inside the final holding period no
        longer reads as a fictitious multi-hundred-percent gain). Forced
        exits ARE now subject to the extreme-return guard on this
        corrected, consistent basis (re-examined per finding 3's own
        instruction, rather than silently inheriting the old exemption)."""
        nonlocal forced_exits, extreme_returns, extreme_returns_long, extreme_returns_short
        if not prior_weights:
            return {}, {}
        realized: dict[str, float] = {}
        mark_prices: dict[str, float] = {}
        exit_return_prices: dict[str, float] = {}
        excluded: set[str] = set()
        exact = _rows_at_exact_session(providers, sorted(prior_weights), fill_date)
        for ticker in prior_weights:
            row = exact.get(ticker)
            entry_return = prior_return_prices[ticker]
            is_forced_exit = row is None
            if is_forced_exit:
                entry_fill = prior_fill_prices[ticker]
                last = _last_available_row(providers, ticker, fill_date)
                last_price_raw = float(last["close"]) if last is not None else entry_fill
                last_price_adj = float(last["adj_close"]) if last is not None else entry_return
                ledger.force_exit(
                    ticker, last_price_raw, config.delisting_haircut, reason="price_series_ended"
                )
                forced_exits += 1
                r = (last_price_adj / entry_return) * (1.0 - config.delisting_haircut) - 1.0
            else:
                adj_ratio = float(row["adj_close"]) / float(row["close"])
                exit_price = float(row[fill_column]) * adj_ratio
                exit_return_prices[ticker] = exit_price
                r = exit_price / entry_return - 1.0

            if r > config.extreme_return_bound:
                # See this function's docstring and `_weighted_return_
                # excluding`'s: the OLD repo's own guard semantics
                # ("count and exclude"), applied per sign-book so a short's
                # exclusion never redistributes onto longs or vice versa -
                # inherited parity, including the short-book asymmetry
                # (quant-gate VERDICT.md finding 4, ORCHESTRATOR DECISION:
                # frozen as `extreme_return_policy="exclude_legacy"`, not
                # re-litigated here). The ledger's OWN mark (a separate,
                # documented track) still freezes a non-forced-exit name at
                # its entry price - neither track trusts a print this far
                # outside a plausible single-period move.
                extreme_returns += 1
                if prior_weights[ticker] > 0:
                    extreme_returns_long += 1
                else:
                    extreme_returns_short += 1
                excluded.add(ticker)
                if not is_forced_exit:
                    mark_prices[ticker] = prior_fill_prices[ticker]
            elif not is_forced_exit:
                mark_prices[ticker] = float(row[fill_column])
            realized[ticker] = r

        gross, degenerate_books = _weighted_return_excluding(
            prior_weights, realized, excluded, config.extreme_return_policy
        )
        if degenerate_books:
            degenerate_excluded_book_dates.setdefault(str(fill_date.date()), []).extend(
                degenerate_books
            )
        short_exposure = sum(-w for w in prior_weights.values() if w < 0)
        borrow = costs_mod.borrow_fee_for_period(
            short_exposure, config.borrow_fee_annual_bps, periods_per_year
        )
        net = gross - prior_cost_fraction - borrow
        gross_returns[fill_date] = gross
        net_returns[fill_date] = net
        cost_drag_hist[fill_date] = gross - net
        return mark_prices, exit_return_prices

    for k in range(len(reb_dates) - 1):
        t = reb_dates[k]
        asof_box["value"] = t
        fill_date = t if config.execution == "close" else next_trading_day(t)
        fill_dates.append(fill_date)

        mark_prices, settled_return_prices = _settle(fill_date)

        # -- decision -------------------------------------------------------
        ctx = context_factory(requirements)
        try:
            targets = strategy.generate_targets(ctx, t)
        except ValueError as exc:
            unscoreable_dates.append(str(t.date()))
            if config.abort_on_unscoreable:
                raise BacktestAbortError(f"unscoreable rebalance at {t.date()}: {exc}") from exc
            # Record-and-hold-prior (QUANT-NOTES M03 carried item 4): keep
            # every prior holding that SURVIVED settlement (a name forced
            # out above cannot be "held"; its freed weight simply sits in
            # cash rather than being redistributed - documented, not a bug).
            held_weights = {t2: w for t2, w in prior_weights.items() if t2 in mark_prices}
            targets = TargetWeights(asof=t, weights=held_weights, strategy_id=strategy.strategy_id)

        if requirements.needs_universe:
            declared = set(ctx.universe())
            # quant-gate VERDICT.md finding 1: the coverage bound must
            # measure the UNIVERSE the strategy could see, not the names it
            # happened to select - accumulate every point-in-time member
            # ever seen, separately from `all_encountered_tickers` (held
            # names, used for provenance's actions-fetched_at range).
            all_universe_tickers.update(declared)
            unscored = sorted(declared - set(targets.weights.keys()))
            if unscored:
                unscored_by_date[str(t.date())] = unscored

        holdings_history[t] = targets
        all_encountered_tickers.update(targets.weights)
        all_encountered_tickers.update(prior_weights)

        # -- entry prices for the new target book ----------------------------
        needed = sorted(set(targets.weights) - set(mark_prices))
        fresh = _rows_at_exact_session(providers, needed, fill_date) if needed else {}
        fill_prices = dict(mark_prices)
        fill_prices.update({t2: float(row[fill_column]) for t2, row in fresh.items()})
        return_prices = dict(settled_return_prices)
        return_prices.update(
            {
                t2: float(row[fill_column]) * float(row["adj_close"]) / float(row["close"])
                for t2, row in fresh.items()
            }
        )

        tradeable_weights = {t2: w for t2, w in targets.weights.items() if t2 in fill_prices}
        missing_fill = sorted(set(targets.weights) - set(tradeable_weights))
        if missing_fill:
            dropped_tickers_by_date.setdefault(str(t.date()), []).extend(missing_fill)

        turnover = costs_mod.compute_turnover(prior_weights, tradeable_weights)
        turnover_hist[t] = turnover

        if config.cost_model == "flat_bps":
            cost_rate: float | dict[str, float] = config.one_way_cost_bps
        else:
            names = sorted(set(prior_weights) | set(tradeable_weights))
            cost_rate = _corwin_schultz_one_way_bps(
                providers, names, fill_date, config.corwin_schultz_lookback_days
            )
        cost_fraction = costs_mod.transaction_cost_fraction(
            prior_weights, tradeable_weights, cost_rate
        )

        ledger.rebalance_to(
            TargetWeights(asof=t, weights=tradeable_weights, strategy_id=targets.strategy_id),
            fill_prices,
            cost_fraction,
            mark_prices=mark_prices or None,
        )
        snapshots[t] = ledger.snapshot(t, fill_prices)

        prior_weights = tradeable_weights
        prior_fill_prices = {t2: fill_prices[t2] for t2 in tradeable_weights}
        prior_return_prices = {t2: return_prices[t2] for t2 in tradeable_weights}
        prior_cost_fraction = cost_fraction

    # -- settle the FINAL holding period (no further rebalance follows it) --
    final_fill_date = (
        reb_dates[-1] if config.execution == "close" else next_trading_day(reb_dates[-1])
    )
    fill_dates.append(final_fill_date)
    _settle(final_fill_date)

    gross_returns_s = pd.Series(gross_returns, dtype=float).sort_index()
    net_returns_s = pd.Series(net_returns, dtype=float).sort_index()
    turnover_s = pd.Series(turnover_hist, dtype=float).sort_index()
    cost_drag_s = pd.Series(cost_drag_hist, dtype=float).sort_index()

    def _equity_with_start(returns: pd.Series, start_date: pd.Timestamp) -> pd.Series:
        equity = (1.0 + returns).cumprod()
        return pd.concat([pd.Series([1.0], index=[start_date]), equity])

    gross_equity = _equity_with_start(gross_returns_s, reb_dates[0])
    net_equity = _equity_with_start(net_returns_s, reb_dates[0])

    benchmark_returns_s = _benchmark_returns(providers, config.benchmark, fill_dates)
    benchmark_equity = _equity_with_start(benchmark_returns_s, reb_dates[0])

    universe_history = providers.constituents.membership_history(config.start, config.end)
    # quant-gate VERDICT.md finding 1: coverage over the UNIVERSE the
    # strategy could see (falls back to held names for a strategy that
    # never declares `needs_universe` at all, the best available proxy).
    coverage_tickers = all_universe_tickers | all_encountered_tickers
    price_availability = price_availability_from_cache(
        sorted(coverage_tickers), providers.cache_dir
    )
    report = coverage_gap(
        universe_history, price_availability, config.start, config.end, sample_dates=reb_dates
    )

    quality_flags = QualityFlags(
        forced_exits=forced_exits,
        extreme_returns=extreme_returns,
        extreme_returns_long=extreme_returns_long,
        extreme_returns_short=extreme_returns_short,
        missing_forward_prices=forced_exits,
        unscoreable_dates=tuple(unscoreable_dates),
        dropped_tickers_by_date=dropped_tickers_by_date,
        unscored_by_date=unscored_by_date,
        degenerate_excluded_book_dates=degenerate_excluded_book_dates,
    )

    known_caveats = []
    if "ttm_eps" in requirements.fundamental_fields:
        known_caveats.append(_TTM_EPS_CAVEAT)
    if extreme_returns_short > 0 and config.extreme_return_policy == "exclude_legacy":
        known_caveats.append(
            f"The extreme-return guard (upside-only, inherited from the old repo's "
            f"vendor-glitch filter) excluded {extreme_returns_short} adverse move(s) in "
            "the short book this run under the default 'exclude_legacy' policy - this "
            "FLATTERS reported short-book performance by hiding a real loss a short "
            "position could take from a squeeze, not just a data glitch. See engine.py's "
            "module docstring; set extreme_return_policy='flag_only' to count without "
            "excluding."
        )

    fetched_at = _actions_fetched_at(providers.cache_dir, all_encountered_tickers)
    known_fetched_at = sorted(v for v in fetched_at.values() if v is not None)

    provenance = {
        "strategy_id": strategy.strategy_id,
        "strategy_params": strategy.params,
        "backtest_config": json.loads(config.model_dump_json()),
        "providers": {
            "prices": type(providers.price).__name__,
            "constituents": type(providers.constituents).__name__,
            "fundamentals": type(providers.fundamentals).__name__,
            "corporate_actions": type(providers.corporate_actions).__name__,
        },
        "actions_cache_fetched_at": {
            "min": known_fetched_at[0] if known_fetched_at else None,
            "max": known_fetched_at[-1] if known_fetched_at else None,
        },
        "quantlab_git_sha": _git_sha(),
        "run_timestamp": pd.Timestamp.now("UTC").isoformat(),
        "data_semantics_version": DATA_SEMANTICS_VERSION,
        "known_caveats": known_caveats,
    }

    return BacktestResult(
        gross_returns=gross_returns_s,
        net_returns=net_returns_s,
        gross_equity=gross_equity,
        net_equity=net_equity,
        benchmark_returns=benchmark_returns_s,
        benchmark_equity=benchmark_equity,
        turnover=turnover_s,
        cost_drag=cost_drag_s,
        holdings_history=holdings_history,
        snapshots=snapshots,
        quality_flags=quality_flags,
        coverage_report=report,
        provenance=provenance,
    )
