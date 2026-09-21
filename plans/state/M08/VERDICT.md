VERDICT: REJECT

# M08 quant-gate verdict (cycle 1) — paper trading

Code review's APPROVE is not in dispute: the code is correct against its own
docstrings, the promotion gate is keyed exactly as M06 required, the Alpaca
adapter has no live-money path, and the rebalancer's hand cases recompute. What
this gate tests instead is whether the milestone does the thing it exists to do —
run a validated strategy forward, on a monthly schedule, producing a record M09
can compare against the backtest. It does not. On a healthy fixture the runner
reproduces the engine's targets exactly; on the first ordinary real-world event
(a dividend, a delisting, a partial fill, one unrefreshable ticker in a 40-name
universe) it either stops trading permanently or crashes without a journal entry.

Findings 1–3 are each independently sufficient to reject. Findings 4–5 are
blocking but cheap.

## Verification commands (all run in this worktree)

- `uv run pytest tests/ -q` — exit 0, unchanged from the handoff.
- `uv run ruff check`, `uv run ruff format --check` — clean.
- Adversarial probes written to the scratchpad, not the repo; every mutated file
  was restored from a byte-for-byte copy and its SHA-256 re-verified (see
  "Files touched" at the bottom). I did not run the CLI against the real
  `data/` cache, for the write-through reason the review traced; all probes use
  fake providers.

---

## 1. [BLOCKING] Reconciliation permanently bricks the schedule after the first
##    ordinary corporate action, and the documented recovery cannot work

`run_once` reconciles this run's `account_before` against the last **non-refused**
journal record's `account_after` (`src/quantlab/paper/runner.py:390-392`). A
refused run therefore never becomes the new baseline. Combined with a $1 absolute
cash tolerance (`paper/reconcile.py:32`), the first dividend, interest credit or
split inside the paper account — none of which this platform causes or predicts —
makes every subsequent run refuse, forever, against the same frozen baseline.

Reproduced with a four-run monthly schedule, one $123.75 dividend credited by the
broker between run 1 and run 2 (a 495-share position at $0.25):

```
run 1 asof=2023-11-30: TRADED, orders=2
[broker credits a $123.75 dividend to cash]
run 2 asof=2023-12-29: REFUSED - reconcile failed against the prior run's expected account (asof=2023-11-30): cash_diff=123.75
run 3 asof=2024-01-31: REFUSED - reconcile failed against the prior run's expected account (asof=2023-11-30): cash_diff=123.75
run 4 asof=2024-02-29: REFUSED - reconcile failed against the prior run's expected account (asof=2023-11-30): cash_diff=123.75
```

Note the baseline `asof=2023-11-30` never advances. `docs/paper-trading.md:113-115`
correctly names a corporate action as a cause, then at line 123 prescribes a
recovery that is impossible: "let the NEXT run's own expectation reset: since
reconciliation only compares against the immediately PRIOR run's `account_after`,
once the next run completes cleanly its `account_after` becomes the new baseline."
No next run can complete cleanly, because reconciliation happens before any
trading and the comparison is against the last *traded* run, not the immediately
prior one. The only escape the doc then offers is to recreate the broker account
and move `journal.jsonl` aside — which destroys the forward-test history M09 is
built to read.

This is not an edge case. Any long US equity book pays dividends most months. As
shipped, this system trades exactly once.

**Required remedy** (either, preferably both):
- Make the expectation corporate-action aware. The platform already wires a
  `CorporateActionsProvider` into `BacktestProviders`; roll the journal's expected
  cash and share counts forward through dividends and splits with ex-date between
  the two runs' `asof` dates before comparing, and journal that adjustment so a
  reader can see what was explained versus what was not.
- Add an explicit, journaled re-baseline path (e.g. `quantlab paper reconcile
  --accept`, writing a record with its own kind so it is never mistaken for a
  trading run). The doc's "there is no automatic 'accept the new reality' command
  by design" is a defensible stance only if some human-driven path exists; today
  there is none, and the doc describes one that does not work.
- Either way, correct `docs/paper-trading.md:117-130`.

## 2. [BLOCKING] The runner's decision context is not the engine's: the
##    ticker-filtering layer and both data-degradation guards are missing

