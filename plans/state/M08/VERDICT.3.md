VERDICT: ACCEPT

# M08 quant-gate verdict (cycle 3) — paper trading

Both cycle-2 blockers are fixed, and I verified each by re-running my own probes
unchanged rather than re-reading the developer's tests. The proactive refresh is
the remedy the packet specified, it works on the shipped strategy shape, it covers
held tickers outside the declared universe, and it introduces no look-ahead. The
two rulings I was asked for both stand in the developer's favour.

I am accepting. One real defect remains, in `--dry-run` (see "Must fix before
`--dry-run` is trusted" below). I am not blocking on it because it sits outside
the scope this cycle was given, it cannot cause a trade, and it fails loudly in
its two most likely forms — but it is a genuine defect of a class I rejected for
twice, so it must not be closed quietly.

## Verification commands (worktree only, fake providers only)

- `uv run pytest tests/ -q` — exit 0, 690 tests.
- `uv run pytest tests/canaries -q` — 24/24 green.
- `uv run pytest tests/ -q` **with all outbound sockets hard-blocked** — exit 0.
  CLAUDE.md invariant #5 holds globally, including on the new refresh path; no test
  reaches the network even where the proactive pass runs unguarded.
- `uv run ruff check` / `ruff format --check` — clean.
- Nothing run against the real `data/` cache. No source file mutated this cycle.

---

## Cycle-2 blocker 1 — proactive actions refresh: FIXED

`_proactive_actions_refresh` (runner.py:249-309) runs before the decision context is
built, reads the `fetched_at` sidecar directly through `backtest.context.actions_fetched_at`
— the same helper the engine's provenance uses, so there is still one implementation —
and refreshes anything missing or stale for the declared universe plus every held
ticker. It sits after the promotion gate, so a `REJECTED` strategy still refuses
before touching the network.

Re-ran my two cycle-2 probes unchanged, with real sidecar files on disk, on the
shipped declaration shape (`needs_universe=True`, `price_lookback_days > 0`):

| scenario (sidecar `fetched_at=2023-12-02`, run at `asof=2023-12-29`) | cycle 2 | cycle 3 |
|---|---|---|
| all 40 universe tickers stale | `BacktestAbortError`, 0 refreshes | **TRADED**, 40 refreshes, 0 dropped |
| 1 of 40 stale | traded, dropped silently, 0 refreshes | **TRADED**, exactly 1 refresh, 0 dropped |
| 1 of 40 stale and its refresh fails | n/a | **TRADED** on 39, dropped and journaled |

The third row is the one that matters most for honesty: a refresh that genuinely
cannot succeed still falls through to the shared filter's drop-and-count policy and
is recorded in `dropped_tickers`, rather than being papered over.

**Held tickers outside the universe are covered.** A position in a name that has left
the index — the case that made the roll-forward residual routine rather than rare — is
refreshed: universe `T00..T04` fresh, held `OLD` stale and out of the index, and the
run refreshes exactly `OLD`.

**No look-ahead introduced.** This was the sharpest new risk: a refresh at `asof`
downloads the full actions history *through today*, so the cache legitimately comes to
hold ex-dates after `asof`. I planted a 10:1 split dated 2024-01-03 — five days after
an `asof` of 2023-12-29 — let the proactive pass pull it in, and checked what the
strategy could see:

```
refreshed=['BENCH', 'T00']; cache now holds a 10:1 split dated 2024-01-03
ctx.prices last close = 100.0   (raw fixture close = 100.0, i.e. unadjusted)
ctx.prices max index  = 2023-12-29  (exactly asof)
planned order         = BUY 990.0   (unchanged; a leaked 10:1 would move this ~10x)
```

The context's hard slice at `asof` holds, and the quantity a leak would have moved by
an order of magnitude is untouched. Canaries are 24/24 green, including (f)
`test_canary_future_dated_action_has_zero_effect_on_prices` and both halves of (k).

## Cycle-2 blocker 2 — guarded refusal writer: FIXED

`_refuse`'s own account fetch is now guarded. Probed across the broker surface; the
`account()` row is the one that produced zero records last cycle:

```
raised=_Boom  records=1
account_before={'unavailable': '_Boom: broker unreachable'}
reason=run_once failed at stage='targets' (_Boom: broker unreachable) - refusing to
       trade; no orders were submitted this run. ALSO: broker.account() failed while
       journaling this refusal (_Boom: broker unreachable)
```

Exactly one record, the stage named, and both causes stated. The structural
guarantee now holds for every `Exception` I can construct.

## Ruling — the roll-forward residual has collapsed back to a rare edge

Asked to confirm this directly. Run 1 holds `HELD` and trades; `HELD` then pays a
dividend and leaves the index before run 2, so only the held-ticker branch of the
proactive pass can save it. Run 2 trades, with the dividend explained:

```
applied_adjustments=[{'ticker': 'HELD', 'action_type': 'dividend',
                      'date': '2023-12-15', 'value': 0.25, 'cash_credit': 123.75}]
```

Under cycle 2 this same case refused. The unadjusted-comparison fallback remains as a
last resort and remains conservative — it can only cause a refusal, never a silently
accepted wrong position — but it is now the rare edge its docstring describes. Item
closed.

## Ruling — the autouse no-op refresh fixture is acceptable, with a recommendation

`_no_real_actions_refresh` (tests/test_runner.py:321-336) monkeypatches
`refresh_actions_cache` to a no-op for every test in that file, because none of the
file's fixtures write a `fetched_at` sidecar, so the proactive pass considers
everything stale and would otherwise attempt live downloads. CLAUDE.md invariant #5
requires offline deterministic tests, so guarding it is right, and the guard is
scoped to one file rather than to `conftest.py`.

I checked the two things that would make it dangerous, and neither holds:

- **It is not hiding a live call elsewhere.** `tests/test_cli_paper.py` and
  `tests/canaries/test_lookahead.py` also drive `run_once` with no such fixture. I ran
  the entire suite with `socket.connect` replaced by a hard failure: exit 0. Nothing
  reaches the network, guarded or not.
- **It is not making the refresh tests pass vacuously.** The three new tests
  re-monkeypatch the same name locally, and the reviewer's mutation check (deleting the
  proactive pass fails all three) is corroborated by my own probes, which used real
  sidecar files on disk and produced exactly the right refresh counts per scenario.

