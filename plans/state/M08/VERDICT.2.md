VERDICT: REJECT

# M08 quant-gate verdict (cycle 2) — paper trading

All five cycle-1 findings are genuinely fixed. I re-ran every cycle-1 reproduction
unchanged and each now behaves correctly, including the two that required real
arithmetic rather than a changed error message. The work in iterations 2 and 3 is
good, and `backtest/context.py` is the right shape for the shared-context fix.

I am rejecting on one new finding, and it is a regression introduced by the
cycle-2 fix for cycle-1 finding 2: making the paper runner share the engine's
filtering provider has made the actions-cache refresh policy **unreachable for
every strategy this repository ships**. The consequence is the same one cycle 1
was rejected for — a scheduled paper run that refuses, month after month, with no
in-product way to clear it — arriving by a different route. The regression test
that covers the refresh policy uses a `DataRequirements` shape no shipped strategy
declares, so the suite is green while the shipped path is dead.

The remedy is small and is already written down: the M08 packet specifies a
**proactive** refresh policy, and what was implemented is a **reactive** one. See
finding 1. I do not think this needs escalation to Alex; it needs one more
iteration against the packet's own wording.

Finding 2 is a second, narrower hole in the same "exactly one journal record"
guarantee iteration 3 was about. Findings 3 and 4 are rulings the team lead asked
for, both in the developer's favour.

## Verification commands (all in this worktree, fake providers only)

- `uv run pytest tests/ -q` — exit 0, 686 tests, no failures.
- `uv run pytest tests/parity tests/canaries tests/test_engine.py -q` — 83/83 green
  after the `backtest/context.py` extraction. The parity goldens are undisturbed.
- `uv run ruff check` / `uv run ruff format --check` — clean.
- No repository file was modified by this gate other than `plans/QUANT-NOTES.md`
  and this verdict; `git status --short` matches the developer's iteration-3 list.
  Nothing was run against the real `data/` cache.

---

## 1. [BLOCKING] The shared filtering provider swallows cache staleness, so the
##    actions-cache refresh policy never runs for any shipped strategy

`backtest/context.py`'s `_FilteringConstituentsProvider.membership` probes each
candidate with `get_actions(ticker, _EPOCH, asof)` and converts
`StaleActionsCacheError` into a **drop** (context.py:78-82), escalating to
`BacktestAbortError` only past `max_dropped_fraction` (context.py:84-90).
`runner.py`'s `_generate_targets_with_actions_refresh` triggers the refresh only on
a `StaleActionsCacheError` **escaping** `generate_targets` (runner.py:240-242). With
the filter active, staleness can no longer escape: the tickers the strategy then
passes to `ctx.prices()` are precisely the ones whose actions probe just succeeded.

The filter is active exactly when `requirements.needs_universe and
(price_lookback_days > 0 or fundamental_fields)` (context.py:132-134). Every shipped
strategy meets it — `momentum` declares `price_lookback_days = 23 * (months + 3)`
with `needs_universe=True` (`strategies/momentum.py:200-208`), `value_composite`
declares fundamental fields, and `blend_50_50.yaml` takes the union.

The actions cache is fetch-once-forever and goes stale the moment `asof` passes its
`fetched_at` (`data/corporate_actions.py:32-55`). A backtest never sees this because
its `asof` values all precede the fetch. A paper runner's `asof` advances past it on
the first scheduled run and never comes back. So the normal monthly state is that
**every** universe ticker is stale.

Probe — actions cache `fetched_at=2023-12-02`, paper run at `asof=2023-12-29`, a
shipped declaration shape:

```
all 40 universe tickers stale (the normal case a month later)
  -> RAISED BacktestAbortError; refresh_actions_cache called 0x; dropped=[all 40]; refreshed=[]
only 1 of 40 stale (2.5%, under max_dropped_fraction=5%)
  -> TRADED; refresh_actions_cache called 0x; dropped=['T00']; refreshed=[]
```

Both outcomes are wrong, in opposite directions:

- **Above the threshold** (the ordinary monthly case) the run refuses with "data
  degraded beyond max_dropped_fraction". Nothing in the product can clear it:
  `refresh_actions_cache` is the only cure, the runner was supposed to be its
  operational caller, and there is still no `quantlab data refresh` command (an open
  M09 item). This is cycle-1's "trades once, then refuses forever" outcome again.