The packet requires the runner to "build `PITDataContext(asof=last completed
session)` exactly as the engine does", and `docs/paper-trading.md:153-156`
promises in its Guarantees section that "the runner's decision context is built
identically to the backtest engine's own decision path". It is not.

`backtest/engine.py:868-896` builds its decision context with
`constituents_provider=constituents`, where `constituents` is a
`_FilteringConstituentsProvider` wrapper whenever `reqs.needs_universe and
(reqs.price_lookback_days > 0 or reqs.fundamental_fields)` — precisely the
declaration `strategies/momentum.py:200-208` makes, so this is the shipped path
for `momentum_12_1.yaml`, not a corner. The wrapper probes each candidate's
corporate-actions fetch before the strategy sees `ctx.universe()`, drops and
records failures, and aborts the run if more than `max_dropped_fraction` (default
5%) of the membership fails. `paper/runner.py:159-173` passes the raw
`providers.constituents` with no wrapper.

Probe: a 40-name universe, equal weight over whatever `ctx.universe()` returns,
same `asof` (2023-11-30), engine versus runner.

| case | engine | runner |
|---|---|---|
| all 40 healthy | 0.025 each | 0.025 each, weights byte-identical |
| one name (2.5% < 5%) with an unclearable actions failure | rebalances into the other 39 at 0.025641 each | raises `StaleActionsCacheError`, refuses to trade |

The healthy case is genuinely identical, which is worth keeping. The degraded
case is not, and the divergence runs the wrong way for a forward test: the paper
runner stops on exactly the data conditions the backtest was built to absorb. One
dead ticker in an S&P universe — routine over a live year — takes the whole
schedule down. It fails safe, so this is not a money-losing bug; it is a
"the forward test has holes M09 will read as strategy behaviour" bug, and a
documentation claim that is false.

Compounding it, the runner has no counterpart to **either** engine guard on
degraded data: `max_dropped_fraction` (engine.py:876-882) or
`abort_on_unscoreable` (engine.py:1050-1053, default True). A half-completed
overnight price sync leaves the strategy scoring only the names that happen to
have data; the runner will size and submit that concentrated book with nothing
refusing and no coverage bound recorded. `targets.unscored` reaches the journal,
but nothing reads it and no threshold acts on it. That direction *can* lose money.

**Required remedy:** build the paper decision context through the same wrapper
with the same drop-and-abort policy; carry a paper-side equivalent of
`max_dropped_fraction` and `abort_on_unscoreable`; record the dropped list and a
coverage bound in the journal record so M09 can tell a data outage from a signal
change. Then make the Guarantees paragraph true, or narrow it to what is actually
guaranteed.

## 3. [BLOCKING] A delisted holding crashes the run with no journal record at all

`plan_orders` raises `ValueError` for any ticker needing an order that has no
price (`paper/rebalancer.py:101-104`). `run_once` calls it at
`paper/runner.py:428`, outside every `try`. A position in a name that has stopped
printing bars — the normal end state of a holding that gets delisted between two
monthly runs — therefore takes the runner down with an unhandled `ValueError`:

```
RAISED ValueError: plan_orders: no price supplied for 'DEAD'
journal records written for this run: 0
```

Two things are wrong. First, `run_once`'s own docstring
(`paper/runner.py:286-292`) states it "Always appends exactly one `JournalRecord`
(including on a refusal) before returning or raising"; on this path, and on any
strategy-raised exception that is not a stale/unfetchable-actions error, it
appends none. M09 reads a journal that silently omits the days the runner died.
Second, the platform has a non-negotiable invariant that delistings book a forced
exit at last available price with a configurable haircut (CLAUDE.md invariant #3,
implemented in the engine). The paper path has no delisting handling whatsoever.

**Required remedy:** give a priced-out holding an explicit policy — book a forced
exit at the last available close under the engine's `delisting_haircut`
convention, or refuse and journal — and restructure `run_once` so that every exit
path, exception included, writes exactly one record, as its docstring already
promises.

## 4. [BLOCKING, lower severity] A partial fill can never be completed, and the
##    journal misreports the replayed fill as this run's result

`client_order_id` is a pure function of `(strategy_id, asof, ticker)`
(`paper/broker.py`, `client_order_id_for`), so one ticker gets at most one order
per day, ever. That gives same-day idempotency, which the packet asked for. It
also means a partially filled order can never be topped up. Probe, 25% fill
fraction, same `asof` three times:

```
run 1: planned=[('AAA','BUY',990.0)]  results=[('AAA', 247.5)]  account AAA=247.5  open_orders=[742.5]
run 2: planned=[('AAA','BUY',742.0)]  results=[('AAA', 247.5)]  account AAA=247.5  open_orders=[742.5]
run 3: planned=[('AAA','BUY',742.0)]  results=[('AAA', 247.5)]  account AAA=247.5  open_orders=[742.5]
```

The record for runs 2 and 3 reads "planned BUY 742, result a fill of 247.5" — the
result belongs to a different order, submitted on a different run. A later reader
of the journal, human or M09, cannot tell that nothing was executed. Meanwhile the
742.5-share remainder rests at the broker indefinitely: `Broker.open_orders()` and
`cancel()` exist in the ABC and the runner never calls either. At a real broker
that remainder can fill days later, moving the account outside the journal, which
then trips finding 1 and refuses forever.

**Required remedy:** pick a policy and implement it — cancel prior-run resting
orders at the start of a cycle, or admit a top-up attempt into the client order id
so it is a distinct order. Either way, never journal a replayed duplicate as this
run's fill: `MockBroker.submit` already distinguishes the duplicate case for
`OrderAck` (`paper/mock.py:82-84`) but replays the cached `Fill` verbatim
(`paper/mock.py:79-81`); both should surface as `DUPLICATE` in the record.

## 5. [BLOCKING, lower severity] Blend strategies lose the M04 per-child context
##    guard in the paper path

`backtest/engine.py:898-899` calls `strategy.set_context_factory(context_factory)`
so each blend child gets a context built from its **own** `requires()`. The runner
never calls it, so `BlendStrategy.generate_targets` takes its documented fallback
and hands every child the single union-built context
(`strategies/blend.py:125-130, 205-210`). That fallback is the pre-M04 bug by
name: `tests/test_blend.py:398-405`
(`test_overreaching_child_does_not_raise_without_the_factory_reproducing_the_bug`)
exists specifically to demonstrate that a child over-reaching its declared data
footprint raises `UndeclaredDataError` standalone but not under the union context.

`configs/strategies/blend_50_50.yaml` ships, so this is a live path. The guard
being off does not create look-ahead past `asof` — the child's context is still
bound to the same date — but it does mean an under-declared child reads more
history in paper than the backtest allowed it, and can therefore produce different
targets. A milestone whose whole purpose is "no second signal implementation"
should not quietly disable the mechanism that keeps composition honest.

**Required remedy:** call `set_context_factory` from the runner with the same
closure shape the engine uses, bound to the run's single `asof`.

---

## Non-blocking, carried to M09

- **The staleness ceiling watches only the benchmark.** `_cached_data_ceiling`
  (`paper/runner.py:122-137`) clamps `asof` to the last cached bar for
  `platform_config.benchmark` alone. A universe name whose overnight sync lagged
  is decided on a stale bar with nothing recorded; the journal has no per-ticker
  data-asof, so M09 cannot separate that from signal drift.
- **Execution timing differs from the backtest and is undocumented.** Scheduled at
  16:30 ET, the runner decides as of the previous completed session and submits
  market orders that fill at the next open — roughly one and a half sessions after
  the backtest's `close` convention fills the same rebalance. Expected, but
  `docs/paper-trading.md` never says so, and M09's drift check will mis-attribute
  it unless it models the lag.
- **`journal_to_frame` drops fields M09 will want.** `promoting_report_card`,
  `known_caveats`, `refreshed_actions_tickers` and `targets` are in the JSONL but
  not in the frame (`paper/journal.py:109-125`). The docstring points at the raw
  file, so this is a convenience gap, not a data gap.
- **Canary (k) asserts only half of what the packet specified.** It pins
  `asof == prev_trading_day(today)` (`tests/canaries/test_lookahead.py:802-803`)
  but not "never later than the data's last cached bar". I mutated
  `resolve_asof` to delete the data-ceiling clamp entirely and the canary still
  passed; only `tests/test_runner.py::test_resolve_asof_clamps_to_the_price_caches_actual_last_bar`
  failed. The behaviour is covered, but not by the canary the packet named, and
  canaries are the layer that is meant to survive refactors.

## Confirmed sound — do not redo these in cycle 2

- **Promotion gate keying** closes the M06 carried item. Probed directly: a
  `REJECTED` card, a `RESEARCH_ONLY` card, an `ELIGIBLE_FOR_PAPER` card carrying a
  stale `data_semantics_version`, and a `REJECTED`-plus-stale-`ELIGIBLE` pair all
  raise `PromotionGateError`; only a current-semantics `ELIGIBLE_FOR_PAPER` card
  trades. A semantics-version bump correctly invalidates every old card.
- **`--force-research`** leaves an unmissable trail M09 can see:
  `force_research: true`, `promoting_report_card: null`, and a `known_caveats`
  entry beginning `FORCE-RESEARCH:`.
- **Alpaca paper-only by construction.** Credentials read only from
  `ALPACA_API_KEY`/`ALPACA_SECRET_KEY`, `paper=True` hardcoded, plus a
  belt-and-braces assertion on the client's resolved base URL. Nothing logged.
- **Rebalancer.** No-short guard raises before any order is planned; sells precede
  buys; quantities are only ever floored, so rounding cannot eat the cash buffer;
  a sell is bounded by the held quantity and cannot go short.
- **Targets are byte-identical to the engine's on healthy data** — the core claim
  of the milestone holds where the data holds.
- **Journal is genuinely append-only**, one record per run on every path that
  reaches a record at all (finding 3 is about paths that do not).

## Files touched during this review

Mutated and restored, checksum re-verified identical
(`551ede4bbe31af75ec09a22442b1659191b7c879372890d89db838be57c0e091`):

- `src/quantlab/paper/runner.py` — data-ceiling clamp deleted for the canary
  mutation check, then restored from a copy taken before the edit.

No other repository file was modified by this gate. Probe scripts live in the
session scratchpad.