The recommendation, for whenever this file is next touched: have the shared
`_platform_config` / `_fake_providers` helpers write fresh sidecars, so the proactive
pass honestly concludes "nothing to refresh" and the autouse no-op becomes a
belt-and-braces net rather than the thing that makes the default path quiet. As it
stands, every test in the file exercises "decide stale, then refresh into a no-op",
which is a slightly false default. Not blocking; the behaviour is verified elsewhere.

## Non-blocking items from cycle 2: all done

`_refuse` now carries `planned_orders` through on a submit-stage refusal;
`_next_attempt_number` excludes refused records; `cancel_open_before_plan`'s docstring
states plainly that `False` can stack a second live order; `docs/paper-trading.md`
states the `KeyboardInterrupt` exclusion and why.

---

## Must fix before `--dry-run` is trusted (carried, not blocking this verdict)

`cli.py:552-585`'s `--dry-run` branch is a hand-rolled second implementation of the
decide-and-plan sequence. It calls `build_decision_context` and `plan_orders` directly
and wires **none** of what `run_once` does:

```
set_context_factory          present in dry-run branch: False
_proactive_actions_refresh   present in dry-run branch: False
forced_exit                  present in dry-run branch: False
attempt                      present in dry-run branch: False
cancel                       present in dry-run branch: False
PaperRunConfig               present in dry-run branch: False
```

Same stale cache, same `asof`, same fixture, both paths:

```
--dry-run : RAISED BacktestAbortError - 41/41 tickers (100.0%) failed a
            data-availability probe at asof=2023-12-29, exceeding max_dropped_fraction=5%
real run  : TRADED, 1 order, 41 tickers refreshed
```

Consequences, in descending order of seriousness:

1. **The blend per-child context guard is off in dry-run.** With no
   `set_context_factory`, `BlendStrategy` takes its pre-M04 fallback and hands every
   child the union context. That is cycle-1 finding 5, still live here, and
   `configs/strategies/blend_50_50.yaml` ships. A previewed blend book can differ from
   the real one, and an under-declared child does not raise.
2. **The preview aborts where the real run trades**, on what is now the ordinary stale
   cache — which is also the packet's own verification command
   (`quantlab paper run ... --broker mock --dry-run`).
3. **The preview can crash where the real run force-exits**, since a held unpriceable
   ticker with a nonzero target still reaches `plan_orders` without the forced-exit
   rewrite.
4. Order ids shown are always attempt 1, and `max_dropped_fraction` is hardcoded to
   `0.05` rather than read from `PaperRunConfig`.

**Remedy:** give `run_once` a `dry_run: bool` parameter that stops after planning —
skipping `broker.submit` and journaling, or journaling with `kind="dry_run"` — and have
the CLI call it. The whole point of this milestone is that there is one decide-and-plan
path; a preview built from a different one is the same mistake in a smaller place.

I would have made this blocking had I raised it in cycle 1 or 2. I am not doing so now
because this cycle was scoped to my VERDICT.2.md items, the developer had no notice of
it, it cannot cause a trade, and points 2 and 3 fail loudly. It should be fixed before
Alex relies on `--dry-run` to decide whether the system is behaving.

## Files touched during this review

None mutated. Every probe ran against fake providers from the session scratchpad, so no
checksum restoration was required. `git status --short` is unchanged from the developer's
iteration-4 handoff apart from `plans/QUANT-NOTES.md` and this file.