- **Below the threshold** the run trades, but the stale ticker is silently dropped
  from the paper universe and never refreshed — so it is dropped again next month,
  and every month after, permanently. Meanwhile a backtest of the same strategy
  includes it, because at a historical `asof` it is not stale. The paper book
  diverges from the backtest on that name indefinitely, and the journal records it
  as a data-availability drop rather than an un-refreshed cache. That is the
  milestone making it *easier* to fool ourselves, not harder.

The reason this was not caught: `tests/test_runner.py`'s `_ActionsProbeStrategy`
declares `DataRequirements(needs_universe=True, needs_actions=True)`
(tests/test_runner.py:167-168) — `price_lookback_days` defaults to 0 and there are no
fundamental fields, so the filter is **not** wrapped and staleness escapes as the
test expects. The refresh-policy test therefore passes against a declaration shape
no shipped strategy uses.

**Required remedy — implement the policy the packet actually specifies.** The M08
packet says: "call `refresh_actions_cache` for the universe when `fetched_at <
asof`, log it" (`plans/M08-paper-trading.md:46-47`). That is a **proactive** check on
the sidecar, performed before the decision context is built. What was implemented is
a **reactive** catch-and-retry, which happened to be equivalent in cycle 1 only
because nothing then intercepted the exception. Read `fetched_at` directly — the
helper already exists as `backtest/engine.py:765`'s `_actions_fetched_at`, over
`data/cache.py`'s `read_json_meta` — for the strategy's declared universe **and**
every currently held ticker, refresh those whose `fetched_at < asof`, log the
refreshed list into `refreshed_actions_tickers`, and only then build the context. A
ticker still failing after its refresh is a genuine data failure and should reach
the filter's drop-and-abort path as it does today.

Please also re-point the refresh-policy regression test at a shipped declaration
shape (`price_lookback_days > 0, needs_universe=True`), so it exercises the path
`momentum_12_1.yaml` actually takes.

## 2. [BLOCKING, narrow] A failing `broker.account()` still leaves zero journal
##    records, because the refusal writer itself calls `broker.account()`

Iteration 3's outer `except Exception` is the right structure, but `_refuse` opens
with `account_now = broker.account()` (runner.py:453-454). If that call is what
failed, `_refuse` raises again from inside the exception handler and no record is
written. Probed across the broker surface:

| broker method made to raise | journal records |
|---|---|
| `capabilities()` | 1 |
| `open_orders()` | 1 |
| `submit()` | 1 |
| `account()` | **0** |

An unreachable or unauthenticated broker — an expired key, an API outage, a network
failure on a scheduled unattended run — is the single most likely way this system
fails in production, and it is the one case the structural guarantee misses. The
docstring's "always appends exactly one `JournalRecord`" and the docs' Guarantees
paragraph are still not literally true.

**Required remedy:** wrap the account fetch inside `_refuse` in its own
`try/except`, journaling `account_before`/`account_after` as `null` (or an explicit
`{"unavailable": "<ExceptionClass>: <msg>"}` marker) when the broker cannot be
reached, so the run still leaves exactly one record naming the stage and the cause.

## 3. [RULING — the KeyboardInterrupt exclusion is correct, no change wanted]

I confirmed the behaviour independently: a `generate_targets` that raises
`KeyboardInterrupt` leaves zero journal records, because `except Exception` does not
catch `BaseException`.

I agree with the reviewer's judgement and record it as the gate's own ruling rather
than a carried item. Catching `BaseException` to journal a Ctrl-C would delay an
operator's own interrupt, and a record written from a partially unwound stack —
possibly mid-`broker.submit`, where the runner genuinely does not know what reached
the broker — would be worse than no record: it would assert an account state nobody
verified. On Windows a scheduled task killed outright terminates the process with no
Python exception at all, so the extra coverage would only ever fire on an
interactive run where a human already knows what they did. Leave it as it is.

One documentation nit, not blocking: `docs/paper-trading.md`'s Guarantees wording
"journals ANY exception that reaches it" is true under the conventional reading of
"exception" as `Exception`-derived, but since this guarantee is the one thing a
reader will lean on hardest, say so explicitly — one clause noting that a
`KeyboardInterrupt` or a killed process is deliberately outside it.

## 4. [RULING — the roll-forward residual is acceptable, with one caveat]

When a held ticker's actions fetch fails during the reconcile roll-forward, the
runner skips it and compares that ticker unadjusted (runner.py:593-599). I confirm
this is conservative and correct in isolation: an unexplained real action can then
only cause a **refusal**, never a silently accepted wrong position. There is no path
where this fabricates an adjustment or lets a mismatch through.

The caveat is its interaction with finding 1. Because nothing in the product ever
refreshes the actions cache, a held ticker's actions will routinely *be* stale at
roll-forward time, so this "documented limitation" is not a rare edge — it is the
default state, and every genuine dividend on such a name will refuse the run. Fixing
finding 1 proactively (refreshing held tickers as well as universe members, as the
remedy above specifies) collapses this residual back to the rare case it was
described as. Do not treat finding 4 as separately actionable; fix finding 1 and
re-check it.

## Cycle-1 findings: all five confirmed fixed

Re-ran each cycle-1 reproduction unchanged.

1. **Reconcile bricking — fixed.** Probed the roll-forward directly rather than
   re-reading the developer's tests. A dividend on a name the prior run **sold to
   zero** is correctly *not* credited (it is absent from the baseline's positions)
   and the next run trades normally. An injected cash credit with no corporate
   action behind it still refuses — the fix explains the ordinary case rather than
   loosening the check. `accept_broker_state` / `quantlab paper rebaseline` is a
   real, journaled escape hatch, and a refused run still never becomes the baseline.
2. **Shared decision context — fixed, and byte-identical both ways.** My 40-name
   engine-versus-runner probe now agrees in **both** cases: 0.025 each when all
   names are healthy, and 0.025641 across the surviving 39 when one name is
   unclearable — the runner drops exactly what the engine drops. `backtest/context.py`
   is genuinely the only construction site for either caller. Parity, canaries and
   `test_engine.py` are 83/83 green after the extraction.
3. **Delisted holding — fixed.** A 50-share position in a name with no bars anywhere
   is force-exited without needing a price, `forced_exits` is journaled, the broker's
   rejection of the unpriced order is recorded honestly as `REJECTED` rather than
   dressed up as a fill, and exactly one journal record is written. No crash.
4. **Partial fills — fixed, and it genuinely converges.** Three runs at a 25% fill
   fraction: 247.5 → 433.125 → 572.34375, each run cancelling the prior attempt's
   resting remainder (journaled in `canceled_orders`) and planning the residual under
   a distinct `-a2` / `-a3` client order id. The remainder is also visible in the
   same run's own record via `resting_orders`.
5. **Blend per-child context — fixed.** `run_once` calls `set_context_factory` with
   the same shared-context closure the engine uses, and an over-reaching child now
   raises rather than silently reading extra history — with a journal record naming
   `stage='targets'` and `UndeclaredDataError`, which iteration 3 added.

## Non-blocking, for whoever does the next iteration

- **`_refuse` hardcodes `planned_orders=[]`** (runner.py:462). A refusal at
  `stage='submit'` therefore records no orders even though orders were planned and
  may have partly reached the broker. The reason string is honest ("no orders were
  confirmed submitted"), but the human investigating has to reconstruct the intended
  book from the broker's own history. Pass the planned orders through to the record
  on the submit-stage refusal.
- **`_next_attempt_number` counts refused records** (runner.py:329-338), since
  `_refuse` leaves `kind="run"`. A run that refuses at `stage='reconcile'` — before
  anything is planned — still burns an attempt number. Harmless today because
  planning is driven off live account state, but the docstring says "prior
  TRADING-cycle journal records", which a refusal is not.
- **`cancel_open_before_plan=False` is a footgun.** With the attempt suffix,
  cancellation is what stops a re-run from stacking a second live order on top of a
  still-resting first one. The default is `True`; the field's docstring should say
  that turning it off can double an order, not merely that it exists.

## Files touched during this review

None mutated. This cycle needed no source mutation — every probe ran against fake
providers from the session scratchpad. `git status --short` is unchanged from the
developer's iteration-3 handoff apart from `plans/QUANT-NOTES.md` and this file.
