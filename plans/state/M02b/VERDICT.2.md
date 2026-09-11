VERDICT: ACCEPT

# M02b quant-gate verdict, cycle 2 — as-of adjustment replay + actions-cache staleness

All five cycle-1 findings are fixed, and I reproduced each fix myself rather than
reading the handoff's word for it. The accepted design is intact and I re-pinned it
with three mutations of my own. `plans/state/M02/VERDICT.md` carried item 1 is CLOSED
and M03 momentum is unblocked.

## Tree state
`uv run pytest tests/ -q` → 163 passed, 3 deselected. `uv run ruff check` → clean.
`uv run ruff format --check` → 37 files formatted. Matches HANDOFF.2.md and REVIEW.2.md.

## Each cycle-1 finding, re-run against the current tree

**1. Dividend history predating the price window — FIXED.** My exact cycle-1
reproduction (KO-style quarterly dividends from 2015-03, `asof=2024-12-10`,
`lookback_days=60`, through `PITDataContext.prices()`) no longer raises. It also
computes the right thing, which matters more than not crashing: the single in-window
ex-date (2024-09-30) applies a factor of `1 - 0.46/60`, giving a first-row close of
59.54 against a hand-computed 59.54; the `asof` row stays at the raw 60.0; the
`raw_close` column is untouched throughout.

I verified the output-preserving claim directly rather than by argument. A four-row
panel spanning a 2020 dividend and a 2021 split, adjusted whole, gives closes
`[4.5, 5.0, 10.0, 20.0]`; the same panel trimmed to its last two rows gives
`[10.0, 20.0]` — identical on the shared rows, so dropping the pre-window actions
changes no value anyone can observe. The gate sits in `apply_asof_adjustment` and
`adjustment_factors` stayed strict, as required. A two-ticker panel with different
first dates resolves each ticker against its own first date correctly.

**2. Transient fetch failure — FIXED.** My monkeypatched `ConnectionError`
reproduction now raises `ActionsFetchError` naming the ticker and the underlying
exception, chained with `raise ... from exc`, and still writes neither the cache file
nor the sidecar, so the next call retries. The new error is a `DataQualityError`
subclass, so it sits under the same umbrella as `StaleActionsCacheError`. The silent
path to an unadjusted decision series is gone.

**3. Cross-column incoherence — FIXED, preferred remedy taken.** The same NVDA row
that read `close=121.0` against `low=1195.0` at cycle 1 now reads
`open=120.0, high=121.5, low=119.5, close=121.0`: `low <= close <= high` holds, and
`volume` stays at its raw 1000. `prices_for_returns()` is unpolluted — I confirmed
the accounting path still returns raw `1200/1215/1195/1210` plus `adj_close` for the
same session.

**4. Non-positive dividend factor — FIXED at both levels.** The 45.0 distribution
against a 40.0 prior close now raises `DataQualityError`, and so does the exact-zero
boundary (40.0 against 40.0), which is the harder case to remember. The composed-factor
check in `adjustment_factors` is unreachable while every individual factor is
positive, and the comment says so; keeping it is right, because the composed value is
what actually multiplies a price.

**5. Reviewer minors — all four in.** `TOL` is 1e-12 and the suite passes at it. The
mutation-asymmetry note is in `adjustment.py`. The staleness contract note is on the
`CorporateActionsProvider` ABC, non-abstract, which is what I asked for. The
end-to-end propagation test parametrizes over both error types through `prices()`.

## The accepted design is unchanged, and I re-pinned it

Present and unmodified: `1.0 / value` for splits, `1 - D/close_prev_ex` for dividends,
the `actions.index <= asof_ts` gate, the same-day `groupby(level=0).prod()`, the
reverse cumulative product, the `side="right"` ex-date boundary, both `pit.py` hard
slices, and the `fetched_at is None or end_ts > fetched_at` staleness rule.

Three mutations of my own, each reverted and the files confirmed byte-identical to
their pre-mutation backups afterwards (the tree is uncommitted, so I restored from
copies rather than from git):

| Mutation | Result |
|---|---|
| `adjustment_factors` ex-date gate removed | both `..._leaves_price_unadjusted_when_asof_before_ex_date` parity tests fail |
| `pit.py` `prices()` actions hard slice removed | canary (f) fails with `LookaheadError` |
| OHL adjustment reverted to close-only | `..._applies_same_factor_to_open_high_low_as_close` fails |

**The `prices()` contract is now freezable for M03's Strategy ABC.** It states what
`close` is, that the identical factor hits all four price columns, that `volume` does
not get it, that a level before a gated ex-date is not a traded price, and that a
stale or unfetchable actions history blocks the decision instead of degrading it.
Those were the three gaps I named at cycle 1.

## Non-blocking observations, not conditions

- `prices()` now calls the actions provider for every requested ticker on every call,
  each hitting a parquet read plus a JSON sidecar read. A long backtest multiplies
  that by rebalances × universe size. A performance note for M04, not a methodology
  problem; the correctness of re-reading per call is not in question.
- Raw `open`/`high`/`low` are no longer retained anywhere in `prices()` — only
  `raw_close` is. Nothing in M03 needs them and `prices_for_returns()` still carries
  them, so this is a carry-forward rather than a gap. Recorded below.

## Closure

`plans/state/M02/VERDICT.md` carried item 1 — CLOSED. Adjusted decision prices from
ex-date-gated events: delivered and parity-fixtured. Hand-computed fixtures for real
sequences: delivered (NVDA, AAPL, dividend, composition, reverse split behavior
verified at this gate). The `prices()`-semantics-versus-new-accessor decision: made
and documented before the Strategy ABC freezes. Adversarial actions canary: canary
(f), mutation-verified by three separate parties now. Actions-cache staleness: strict
policy, enforced, with the fetch-failure hole closed.

M03 may compute cross-time price signals on `prices()`. It must use `close`, never
`raw_close` — see the carried items in plans/QUANT-NOTES.md.
