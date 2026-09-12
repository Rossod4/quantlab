"""`run_backtest`: one generic EOD backtest loop for ANY M03 `Strategy`.

## The rebalance loop

For each pair of consecutive rebalance dates `(t_k, t_{k+1})` (after
dropping a spurious terminal partial period - see `_drop_terminal_partial_period`,
CLAUDE.md/QUANT-NOTES M00 item):

1. Build a fresh `PITDataContext` at `asof=t_k` from the strategy's own
   `requires()` and call `strategy.generate_targets(ctx, t_k)`. The strategy
   never sees anything else - no raw provider, no future data (see
   `backtest/context.py`'s `_FilteringConstituentsProvider` for how a
   per-ticker data failure is kept OUT of what the strategy sees, not
   silently degraded).
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
value-leg silent drops, generalized to any strategy). M04b quant-gate
VERDICT.md cycle 1 finding 3 (BLOCKING) changed HOW this is populated: this
engine used to diff the strategy's declared `ctx.universe()` against
`TargetWeights.weights.keys()` after `generate_targets` returned, which
conflates "the strategy tried to score this name and couldn't" with "the
strategy scored it fine and didn't select it into a top-N book" - measured
at the gate on a real ~500-name universe with a 30-name momentum book, that
made the flag ~473 names wide at EVERY rebalance, indistinguishable from
noise. This engine now reads `TargetWeights.unscored` (core/types.py) -
additive, ticker -> reason - directly: the strategy itself (momentum.py,
value.py, blend.py) reports only names it could not establish a score for
(a missing lookback price, missing shares_outstanding, etc.), never a mere
non-selection.

**Why `unscored_by_date` is a separate `quality_flags` entry, not merged into
`coverage_report`:** the packet's own
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
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from quantlab.backtest import costs as costs_mod
from quantlab.backtest.accounting import Ledger
from quantlab.backtest.config import BacktestConfig, ExtremeReturnPolicy
from quantlab.backtest.context import DecisionProviders, actions_fetched_at, build_decision_context
from quantlab.backtest.panel_store import PricePanelStore
from quantlab.backtest.result import BacktestResult, QualityFlags
from quantlab.core.calendar import (
    RebalanceFreq,
    calendar_first_session,
    next_trading_day,
    rebalance_dates,
    trading_days,
)
from quantlab.core.config import PlatformConfig

# BacktestAbortError now lives in core/errors.py (quant-gate VERDICT.md M08
# cycle-1 finding 2 - see backtest/context.py's module docstring for why);
# re-exported here under its original name so every existing `from
# quantlab.backtest.engine import BacktestAbortError` call site (including
# tests/test_engine.py) is unaffected.
from quantlab.core.errors import (
    ActionsFetchError,
    BacktestAbortError,
    LookaheadError,
    StaleActionsCacheError,
)
from quantlab.core.semantics import DATA_SEMANTICS_VERSION
from quantlab.core.types import PortfolioSnapshot, TargetWeights
from quantlab.data.interfaces import (
    ConstituentsProvider,
    CorporateActionsProvider,
    FundamentalsProvider,
    PriceProvider,
    build_provider,
)
from quantlab.data.pit import PITDataContext
from quantlab.data.quality import membership_start_by_ticker
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
#
# `_FilteringConstituentsProvider` now lives in `backtest/context.py`
# (quant-gate VERDICT.md M08 cycle-1 finding 2), shared verbatim with
# `paper/runner.py` via `build_decision_context` below - see that module's
# docstring. This section header and the module docstring's "Per-ticker
# data failure" cross-reference are kept for readers landing here from
# either.


# -- accounting-path price helpers (prices_for_returns() only - never prices()) --


def _accounting_context(
    providers: BacktestProviders,
    asof: pd.Timestamp,
    lookback_days: int,
    panel_store: PricePanelStore | None = None,
) -> PITDataContext:
    """The engine's OWN context for fill/settlement/benchmark bookkeeping -
    `accounting=True` (data/pit.py) is what actually authorizes calling
    `prices_for_returns()` below; this context is never handed to a
    strategy (see `context_factory` in `run_backtest`, which always
    constructs the DECISION-path context with the default `accounting=False`).

    `panel_store` (M04b work packet item 4, default None): the run-level
    `PricePanelStore` `run_backtest` builds once, threaded through every
    accounting call site below so they slice an in-memory panel instead of
    each independently calling `providers.price.get_prices()` again."""
    return PITDataContext(
        asof=asof,
        requirements=DataRequirements(price_lookback_days=lookback_days),
        price_provider=providers.price,
        constituents_provider=providers.constituents,
        fundamentals_provider=providers.fundamentals,
        corporate_actions_provider=providers.corporate_actions,
        accounting=True,
        panel_store=panel_store,
    )


def _rows_at_exact_session(
    providers: BacktestProviders,
    tickers: list[str],
    asof: pd.Timestamp,
    panel_store: PricePanelStore | None = None,
) -> dict[str, pd.Series]:
    """Each ticker's row on the EXACT trading session `asof` snaps to (via
    `prices_for_returns(tickers, 1)`) - absent if the ticker has no bar
    there (e.g. it stopped trading earlier). Used both to fetch a normal
    fill/mark price and to DETECT the forced-exit condition (a ticker
    missing here needs `_last_available_row` instead)."""
    if not tickers:
        return {}
    panel = _accounting_context(providers, asof, 1, panel_store).prices_for_returns(tickers, 1)
    return {
        t: panel[panel["ticker"] == t].iloc[-1] for t in tickers if (panel["ticker"] == t).any()
    }


def _last_available_row(
    providers: BacktestProviders,
    ticker: str,
    asof: pd.Timestamp,
    panel_store: PricePanelStore | None = None,
) -> pd.Series | None:
    """The most recent bar for `ticker` on or before `asof`, searched over a
    generous lookback - used ONLY once `_rows_at_exact_session` has already
    shown the ticker has no bar exactly at `asof` (a forced-exit candidate),
    to find the actual last-traded price to book the exit at."""
    ctx = _accounting_context(providers, asof, _LAST_PRICE_SEARCH_LOOKBACK_DAYS, panel_store)
    panel = ctx.prices_for_returns([ticker], _LAST_PRICE_SEARCH_LOOKBACK_DAYS)
    sub = panel[panel["ticker"] == ticker]
    return sub.iloc[-1] if not sub.empty else None


def _corwin_schultz_one_way_bps(
    providers: BacktestProviders,
    tickers: list[str],
    asof: pd.Timestamp,
    lookback_days: int,
    panel_store: PricePanelStore | None = None,
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
    panel = _accounting_context(providers, asof, lookback_days, panel_store).prices_for_returns(
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
    panel_store: PricePanelStore, benchmark: str, fill_dates: list[pd.Timestamp]
) -> pd.Series:
    """Buy-and-hold benchmark returns over the EXACT SAME (entry, exit) date
    pairs the strategy's own realized returns use (old repo Fix 2: first
    benchmark return date == first strategy return date - satisfied by
    construction here, not just by a regression test). Raises
    `BacktestAbortError` if the benchmark is missing a price on any fill
    date - "a failure of the benchmark ... aborts the run with a clear
    error".

    M04b work packet item 5 ("Benchmark computation reads from the store,
    no giant context"): this used to build ONE `PITDataContext` with
    `lookback_days` sized to the ENTIRE run's trading-session count (a
    single call spanning the whole run, deliberately - one fetch instead of
    one per fill date) - which `PITDataContext._sliced_price_panel`'s own
    calendar-day buffer then roughly DOUBLED, so a real 2012-2026 run
    requested a window reaching back to ~2006. Before this milestone pinned
    `core/calendar.py`'s bounds, that raised `DateOutOfBounds` outright (the
    crash plans/M04b-engine-perf.md profiles); even with pinned bounds, a
    request that wide would have missed the panel store's own (deliberately
    tight - see `run_backtest`'s sizing) preloaded window and fallen back to
    a live, whole-history re-fetch for the benchmark ticker. Reading a plain
    [fill_dates[0], fill_dates[-1]] date-range slice directly from the store
    avoids the giant lookback-count arithmetic entirely - it needs exactly
    the dates this function already knows it wants, no more - while still
    being ONE call, not one per fill date. Still untrusted like any other
    store/provider access in this module: `_assert_no_lookahead` below
    mirrors data/pit.py's own hard-slice-then-assert discipline for this,
    the one price access in this file that does not go through a
    `PITDataContext` at all (this is realized, already-past accounting
    bookkeeping over KNOWN historical fill dates, never a strategy decision -
    see this module's own docstring's "Two parallel tracks" section)."""
    raw = panel_store.get_prices([benchmark], fill_dates[0], fill_dates[-1])
    raw = raw[raw["ticker"] == benchmark]
    violations = raw.index[raw.index > fill_dates[-1]]
    if len(violations) > 0:
        raise LookaheadError(
            f"_benchmark_returns: {len(violations)} row(s) for {benchmark!r} dated after "
            f"the last fill date {fill_dates[-1].date()} (first violation: "
            f"{violations.min().date()})"
        )
    prices: dict[pd.Timestamp, float] = {}
    for d in fill_dates:
        row = raw.loc[raw.index == d]
        if row.empty:
            raise BacktestAbortError(f"benchmark {benchmark!r} has no price data on {d.date()}")
        prices[d] = float(row["adj_close"].iloc[0])

    returns = {
        fill_dates[i + 1]: prices[fill_dates[i + 1]] / prices[fill_dates[i]] - 1.0
        for i in range(len(fill_dates) - 1)
    }
    return pd.Series(returns, dtype=float).sort_index()


# -- run-level stores (M04b work packet item 4) ------------------------------


def _full_universe_from_history(universe_history: pd.DataFrame) -> set[str]:
    """Every ticker that appears in ANY row of `membership_history`'s
    `tickers` column - i.e. every point-in-time constituent over the whole
    window that history spans, not just the current/latest membership. Used
    to size the run-level `PricePanelStore`'s preload (a superset of every
    ticker `ctx.universe()` could ever hand a strategy is sufficient; a
    ticker this misses for some reason - e.g. a membership change recorded
    strictly before the queried window - still works correctly, just via
    `PricePanelStore`'s per-ticker provider fallback rather than the
    in-memory fast path)."""
    if "tickers" not in universe_history.columns:
        return set()
    tickers: set[str] = set()
    for members in universe_history["tickers"]:
        tickers.update(members)
    return tickers


def _panel_store_warmup_start(config_start: pd.Timestamp, max_lookback_days: int) -> pd.Timestamp:
    """The run-level panel store's own preload window start: exactly
    `max_lookback_days` TRADING sessions before `config_start` (mirroring
    `PITDataContext._sliced_price_panel`'s own SESSION-COUNT-based window,
    not a padded calendar-day buffer), clamped to the calendar's pinned
    first session (`core/calendar.py`).

    Sizing this by trading SESSIONS rather than a generous calendar-day
    multiplier matters in practice, not just in theory: a shared prefetched
    price cache's sidecar metadata records the EXACT range it was populated
    for (data/cache.py's `write_price_cache_meta`), and requesting further
    back than that - even by a seemingly modest calendar-day margin - reads
    as a WIDER request than the cache covers, silently falling back to a
    live re-fetch for the ENTIRE preloaded universe on this store's very
    first build call. That is the opposite of this milestone's point, and
    was confirmed against the real shared cache during development (its
    metadata was fetched for exactly [2010-06-01, 2026-09-11]; the momentum
    strategy's own ~368-trading-session lookback lands at 2010-08-17 from a
    2012-01-31 first rebalance - safely inside that window - while even a
    modest calendar-day-multiplier version of this same calculation lands
    outside it and would have triggered exactly the mass re-fetch this
    function exists to avoid)."""
    if max_lookback_days <= 0:
        return calendar_first_session()
    prior_sessions = trading_days(calendar_first_session(), config_start)
    if len(prior_sessions) > max_lookback_days:
        return prior_sessions[-max_lookback_days]
    return calendar_first_session()


def _build_panel_store(
    providers: BacktestProviders,
    config: BacktestConfig,
    requirements: DataRequirements,
    universe_history: pd.DataFrame,
) -> PricePanelStore:
    """Build the run-level `PricePanelStore` covering every point-in-time
    universe member (plus the benchmark) over the whole backtest window -
    see this module's docstring and `panel_store.py`'s own docstring."""
    max_lookback_days = max(
        requirements.price_lookback_days,
        _LAST_PRICE_SEARCH_LOOKBACK_DAYS,
        config.corwin_schultz_lookback_days,
        1,
    )
    warmup_start = _panel_store_warmup_start(config.start, max_lookback_days)
    # A small pad past `config.end`: `next_open` execution's final fill date
    # is one session AFTER the last rebalance date, which can fall a few
    # calendar days past `config.end` itself.
    store_end = config.end + pd.Timedelta(days=10)
    tickers = sorted(_full_universe_from_history(universe_history) | {config.benchmark})
    return PricePanelStore.build(providers.price, tickers, warmup_start, store_end)


def _build_actions_store(
    providers: BacktestProviders, tickers: set[str], end: pd.Timestamp
) -> dict[str, pd.DataFrame]:
    """Best-effort run-level actions pre-fetch (M04b work packet item 4):
    each ticker's full actions history through the run's END date, fetched
    ONCE via the provider (itself cache-backed - a disk hit past the first
    fetch, but still real per-call I/O plus a staleness re-check) rather
    than being re-fetched by every fresh `PITDataContext` at every
    rebalance that touches it (data/pit.py's `_gated_actions_by_ticker` -
    its OWN per-context memoisation, unaffected by this, only covers ONE
    context's lifetime, i.e. one rebalance).

    A ticker whose fetch fails (`StaleActionsCacheError`/`ActionsFetchError`)
    is simply left OUT of the store: `_gated_actions_by_ticker`'s existing
    fallback then calls the provider directly for it, at whatever `asof`
    actually needs it, preserving the EXACT per-rebalance staleness/failure
    semantics `_FilteringConstituentsProvider` (and the M02b/M03b staleness
    contract) already depend on - a failure fetching through `end` must
    never be silently treated as "this ticker is unusable for the whole
    run", since an EARLIER `asof` might not be stale at all. Never retried
    here; this is a best-effort perf pre-fetch, not a new failure policy."""
    store: dict[str, pd.DataFrame] = {}
    for ticker in sorted(tickers):
        try:
            store[ticker] = providers.corporate_actions.get_actions(ticker, _EPOCH, end)
        except (StaleActionsCacheError, ActionsFetchError):
            continue
    return store


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


def _git_dirty() -> bool | None:
    """Whether `git status --porcelain` in the repo root was non-empty at
    run time (M04 verdict carried item, plans/QUANT-NOTES.md: M04 itself ran
    from an uncommitted working tree, so `quantlab_git_sha` alone named a
    commit that did NOT contain the code that actually produced the result -
    M06's trials registry needs this to avoid keying a trial to the wrong
    code). `None` - never a silent `False` - when git itself is unavailable
    or errors; `run_backtest` adds a `known_caveats` note in that case so a
    missing signal is never misread as "clean"."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=_repo_root(),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0:
            return bool(result.stdout.strip())
    except OSError:
        pass
    return None


# -- the engine ---------------------------------------------------------------


def run_backtest(
    strategy: Strategy, config: BacktestConfig, providers: BacktestProviders
) -> BacktestResult:
    _run_start = time.perf_counter()  # provenance.run_seconds, M04b work packet item 6
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

    # M04b work packet item 4: run-level stores, built ONCE before the
    # rebalance loop starts. `universe_history` is computed here (rather
    # than at the bottom of this function, where a pre-M04b version of this
    # code computed it again for `coverage_gap` below) so BOTH the panel
    # store's sizing and the final coverage report reuse the identical
    # single call to `membership_history` - see `_build_panel_store`.
    universe_history = providers.constituents.membership_history(config.start, config.end)
    panel_store = _build_panel_store(providers, config, requirements, universe_history)
    actions_store = _build_actions_store(
        providers, _full_universe_from_history(universe_history), config.end
    )

    asof_box: dict[str, pd.Timestamp] = {"value": reb_dates[0]}

    decision_providers = DecisionProviders(
        price=providers.price,
        constituents=providers.constituents,
        fundamentals=providers.fundamentals,
        corporate_actions=providers.corporate_actions,
    )

    def context_factory(reqs: DataRequirements) -> PITDataContext:
        asof = asof_box["value"]

        def _on_drop(ticker: str, exc: Exception, _asof=asof) -> None:
            dropped_tickers_by_date.setdefault(str(_asof.date()), []).append(ticker)

        # `accounting` omitted (defaults False, data/pit.py): this is the
        # DECISION-path context - the only one a strategy, or a blend
        # child via `set_context_factory`, ever receives. Calling
        # `prices_for_returns()` on it now raises `UndeclaredDataError` by
        # construction (M04 HANDOFF.3 follow-up to quant-gate VERDICT.md).
        # `build_decision_context` (backtest/context.py, quant-gate
        # VERDICT.md M08 cycle-1 finding 2) is now the ONE shared builder
        # `paper/runner.py` also calls - the filtering wrapper and its
        # `max_dropped_fraction` abort policy can no longer silently diverge
        # between the two callers.
        return build_decision_context(
            asof=asof,
            requirements=reqs,
            providers=decision_providers,
            max_dropped_fraction=config.max_dropped_fraction,
            on_drop=_on_drop,
            panel_store=panel_store,
            actions_store=actions_store,
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
        exact = _rows_at_exact_session(providers, sorted(prior_weights), fill_date, panel_store)
        for ticker in prior_weights:
            row = exact.get(ticker)
            entry_return = prior_return_prices[ticker]
            is_forced_exit = row is None
            if is_forced_exit:
                entry_fill = prior_fill_prices[ticker]
                last = _last_available_row(providers, ticker, fill_date, panel_store)
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

        # quant-gate VERDICT.md cycle 1 finding 3 (BLOCKING): read ONLY
        # `TargetWeights.unscored` - names the STRATEGY ITSELF says it tried
        # to score and could not (core/types.py) - never infer "unscored"
        # from `declared universe - weights.keys()`, which conflates a
        # genuinely unscoreable name with one merely not selected into a
        # top-N book (measured at the gate: ~473 of ~500 names on a real
        # 30-name momentum book, useless as a data-quality signal). A
        # record-and-hold-prior `targets` (built above, not by the strategy)
        # has no strategy-reported `unscored` at all - correctly empty,
        # since nothing was actually attempted that rebalance.
        if targets.unscored:
            unscored_by_date[str(t.date())] = sorted(targets.unscored)

        holdings_history[t] = targets
        all_encountered_tickers.update(targets.weights)
        all_encountered_tickers.update(prior_weights)

        # -- entry prices for the new target book ----------------------------
        needed = sorted(set(targets.weights) - set(mark_prices))
        fresh = _rows_at_exact_session(providers, needed, fill_date, panel_store) if needed else {}
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
                providers, names, fill_date, config.corwin_schultz_lookback_days, panel_store
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

    benchmark_returns_s = _benchmark_returns(panel_store, config.benchmark, fill_dates)
    benchmark_equity = _equity_with_start(benchmark_returns_s, reb_dates[0])

    # `universe_history` was already fetched once, before the rebalance loop
    # (M04b work packet item 4 - see the panel/actions store setup above);
    # reused here rather than calling `membership_history` a second time.
    # quant-gate VERDICT.md finding 1: coverage over the UNIVERSE the
    # strategy could see (falls back to held names for a strategy that
    # never declares `needs_universe` at all, the best available proxy).
    coverage_tickers = all_universe_tickers | all_encountered_tickers
    # M04b quant-gate cycle-2 review: membership START dates need the FULL
    # membership record (from the epoch), not `universe_history` above
    # (bounded to [config.start, config.end]) - a ticker that joined the
    # index well before this run's own window would otherwise look like it
    # "joined" at whatever date first happens to fall inside the window.
    full_membership_history = providers.constituents.membership_history(_EPOCH, config.end)
    membership_starts = membership_start_by_ticker(full_membership_history)
    price_availability = price_availability_from_cache(
        sorted(coverage_tickers), providers.cache_dir, membership_starts
    )
    report = coverage_gap(
        universe_history, price_availability, config.start, config.end, sample_dates=reb_dates
    )
    # M04b quant-gate VERDICT.md cycle 1 finding 2: provenance records the
    # quarantined count and ticker list for this run - a quarantined
    # ticker's data-quality issue is otherwise invisible outside
    # `coverage_report.quarantined_tickers`'s per-year breakdown.
    quarantined_tickers = sorted(t for t, av in price_availability.items() if av.quarantined)
    # M04b quant-gate cycle-2 review: tickers whose EARLY, pre-cache
    # membership span is masked (`PriceAvailability.masked_start`) AND that
    # masking actually falls within THIS backtest's own [start, end] window -
    # read from `report.masked_start_tickers` (per-year), NOT from a raw
    # "avail.masked_start is not None" count. The two differ hugely in
    # practice: this shared cache's prefetch floor (2010-06-01) predates
    # nearly every long-standing constituent's OWN index-membership start
    # (IBM since 1996, etc.), so `masked_start` is technically populated for
    # ~300 completely healthy, non-quarantined tickers whose gap is entirely
    # BEFORE any window this backtest ever queries - a benign, pre-existing
    # fact about the shared cache's own scope, not a symbol-reuse finding,
    # and reporting that raw count as "quarantined as new listings" would be
    # false. The per-year breakdown already excludes exactly these
    # never-actually-queried gaps (see `coverage_gap`'s `year_end <
    # avail.masked_start` condition).
    masked_start_tickers = sorted(
        {t for names in report.masked_start_tickers.values() for t in names}
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

    git_dirty = _git_dirty()

    known_caveats = []
    if "ttm_eps" in requirements.fundamental_fields:
        known_caveats.append(_TTM_EPS_CAVEAT)
    if git_dirty is None:
        known_caveats.append(
            "provenance.dirty could not be determined (git unavailable, or `git status "
            "--porcelain` errored, in the repo root) - quantlab_git_sha alone cannot be "
            "trusted to name the exact code that produced this result."
        )
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
    if masked_start_tickers:
        known_caveats.append(
            f"{len(masked_start_tickers)} point-in-time constituent(s) had already joined "
            "the index before this run's cached price history for them begins, within this "
            "run's own [start, end] window - their early membership span is invisible to "
            "every strategy (PriceAvailability.masked_start; counted in the coverage bound "
            "above, not a second, separate deduction) - see coverage_report."
            "masked_start_tickers for the per-year breakdown and per-ticker reasons."
        )
    if quarantined_tickers:
        known_caveats.append(
            f"Yahoo symbol reuse erases delisted history; {len(quarantined_tickers)} "
            "historical constituent(s) in this run's tracked universe were quarantined "
            "because their cached price series belongs to a DIFFERENT, later company now "
            "trading under the same symbol (data/quality.py's scan_price_cache) - see "
            "provenance.quarantined_tickers."
        )

    fetched_at = actions_fetched_at(providers.cache_dir, all_encountered_tickers)
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
        # M04b work packet item 7 (orchestrator-added, folded in mid-loop):
        # whether the working tree was dirty at RUN time - see `_git_dirty`'s
        # docstring. `None` (git unavailable/errored) is surfaced as a
        # `known_caveats` note above, never silently read as "clean".
        "dirty": git_dirty,
        "run_timestamp": pd.Timestamp.now("UTC").isoformat(),
        "data_semantics_version": DATA_SEMANTICS_VERSION,
        "known_caveats": known_caveats,
        # M04b quant-gate VERDICT.md cycle 1 finding 2: how many, and which,
        # tickers this run's coverage-tracked universe had quarantined by
        # the quality scan (data/quality.py's scan_price_cache) - see
        # coverage_report.quarantined_tickers for the per-year breakdown.
        "quarantined_count": len(quarantined_tickers),
        "quarantined_tickers": quarantined_tickers,
        "masked_start_count": len(masked_start_tickers),
        "masked_start_tickers": masked_start_tickers,
        # M04b work packet item 6: wall-clock seconds for this ENTIRE
        # `run_backtest` call, measured from its very first line - the
        # acceptance-criterion timing number belongs in the artifact a real
        # run actually produces, not just in a human-typed handoff note.
        "run_seconds": time.perf_counter() - _run_start,
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
