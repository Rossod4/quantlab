"""`run_once`: one scheduled paper-trading cycle for one strategy against one
`Broker`. `accept_broker_state`: the explicit, human-approved re-baseline
path (see finding 1 below).

Mirrors `backtest/engine.py`'s decision-path context construction EXACTLY -
via the SAME shared `backtest.context.build_decision_context` the engine
itself now calls (quant-gate VERDICT.md M08 cycle-1 finding 2) - and adds
everything a live schedule needs on top: an as-of date that is never today's
still-open session, the M02b/M04-carried actions-cache refresh policy, the
report-card promotion gate, reconciliation against the journal's own
(corporate-action-aware) expectation, order planning/submission with a
forced-exit and partial-fill policy, and the journal record itself.

## `asof` resolution (canary (k), tests/canaries/test_lookahead.py)

`resolve_asof` never returns `today` itself, REGARDLESS of what a caller
passes as `asof`: this platform has no intraday clock (CLAUDE.md - dates are
day-granular), so there is no way to know from a date alone whether "today"'s
session has actually closed - a scheduled task firing early, or a
mis-configured `--asof today`, must never let the runner decide as of a
session that might still be open. `prev_trading_day(today)` is therefore an
unconditional ceiling: the default (`asof=None`) IS exactly that ceiling, and
an explicit `asof` is clamped down to it if it would exceed it. Separately,
`asof` is also clamped to the most recent bar the price cache ACTUALLY has
for the platform's benchmark ticker (`_cached_data_ceiling`) - a lagging or
partially-failed overnight data sync must not let the runner pretend it can
see a session the data layer does not actually have yet.

## Actions-cache refresh policy (QUANT-NOTES M02b/M04 carried item; quant-gate
## VERDICT.2.md M08 cycle-2 finding 1)

`data/corporate_actions.py`'s actions cache is fetch-once-forever and raises
`StaleActionsCacheError` once `asof` advances past its `fetched_at` (see that
module's docstring). A backtest never hits this in practice (its `asof`
values are all in the past, at or before the cache's own fetch time); a
LIVE/PAPER runner's `asof` advances every single scheduled run, so it WILL
eventually go stale. `refresh_actions_cache()` (that module) is the only way
to clear it and, before this milestone, had "no operational caller" anywhere
in the product (plans/QUANT-NOTES.md).

The policy is **PROACTIVE**, matching the work packet's own wording
verbatim ("call `refresh_actions_cache` for the universe when `fetched_at <
asof`, log it" - plans/M08-paper-trading.md): BEFORE the decision context is
even built, `_proactive_actions_refresh` reads each candidate ticker's
`fetched_at` sidecar directly (`backtest.context.actions_fetched_at`, the
SAME helper `backtest/engine.py`'s own provenance section uses) for the
strategy's declared universe (if `needs_universe`) AND every currently held
ticker, and force-refreshes any whose cache is missing or stale. This
matters because `build_decision_context`'s shared filtering provider
(finding 2, below) converts a `StaleActionsCacheError` into a silent DROP
rather than letting it escape as an exception - a REACTIVE catch-and-retry
alone (the cycle-1 implementation) can never see a staleness the filter
absorbed first, so it never ran for any strategy declaration shape this
platform actually ships. `_generate_targets_with_actions_refresh`'s
reactive catch-and-retry is kept as a SECOND line (a staleness the
proactive pass somehow missed, or newly introduced between that pass and
`generate_targets`, is still caught there) - a SECOND failure after both
lines is journaled as a refusal (naming the exception class) and re-raised
uncaught, never looped. A ticker whose refresh itself fails
(`ActionsFetchError`) is left as-is; the filter's own drop-and-count policy
then handles it as a genuine data failure, exactly as it should.

## Data-degradation policy (quant-gate VERDICT.md M08 cycle-1 finding 2)

`build_decision_context` (backtest/context.py) wraps the constituents
provider in the SAME per-ticker filtering the backtest engine uses whenever
a strategy declares `needs_universe` alongside a price/fundamentals need,
dropping (and journaling) any ticker whose actions probe fails and aborting
via `BacktestAbortError` past `PaperRunConfig.max_dropped_fraction` - a
paper run degrades on bad data EXACTLY like a backtest would, rather than
either stopping on routine single-ticker failures (the pre-cycle-2 behavior)
or silently sizing a concentrated book on a half-completed data sync.
`PaperRunConfig.abort_on_unscoreable` (default `True`, matching
`BacktestConfig`'s own default) governs a strategy-raised `ValueError`
("unscoreable"): `True` refuses and journals; `False` records a
record-and-hold-prior cycle (no orders planned) with the reason in
`known_caveats`, mirroring the engine's own tolerant policy.

## Forced exits and partial fills (findings 3 and 4)

A currently-held ticker missing from this run's price fetch (a delisted or
otherwise unpriceable name) is forced to a zero target REGARDLESS of what
the strategy declared - CLAUDE.md invariant #3's paper-side counterpart -
and journaled under `forced_exits`; `paper/rebalancer.py`'s `plan_orders`
needs no price at all to size a full exit to zero. Every cycle cancels any
resting order left open by a prior cycle BEFORE planning
(`PaperRunConfig.cancel_open_before_plan`, default `True`) and journals the
cancellations, then plans under a fresh `client_order_id` `attempt` number
so a still-needed remainder is resubmitted as a genuinely NEW order rather
than replaying (and, per `paper/mock.py`/`paper/alpaca.py`'s own fix,
never being MISREPORTED as) an already-settled fill.

## Reconciliation (finding 1)

The prior traded (or rebaselined) run's `account_after` is rolled forward
through any dividend/split with ex-date between that run's `asof` and this
one (`paper/reconcile.py`'s `roll_forward_expected`) BEFORE comparison, so
an ordinary corporate action is explained rather than bricking the schedule
forever. `accept_broker_state` is the explicit, journaled, human-approved
escape hatch for a mismatch this cannot explain."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from quantlab.backtest.context import DecisionProviders, actions_fetched_at, build_decision_context
from quantlab.backtest.engine import BacktestProviders, build_backtest_providers
from quantlab.core.calendar import next_trading_day, prev_trading_day
from quantlab.core.config import PlatformConfig
from quantlab.core.errors import (
    ActionsFetchError,
    BacktestAbortError,
    PromotionGateError,
    ReconcileError,
    StaleActionsCacheError,
)
from quantlab.core.semantics import DATA_SEMANTICS_VERSION
from quantlab.core.types import TargetWeights, normalize_timestamp
from quantlab.data.corporate_actions import refresh_actions_cache
from quantlab.data.requirements import DataRequirements
from quantlab.paper.broker import AccountSnapshot, Broker
from quantlab.paper.journal import JournalRecord, append_journal, read_journal
from quantlab.paper.rebalancer import RebalancerConfig, plan_orders
from quantlab.paper.reconcile import (
    ReconcileTolerances,
    build_reconcile_report,
    roll_forward_expected,
)
from quantlab.strategies.base import Strategy
from quantlab.strategies.registry import load_strategy


@dataclass(frozen=True)
class PaperRunConfig:
    """Paper-side counterparts of `backtest.config.BacktestConfig`'s own
    data-degradation fields, same names and same defaults (quant-gate
    VERDICT.md M08 cycle-1 finding 2 - "config shared with BacktestConfig"):
    a paper run degrades on bad data exactly like a backtest would, under
    the identical thresholds. `cancel_open_before_plan` (finding 4, no
    `BacktestConfig` counterpart - a backtest has no persistent broker state
    across calls) defaults `True`.

    **Setting `cancel_open_before_plan=False` is a footgun** (quant-gate
    VERDICT.2.md M08 cycle-2 non-blocking item): `client_order_id_for`'s
    `attempt` suffix is what lets a later cycle top up a partial fill
    safely, and it is CANCELING the prior attempt's resting remainder that
    stops that same cycle from ALSO stacking a brand-new order on top of a
    still-resting first one - with cancellation skipped, a cycle that finds
    drift because a resting order hasn't filled yet will plan and submit a
    SECOND live order for the same gap, and both can eventually fill,
    over-executing the rebalance. Only disable this for a broker/workflow
    where you have your own reason to believe resting orders are otherwise
    accounted for."""

    max_dropped_fraction: float = 0.05
    abort_on_unscoreable: bool = True
    cancel_open_before_plan: bool = True


def _today() -> pd.Timestamp:
    """Module-level, like `data/corporate_actions.py`'s own `_today` - tests
    monkeypatch this directly for determinism (CLAUDE.md invariant #5)."""
    return normalize_timestamp(pd.Timestamp.now())


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


def _cached_data_ceiling(
    providers: BacktestProviders, benchmark: str, today: pd.Timestamp
) -> pd.Timestamp | None:
    """The most recent bar the price cache actually has for `benchmark`, at
    or before `today` - `None` if the provider has nothing at all (never
    raises; a cold/empty cache just means no additional ceiling applies
    here, since `PITDataContext` itself will surface the resulting empty
    panel through its own, already-tested empty-history handling)."""
    window_start = today - pd.Timedelta(days=20)
    try:
        panel = providers.price.get_prices([benchmark], window_start, today)
    except Exception:  # noqa: BLE001 - a ceiling probe must never crash the run
        return None
    if panel.empty:
        return None
    return pd.Timestamp(panel.index.max())


def resolve_asof(
    today: pd.Timestamp,
    requested_asof: object | None,
    providers: BacktestProviders,
    benchmark: str,
) -> pd.Timestamp:
    """See module docstring's "`asof` resolution" section."""
    safety_ceiling = prev_trading_day(today)
    candidate = (
        normalize_timestamp(requested_asof) if requested_asof is not None else safety_ceiling
    )
    if candidate > safety_ceiling:
        candidate = safety_ceiling
    ceiling = _cached_data_ceiling(providers, benchmark, today)
    if ceiling is not None and candidate > ceiling:
        candidate = ceiling
    return candidate


def _proactive_actions_refresh(
    strategy: Strategy,
    providers: BacktestProviders,
    broker: Broker,
    asof: pd.Timestamp,
    cache_dir: Path,
) -> list[str]:
    """BEFORE the decision context is built: read the `fetched_at` sidecar
    directly (`backtest.context.actions_fetched_at`) for the strategy's
    declared universe (if `needs_universe`) AND every currently held ticker,
    and force-refresh any whose cache is missing or stale relative to
    `asof` - see module docstring's "Actions-cache refresh policy" section
    for why this must be PROACTIVE (quant-gate VERDICT.2.md M08 cycle-2
    finding 1): the shared filtering provider (finding 2) converts a
    `StaleActionsCacheError` into a silent drop, so a reactive
    catch-and-retry can never see the staleness once that filter is active
    - which it is for every shipped strategy declaration shape.

    Held tickers are included even when the strategy's OWN universe
    declaration would no longer surface them (VERDICT.2.md finding 4's
    caveat: a held name a strategy has quietly dropped must still be
    refreshable so `roll_forward_expected`'s reconcile step is not
    routinely starved of fresh actions data). Never raises: a failure
    discovering candidates (a broken `membership()`/`account()` call) is
    swallowed here - the real decision/reconcile paths surface such a
    failure properly on their own with a specific reason; this is a
    best-effort pre-pass, not a second place for that failure to be
    reported. A ticker whose refresh itself fails (`ActionsFetchError`) is
    simply left un-refreshed - the shared filter's own drop-and-count
    policy (or the reconcile step's own per-ticker fallback) handles it
    from there, exactly as a genuine data failure should.

    Returns the tickers actually refreshed, for
    `JournalRecord.refreshed_actions_tickers`."""
    requirements = strategy.requires()
    candidates: set[str] = set()
    if requirements.needs_universe:
        try:
            candidates.update(providers.constituents.membership(asof))
        except Exception:  # noqa: BLE001 - best-effort candidate discovery only
            pass
    try:
        candidates.update(broker.account().positions)
    except Exception:  # noqa: BLE001 - _refuse's own guarded account() call handles this
        pass

    if not candidates:
        return []

    fetched_at_raw = actions_fetched_at(cache_dir, candidates)
    refreshed: list[str] = []
    for ticker in sorted(candidates):
        raw = fetched_at_raw.get(ticker)
        fetched_at = normalize_timestamp(raw) if raw is not None else None
        if fetched_at is None or asof > fetched_at:
            try:
                refresh_actions_cache(ticker, cache_dir)
                refreshed.append(ticker)
            except ActionsFetchError:
                continue
    return refreshed


def _generate_targets_with_actions_refresh(
    strategy: Strategy,
    context_factory,
    providers: BacktestProviders,
    asof: pd.Timestamp,
    cache_dir: Path,
) -> tuple[TargetWeights, list[str]]:
    """Call `strategy.generate_targets` against a context built by
    `context_factory` (the SAME closure passed to `strategy.
    set_context_factory` - see `run_once` - so a blend child gets an
    identically-filtered, per-child context, not a fallback union one); on
    `StaleActionsCacheError`, apply the actions-cache refresh policy (see
    module docstring) once and retry. Returns `(targets, refreshed_tickers)`.
    Any OTHER exception (including a second `StaleActionsCacheError`,
    `ActionsFetchError`, or `BacktestAbortError` from the shared
    data-degradation guard) propagates uncaught - `run_once` journals it."""
    requirements = strategy.requires()
    try:
        ctx = context_factory(requirements)
        return strategy.generate_targets(ctx, asof), []
    except StaleActionsCacheError:
        universe: list[str] = []
        if requirements.needs_universe:
            universe = sorted(providers.constituents.membership(asof))
        refreshed: list[str] = []
        for ticker in universe:
            try:
                refresh_actions_cache(ticker, cache_dir)
                refreshed.append(ticker)
            except ActionsFetchError:
                continue
        ctx = context_factory(requirements)
        targets = strategy.generate_targets(ctx, asof)
        return targets, refreshed


def _last_prices_with_dates(
    providers: BacktestProviders, tickers: list[str], asof: pd.Timestamp
) -> tuple[dict[str, float], dict[str, str]]:
    """The most recent RAW (not as-of-adjusted) traded close for each
    ticker, on or before `asof`, plus the ISO date of the bar actually used
    (carried, non-blocking item: M09 needs a per-ticker data-asof, not just
    the benchmark-only staleness ceiling, to tell a stale bar from a signal
    move) - this is order-execution sizing, not a strategy signal, so it
    goes straight to the raw price provider rather than through a
    `PITDataContext` (mirrors how `backtest/engine.py`'s own accounting-path
    fill lookups bypass the decision-path accessor)."""
    if not tickers:
        return {}, {}
    window_start = asof - pd.Timedelta(days=20)
    panel = providers.price.get_prices(sorted(set(tickers)), window_start, asof)
    panel = panel.loc[panel.index <= asof]
    prices: dict[str, float] = {}
    dates: dict[str, str] = {}
    for ticker in tickers:
        sub = panel[panel["ticker"] == ticker]
        if not sub.empty:
            prices[ticker] = float(sub["close"].iloc[-1])
            dates[ticker] = str(pd.Timestamp(sub.index[-1]).date())
    return prices, dates


def _result_to_json(result) -> dict:
    """`Fill` (pydantic, `model_dump`) or `OrderAck` (dataclass, `to_json`) -
    `Broker.submit()`'s return type is a union of the two (paper/broker.py)."""
    if hasattr(result, "model_dump"):
        return result.model_dump(mode="json")
    return result.to_json()


def find_promoting_report_card(
    reports_dir: str | Path, strategy_id: str, data_semantics_version: str
) -> tuple[Path, dict] | None:
    """Search `reports_dir` (recursively - `quantlab validate --full` writes
    `report_card.json` under whatever `--out` directory the caller chose,
    not a fixed path this function could guess) for a report card matching
    BOTH `strategy_id` and `data_semantics_version` with verdict
    `ELIGIBLE_FOR_PAPER`. Returns the MOST RECENTLY MODIFIED matching file
    (and its parsed content) if more than one qualifies, or `None` if none
    do. A malformed/unreadable `report_card.json` is skipped, not fatal -
    this is a best-effort search over a directory tree the runner does not
    own the contents of."""
    import json

    reports_dir = Path(reports_dir)
    if not reports_dir.exists():
        return None

    candidates: list[tuple[Path, dict]] = []
    for path in reports_dir.rglob("report_card.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        provenance = data.get("provenance") or {}
        if (
            data.get("verdict") == "ELIGIBLE_FOR_PAPER"
            and provenance.get("strategy_id") == strategy_id
            and provenance.get("data_semantics_version") == data_semantics_version
        ):
            candidates.append((path, data))

    if not candidates:
        return None
    candidates.sort(key=lambda pc: pc[0].stat().st_mtime)
    return candidates[-1]


def _next_attempt_number(reports_dir: str | Path, strategy_id: str, asof: pd.Timestamp) -> int:
    """1 + the number of prior TRADING-cycle journal records (`kind="run"`,
    `refused_reason is None`) already recorded for this exact `asof` - see
    `paper/broker.py`'s `client_order_id_for` `attempt` parameter and
    finding 4's module docstring section. A REFUSED record (this cycle
    never reached `plan_orders`/`broker.submit`, so nothing was ever
    attempted at the broker under any id) does not burn an attempt number
    (quant-gate VERDICT.2.md M08 cycle-2 non-blocking item) - only a record
    that actually reached planning/submission counts."""
    asof_str = str(asof.date())
    records = read_journal(reports_dir, strategy_id)
    return 1 + sum(
        1
        for r in records
        if r.get("asof") == asof_str
        and r.get("kind", "run") == "run"
        and r.get("refused_reason") is None
    )


def _open_orders_to_json(broker: Broker) -> list[dict]:
    """`broker.open_orders()` as `[{"client_order_id", "ticker", "qty"}, ...]`
    - finding 4's "after submit, call open_orders(); journal resting
    remainders"."""
    return [
        {"client_order_id": o.client_order_id, "ticker": o.ticker, "qty": o.qty}
        for o in broker.open_orders()
    ]


def _cancel_resting_orders(broker: Broker) -> list[dict]:
    """Cancel every order `broker.open_orders()` reports, returning
    `[{"client_order_id", "ticker", "qty"}, ...]` for the journal (finding
    4's `cancel_open_before_plan` policy)."""
    canceled = []
    for order in broker.open_orders():
        broker.cancel(order.client_order_id)
        canceled.append(
            {"client_order_id": order.client_order_id, "ticker": order.ticker, "qty": order.qty}
        )
    return canceled


def _last_traded_or_rebaselined_record(prior_records: list[dict]) -> dict | None:
    """The most recent journal record (`kind` "run" or "rebaseline") whose
    `refused_reason is None` - a refusal never becomes the reconcile
    baseline (that was cycle-1's bug); an explicit re-baseline (finding 1)
    always qualifies, since `accept_broker_state` never sets a refusal."""
    return next((r for r in reversed(prior_records) if r.get("refused_reason") is None), None)


def run_once(
    strategy_config: str | Path | dict,
    platform_config: PlatformConfig,
    broker: Broker,
    *,
    asof: object | None = None,
    rebalancer_config: RebalancerConfig | None = None,
    reconcile_tolerances: ReconcileTolerances | None = None,
    force_research: bool = False,
    paper_config: PaperRunConfig | None = None,
) -> JournalRecord:
    """Run one paper-trading cycle. See module docstring for the full
    sequence. Always appends exactly one `JournalRecord` (including on a
    refusal) before returning or raising. This is a STRUCTURAL guarantee
    (quant-gate VERDICT.md M08 cycle-2 finding 1, following up on cycle-1
    finding 3): everything below the point the run's identity
    (`strategy`/`effective_asof`/`git_sha`/`dirty`) is known runs inside ONE
    outer `try`/`except Exception`, not an enumerated list of "the
    exception types we thought of" - a strategy bug
    (`UndeclaredDataError`, `LookaheadError`, or anything else
    `generate_targets` raises, including via a blend child's own guard) is
    journaled exactly like a data-provider condition, never a silent
    zero-record crash. The specific inner handlers below (promotion gate,
    actions-cache exhaustion, data degradation, unscoreable, reconcile,
    planning/submission) still fire first with a MORE SPECIFIC reason and
    their own typed exception, marking `already_journaled` so the outer
    catch-all never double-records a failure an inner handler already
    wrote; the outer catch is the safety net behind all of them, not a
    replacement. `stage` names where in the cycle an unhandled exception
    was caught (`"promotion_gate"`, `"context"`, `"targets"`, `"reconcile"`,
    `"plan"`, `"submit"`) for whoever reads the journal."""
    strategy = load_strategy(strategy_config)
    providers = build_backtest_providers(platform_config)
    paper_cfg = paper_config or PaperRunConfig()
    today = _today()
    effective_asof = resolve_asof(today, asof, providers, platform_config.benchmark)

    git_sha = _git_sha()
    dirty = _git_dirty()

    stage = "promotion_gate"
    dropped_tickers: list[str] = []
    known_caveats: list[str] = []
    promoting_path: str | None = None
    targets: TargetWeights | None = None
    refreshed_tickers: list[str] = []
    reconcile_report = None
    canceled_orders: list[dict] = []
    forced_exits: dict[str, str] = {}
    price_asof_by_ticker: dict[str, str] = {}
    already_journaled = False

    def _on_drop(ticker: str, exc: Exception) -> None:
        dropped_tickers.append(ticker)

    decision_providers = DecisionProviders(
        price=providers.price,
        constituents=providers.constituents,
        fundamentals=providers.fundamentals,
        corporate_actions=providers.corporate_actions,
    )

    def context_factory(reqs: DataRequirements):
        return build_decision_context(
            asof=effective_asof,
            requirements=reqs,
            providers=decision_providers,
            max_dropped_fraction=paper_cfg.max_dropped_fraction,
            on_drop=_on_drop,
        )

    def _dropped_fraction() -> float | None:
        requirements = strategy.requires()
        if not requirements.needs_universe or not dropped_tickers:
            return 0.0 if requirements.needs_universe else None
        try:
            raw = providers.constituents.membership(effective_asof)
        except Exception:  # noqa: BLE001 - reporting-only probe, never fatal
            return None
        return len(dropped_tickers) / len(raw) if raw else None

    def _refuse(reason: str, known_caveats: list[str], **extra) -> JournalRecord:
        nonlocal already_journaled
        # quant-gate VERDICT.2.md M08 cycle-2 finding 2: `_refuse` itself
        # must never be the reason a run leaves zero records - an
        # unreachable/unauthenticated broker (an expired key, an API
        # outage, a network failure on a scheduled unattended run) is the
        # single most likely real-world failure, and it must not crash the
        # very function that is supposed to guarantee a record gets
        # written. `account_before`/`account_after` become an explicit
        # `{"unavailable": "<ExceptionClass>: <msg>"}` marker rather than a
        # real snapshot when the broker cannot be reached, and `reason`
        # notes it too.
        try:
            account_json = broker.account().to_json()
        except Exception as account_exc:  # noqa: BLE001 - see comment above
            account_json = {"unavailable": f"{type(account_exc).__name__}: {account_exc}"}
            reason = (
                f"{reason} ALSO: broker.account() failed while journaling this refusal "
                f"({type(account_exc).__name__}: {account_exc})."
            )
        record = JournalRecord(
            asof=str(effective_asof.date()),
            strategy_id=strategy.strategy_id,
            data_semantics_version=DATA_SEMANTICS_VERSION,
            quantlab_git_sha=git_sha,
            dirty=dirty,
            targets=extra.get("targets"),
            planned_orders=extra.get("planned_orders", []),
            results=[],
            account_before=account_json,
            account_after=account_json,
            reconcile_report=extra.get("reconcile_report"),
            promoting_report_card=extra.get("promoting_report_card", promoting_path),
            known_caveats=known_caveats,
            force_research=force_research,
            refused_reason=reason,
            refreshed_actions_tickers=extra.get("refreshed_actions_tickers", refreshed_tickers),
            dropped_tickers=list(dropped_tickers),
            dropped_fraction=_dropped_fraction(),
            forced_exits=extra.get("forced_exits", forced_exits),
            canceled_orders=extra.get("canceled_orders", canceled_orders),
            price_asof_by_ticker=extra.get("price_asof_by_ticker", price_asof_by_ticker),
        )
        append_journal(platform_config.reports_dir, record)
        already_journaled = True
        return record

    try:
        # -- promotion gate ---------------------------------------------
        match = find_promoting_report_card(
            platform_config.reports_dir, strategy.strategy_id, DATA_SEMANTICS_VERSION
        )
        if match is not None:
            promoting_report_card_path, report_card_data = match
            promoting_path = str(promoting_report_card_path)
            known_caveats = list(report_card_data.get("known_caveats", []))
        elif not force_research:
            reason = (
                f"promotion gate (stage={stage!r}): no report_card.json under "
                f"{platform_config.reports_dir} has verdict ELIGIBLE_FOR_PAPER for "
                f"strategy_id={strategy.strategy_id!r} "
                f"data_semantics_version={DATA_SEMANTICS_VERSION!r} - refusing to trade. Run "
                "`quantlab validate --full` on this strategy first, or pass --force-research "
                "to bypass for testing the plumbing only (never for real money)."
            )
            _refuse(reason, known_caveats)
            raise PromotionGateError(reason)
        else:
            known_caveats = [
                "FORCE-RESEARCH: promotion gate bypassed for this run (no ELIGIBLE_FOR_PAPER "
                "report card was found) - testing plumbing only, never for real money."
            ]

        # -- context: PROACTIVE actions-cache refresh (finding 1), then
        # -- wire the shared factory (finding 5: blend children) ----------
        stage = "context"
        refreshed_tickers = _proactive_actions_refresh(
            strategy, providers, broker, effective_asof, platform_config.cache_dir
        )
        if hasattr(strategy, "set_context_factory"):
            strategy.set_context_factory(context_factory)

        # -- targets: shared context, REACTIVE actions-cache refresh
        # -- (second line, finding 1), data degradation, unscoreable
        # -- policy --------------------------------------------------------
        stage = "targets"
        try:
            targets, reactively_refreshed = _generate_targets_with_actions_refresh(
                strategy, context_factory, providers, effective_asof, platform_config.cache_dir
            )
            refreshed_tickers = sorted(set(refreshed_tickers) | set(reactively_refreshed))
        except (StaleActionsCacheError, ActionsFetchError) as exc:
            reason = (
                f"actions-cache refresh policy exhausted (stage={stage!r}, "
                f"{type(exc).__name__}: {exc}) - the universe-wide refresh-and-retry did not "
                "clear the failure on retry; refusing to trade rather than retrying "
                "indefinitely or deciding on stale/unfetchable data. A human must investigate "
                "the actions-cache provider/cache."
            )
            _refuse(reason, known_caveats, promoting_report_card=promoting_path)
            raise
        except BacktestAbortError as exc:
            reason = (
                f"data degraded beyond max_dropped_fraction="
                f"{paper_cfg.max_dropped_fraction:.0%} (stage={stage!r}, {exc}) - refusing to "
                "trade rather than sizing a concentrated book on a half-completed data sync."
            )
            _refuse(reason, known_caveats, promoting_report_card=promoting_path)
            raise
        except ValueError as exc:
            if paper_cfg.abort_on_unscoreable:
                reason = (
                    f"unscoreable rebalance at {effective_asof.date()} (stage={stage!r}): "
                    f"{exc} - refusing to trade (abort_on_unscoreable=True)."
                )
                _refuse(reason, known_caveats, promoting_report_card=promoting_path)
                raise
            # Record-and-hold-prior (mirrors backtest/engine.py's own
            # tolerant policy): no orders planned, current holdings simply
            # carry over. Not a refusal - the run completed, it just had
            # nothing to decide.
            account_now = broker.account()
            caveat = (
                f"unscoreable rebalance at {effective_asof.date()}: {exc} - held prior "
                "positions unchanged (abort_on_unscoreable=False)."
            )
            record = JournalRecord(
                asof=str(effective_asof.date()),
                strategy_id=strategy.strategy_id,
                data_semantics_version=DATA_SEMANTICS_VERSION,
                quantlab_git_sha=git_sha,
                dirty=dirty,
                targets=None,
                planned_orders=[],
                results=[],
                account_before=account_now.to_json(),
                account_after=account_now.to_json(),
                reconcile_report=None,
                promoting_report_card=promoting_path,
                known_caveats=[*known_caveats, caveat],
                force_research=force_research,
                refused_reason=None,
                dropped_tickers=list(dropped_tickers),
                dropped_fraction=_dropped_fraction(),
            )
            append_journal(platform_config.reports_dir, record)
            return record

        account_before = broker.account()

        # -- reconcile, corporate-action-aware (finding 1) ----------------
        stage = "reconcile"
        prior_records = read_journal(platform_config.reports_dir, strategy.strategy_id)
        last_traded = _last_traded_or_rebaselined_record(prior_records)
        if last_traded is not None:
            expected_raw = AccountSnapshot.from_json(last_traded["account_after"])
            last_asof = normalize_timestamp(last_traded["asof"])
            actions_by_ticker = {}
            for ticker in expected_raw.positions:
                try:
                    actions_by_ticker[ticker] = providers.corporate_actions.get_actions(
                        ticker, last_asof, effective_asof
                    )
                except (StaleActionsCacheError, ActionsFetchError):
                    # Documented limitation (roll_forward_expected's own
                    # docstring): this ticker's corporate actions could not
                    # be fetched for the roll-forward window, so it is
                    # compared UNADJUSTED - a genuine action here can still
                    # trip a refusal, the conservative, correct default.
                    continue
            expected, applied_adjustments = roll_forward_expected(
                expected_raw, actions_by_ticker, last_asof, effective_asof
            )
            reconcile_report = build_reconcile_report(
                expected,
                account_before,
                reconcile_tolerances or ReconcileTolerances(),
                tuple(applied_adjustments),
            )
            if not reconcile_report.ok:
                reason = (
                    f"reconcile failed against the prior run's expected account "
                    f"(stage={stage!r}, asof={last_traded['asof']}): "
                    f"cash_diff={reconcile_report.cash_diff:.2f}, "
                    f"{len(reconcile_report.position_mismatches)} position mismatch(es) after "
                    f"applying {len(applied_adjustments)} known corporate-action "
                    "adjustment(s) - refusing to trade; a human must resolve the discrepancy "
                    "(see `accept_broker_state`/`quantlab paper rebaseline` if it is "
                    "understood and accepted)."
                )
                _refuse(
                    reason,
                    known_caveats,
                    targets=targets.model_dump(mode="json"),
                    reconcile_report=reconcile_report.to_json(),
                    promoting_report_card=promoting_path,
                    refreshed_actions_tickers=refreshed_tickers,
                )
                raise ReconcileError(reason, report=reconcile_report)

        # -- cancel resting orders before planning (finding 4) ------------
        stage = "plan"
        if paper_cfg.cancel_open_before_plan:
            canceled_orders = _cancel_resting_orders(broker)

        # -- forced exits for held, unpriceable names (finding 3) ---------
        tickers_needing_prices = sorted(set(targets.weights) | set(account_before.positions))
        prices, price_asof_by_ticker = _last_prices_with_dates(
            providers, tickers_needing_prices, effective_asof
        )
        # ANY held, nonzero, unpriceable ticker is forced out - whether or
        # not it is still in `targets.weights`. CLAUDE.md invariant #3
        # overrides whatever the strategy (possibly unaware of the
        # delisting) still wants.
        forced_exit_tickers = sorted(
            t for t, pos in account_before.positions.items() if t not in prices and pos.qty != 0
        )
        effective_weights = dict(targets.weights)
        for ticker in forced_exit_tickers:
            effective_weights.pop(ticker, None)
        effective_targets = (
            targets.model_copy(update={"weights": effective_weights})
            if forced_exit_tickers
            else targets
        )
        forced_exits = dict.fromkeys(forced_exit_tickers, "forced exit: no price / delisted")

        attempt = _next_attempt_number(
            platform_config.reports_dir, strategy.strategy_id, effective_asof
        )

        try:
            orders = plan_orders(
                effective_targets,
                account_before,
                prices,
                broker.capabilities(),
                rebalancer_config,
                attempt=attempt,
            )
        except Exception as exc:  # noqa: BLE001 - never crash without a journal record
            reason = (
                f"order planning failed (stage={stage!r}, {type(exc).__name__}: {exc}) - "
                "refusing to trade this cycle; no orders were submitted."
            )
            _refuse(
                reason,
                known_caveats,
                targets=targets.model_dump(mode="json"),
                reconcile_report=reconcile_report.to_json() if reconcile_report else None,
                promoting_report_card=promoting_path,
                refreshed_actions_tickers=refreshed_tickers,
                forced_exits=forced_exits,
                canceled_orders=canceled_orders,
                price_asof_by_ticker=price_asof_by_ticker,
            )
            raise

        stage = "submit"
        try:
            results = broker.submit(orders) if orders else []
        except Exception as exc:  # noqa: BLE001 - never crash without a journal record
            reason = (
                f"order submission failed (stage={stage!r}, {type(exc).__name__}: {exc}) - "
                "refusing to trade this cycle; no orders were confirmed submitted."
            )
            _refuse(
                reason,
                known_caveats,
                targets=targets.model_dump(mode="json"),
                # quant-gate VERDICT.2.md M08 cycle-2 non-blocking item: the
                # orders were genuinely PLANNED (and may have partly reached
                # the broker) - record the intended book so a human
                # investigating does not have to reconstruct it from the
                # broker's own history.
                planned_orders=[o.model_dump(mode="json") for o in orders],
                reconcile_report=reconcile_report.to_json() if reconcile_report else None,
                promoting_report_card=promoting_path,
                refreshed_actions_tickers=refreshed_tickers,
                forced_exits=forced_exits,
                canceled_orders=canceled_orders,
                price_asof_by_ticker=price_asof_by_ticker,
            )
            raise

        account_after = broker.account()
        resting_orders = _open_orders_to_json(broker)

        record = JournalRecord(
            asof=str(effective_asof.date()),
            strategy_id=strategy.strategy_id,
            data_semantics_version=DATA_SEMANTICS_VERSION,
            quantlab_git_sha=git_sha,
            dirty=dirty,
            targets=targets.model_dump(mode="json"),
            planned_orders=[o.model_dump(mode="json") for o in orders],
            results=[_result_to_json(r) for r in results],
            account_before=account_before.to_json(),
            account_after=account_after.to_json(),
            reconcile_report=reconcile_report.to_json() if reconcile_report else None,
            promoting_report_card=promoting_path,
            known_caveats=known_caveats,
            force_research=force_research,
            refused_reason=None,
            refreshed_actions_tickers=refreshed_tickers,
            dropped_tickers=list(dropped_tickers),
            dropped_fraction=_dropped_fraction(),
            unscored_tickers=dict(targets.unscored),
            forced_exits=forced_exits,
            canceled_orders=canceled_orders,
            resting_orders=resting_orders,
            price_asof_by_ticker=price_asof_by_ticker,
            # Documented paper-trading timing convention (carried,
            # non-blocking item): decide at the prior COMPLETED session's
            # close, submit market orders assumed to fill at the NEXT
            # session's open - roughly one and a half sessions after the
            # backtest's own `close`-mode fill convention for the same
            # nominal rebalance date. See docs/paper-trading.md's "Timing
            # convention" section.
            assumed_fill_session=str(next_trading_day(effective_asof).date()),
        )
        append_journal(platform_config.reports_dir, record)
        return record

    except (PromotionGateError, ReconcileError):
        # Already journaled by the specific handler above that raised it.
        raise
    except Exception as exc:
        # STRUCTURAL safety net (quant-gate VERDICT.md M08 cycle-2 finding
        # 1): anything NOT already journaled by a specific inner handler -
        # a strategy bug (UndeclaredDataError, LookaheadError, or any other
        # exception `generate_targets`/a blend child raises), or any other
        # unanticipated failure at any stage - still gets exactly one
        # journal record before propagating.
        if not already_journaled:
            reason = (
                f"run_once failed at stage={stage!r} ({type(exc).__name__}: {exc}) - refusing "
                "to trade; no orders were submitted this run."
            )
            _refuse(
                reason,
                known_caveats,
                targets=targets.model_dump(mode="json") if targets is not None else None,
                reconcile_report=reconcile_report.to_json() if reconcile_report else None,
                promoting_report_card=promoting_path,
                refreshed_actions_tickers=refreshed_tickers,
                forced_exits=forced_exits,
                canceled_orders=canceled_orders,
                price_asof_by_ticker=price_asof_by_ticker,
            )
        raise


def accept_broker_state(
    strategy_config: str | Path | dict,
    platform_config: PlatformConfig,
    broker: Broker,
    *,
    reason: str,
    asof: object | None = None,
) -> JournalRecord:
    """Explicit, human-approved re-baseline (quant-gate VERDICT.md M08
    cycle-1 finding 1). Writes a `kind="rebaseline"` `JournalRecord` that
    ACCEPTS the broker's current account as the new expected baseline for
    the NEXT run's reconcile check - the diff against whatever the prior
    run/rebaseline expected is computed and recorded (never silently), and
    `reason` (required - no default) is recorded verbatim in
    `known_caveats` so a reader can never mistake this for an ordinary
    trading run or a mismatch nobody looked at.

    This is the human escape hatch for a mismatch `roll_forward_expected`'s
    automatic dividend/split handling cannot explain (a manual trade, a
    transfer, an action this platform's provider does not carry)."""
    strategy = load_strategy(strategy_config)
    providers = build_backtest_providers(platform_config)
    today = _today()
    effective_asof = resolve_asof(today, asof, providers, platform_config.benchmark)

    account_now = broker.account()
    prior_records = read_journal(platform_config.reports_dir, strategy.strategy_id)
    diff_report = None
    last = _last_traded_or_rebaselined_record(prior_records)
    if last is not None:
        expected = AccountSnapshot.from_json(last["account_after"])
        diff_report = build_reconcile_report(expected, account_now, ReconcileTolerances())

    record = JournalRecord(
        asof=str(effective_asof.date()),
        strategy_id=strategy.strategy_id,
        data_semantics_version=DATA_SEMANTICS_VERSION,
        quantlab_git_sha=_git_sha(),
        dirty=_git_dirty(),
        targets=None,
        planned_orders=[],
        results=[],
        account_before=account_now.to_json(),
        account_after=account_now.to_json(),
        reconcile_report=diff_report.to_json() if diff_report is not None else None,
        promoting_report_card=None,
        kind="rebaseline",
        known_caveats=[f"MANUAL RE-BASELINE: {reason}"],
        refused_reason=None,
    )
    append_journal(platform_config.reports_dir, record)
    return record
