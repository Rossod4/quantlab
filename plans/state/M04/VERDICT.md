VERDICT: REJECT

# M04 quant gate — cycle 1

Scope: work packet `plans/M04-backtest-engine.md` (in-scope files, acceptance
criteria 1–11, carried items 1–11), `HANDOFF.md`/`HANDOFF.2.md`,
`REVIEW.md`/`REVIEW.2.md`, and every `plans/QUANT-NOTES.md` item addressed to M04.

Working tree at gate time: 315 tests pass (`uv run pytest tests/ -q`, exit 0),
`uv run ruff check` clean. No repo file was mutated by this gate — an md5 baseline
over all 74 tracked `.py`/`.yaml` files was taken before and after and is identical;
every probe below ran from the session scratchpad.

The code review's APPROVE is sound on everything it examined: all four of its
iteration-1 blockers really are closed, the parity work is a genuine
cross-implementation check against the old repo's own functions, and canary (i) has
real mutation power. The findings below are in the accounting layer the review did
not probe with adversarial fixtures, and four of the five sit in the forced-exit and
coverage paths — the two places where CLAUDE.md invariants #2 and #3 live.

---

## Blocking findings

### 1. The survivorship coverage bound is computed over the names the strategy HELD, not the universe — so `overall_bound` is meaningless in every real run

**Risk.** CLAUDE.md invariant #2 and acceptance criterion 7. The single number the
platform is built around reports "fraction of the index the strategy did not buy"
rather than "fraction of the index the strategy could not see".

**Evidence.** `engine.py:543,706-707` accumulate `all_encountered_tickers` from
`targets.weights` and `prior_weights` only. That set is passed to
`price_availability_from_cache` at `engine.py:772-773`, and `coverage_gap`
(`data/survivorship.py:139-142`) classifies every point-in-time member with no
`price_availability` entry as `lacking`.

Probe: a 10-name universe, every name with a complete, untruncated parquet cache and
sidecar on disk, a strategy holding the top 3.

```
Every one of the 10 universe names has complete price data on disk.
Strategy holds 3 of 10.
coverage by_year:
 2020    70.0
overall_bound: 70.0  <-- TRUTH is 0.0
```

For the shipped `momentum_12_1_2012_2026.yaml` (30 holdings, S&P-scale universe) the
bound reads roughly 94% on every run regardless of actual data coverage. The
masked-truncation machinery added for QUANT-NOTES M02 item 3(ii) is inert as a side
effect: a delisted, metadata-masked name is by definition one the strategy stopped
holding, so it is never in `all_encountered_tickers` and its `masked_end` is never
read. It is instead absorbed into the same undifferentiated 94%.

Every engine test uses `_EqualWeightStrategy`, which holds the entire universe, which
is why this survived both review iterations.

**Remedy.** Accumulate the union of `ctx.universe()` across rebalance dates (the engine
already calls it at `engine.py:698` when `needs_universe`) and build
`price_availability` from that, not from the held set. Add a test where the strategy
holds a strict subset of a fully-cached universe and asserts `overall_bound == 0.0`,
and a second where a non-held member is truncated and the bound moves.

**What the bound then means**, for the record: the worst single calendar year's
percentage of that year's point-in-time index members — membership sampled at the last
rebalance date falling in that year — that had no cached price history at all, or whose
cache was metadata-masked before that sampling date. It is a ceiling on names invisible
to the strategy, not a return impact, and it deliberately excludes the per-rebalance
unscored/dropped names, which stay in `quality_flags`.

### 2. `delisting_haircut` never reaches the reported return series

**Risk.** The haircut is the platform's only realism dial on forced liquidation
(CLAUDE.md invariant #3, and the packet's "document that >0 is the conservative
setting"). It is inert on `gross_returns`, `net_returns`, `gross_equity`, `net_equity`
and `cost_drag` — every number M05–M07 consume. Direction: flattering.

**Evidence.** `engine.py:641-645`. The ledger is told about the haircut; the return is
not:

```python
ledger.force_exit(ticker, last_price, config.delisting_haircut, reason="price_series_ended")
forced_exits += 1
r = last_price / entry_fill - 1.0          # <- no (1 - haircut)
```

Probe: a 50%-weighted name whose series ends mid-period, run at three haircuts.

```
haircut=0.0: LEDGER equity [1000000, 1000000, 1000000, 1000000] | net_equity [1.0, 1.0, 1.0, 1.0]
haircut=1.0: LEDGER equity [1000000,  500000,  500000,  500000] | net_equity [1.0, 1.0, 1.0, 1.0]
```

A 100% haircut writes half the book to zero in the ledger and moves the headline equity
curve by exactly nothing. This also falsifies the module docstring's claim that the two
tracks "agree to first order" and differ by a `cost * gross` cross term.

**Remedy.** Apply the haircut in the return: `r = last_price * (1 - haircut) / entry_fill - 1.0`.
Extend the existing forced-exit test to assert `net_equity` moves with the haircut, so a
zero-valued default cannot hide the omission again.

### 3. The forced-exit return is a RAW price ratio, so a corporate action inside the final holding period is booked as P&L — and the extreme-return guard is exempted from catching it

**Risk.** Unbounded, upward, and correlated with the trigger condition. Reverse splits
are concentrated in exactly the distressed population that then delists, because they
are done to maintain exchange listing compliance.

**Evidence.** `engine.py:638-645` divides `last["close"]` (raw, unadjusted) by
`prior_fill_prices[ticker]` (raw entry). Every other name uses the adj_close ratio at
`engine.py:648`. Forced exits are explicitly exempted from the extreme-return guard
(`engine.py:628-637`), so nothing downstream catches the result.

Probe: a 1-for-10 reverse split on 2020-02-10, last trade 2020-02-14, `adj_close` flat
at 10.0 throughout — the holder's economic value never changed. The name is 50% of an
equal-weight two-name book, so the true period return is 0%.

```
forced_exits    = 1
extreme_returns = 0        <- guard did NOT fire
net_returns: 2020-02-28  +4.5000
final net_equity = 5.5
```

A control run with the identical split, but where the name keeps trading so no forced
exit occurs, returns 0.0000 in every period — which isolates the defect to the
forced-exit branch.

The same line also drops any dividend paid during the final period, and in `next_open`
mode divides a close by an open.

**Remedy.** Book the forced exit on the same total-return basis as every other name:
`adj_close` of the last available bar over `prior_return_prices[ticker]`, with the
haircut applied multiplicatively per finding 2. Keep the raw close for the ledger's cash
proceeds. Then re-examine the guard exemption — with a consistent basis it is
defensible, but state the decision rather than inheriting it.

### 4. The extreme-return guard inverts on short positions: it deletes the worst loss a short book can take

**Risk.** Code that runs but weakens a bias guard. A short squeeze is the single event a
short book must not be allowed to hide, and this removes it and renormalises the
remaining shorts as though the squeezed name had behaved like its peers.
`configs/strategies/momentum_long_short.yaml` (dollar-neutral, n_short=30) and
`momentum_130_30.yaml` both ship.

**Evidence.** `engine.py:649` tests `r > config.extreme_return_bound` on the raw price
return with no reference to the sign of the weight. For a short, a +400% price move is a
−400% position return.

```
130/30, extreme in the LONG book   -> renormalises longs only    OK
130/30, extreme in the SHORT book  -> renormalises shorts only   OK
100% short, shorted stock +400%:
  _weighted_return_excluding({'S1': -1.0}, {'S1': 4.0}, {'S1'})
    = +0.000000   instead of   -4.000000
```

The renormalisation *mechanics* the review verified by hand are correct — each sign-book
rescales independently and never leaks across. The **trigger** is what is wrong, and no
test in the suite exercises the guard with a negative weight.

The old repo's "upside-only" choice was correct in its own context: a long-only book,
where a vendor glitch produces a spurious gain and a real loss is floored at −100%.
Carrying that asymmetry to a short book reverses its direction.

**Remedy.** Gate on the position's return, not the price return — exclude when
`w * r > bound * abs(w)`, that is, when the move is implausibly *favourable to the
position as held*. A long with a +400% print is still excluded; a short squeeze is kept.
A short's genuine gain is floored at +100% of the position, so the upside guard
correctly can never fire on a short. Add long-short tests in both directions.

Related, same function: when *every* name in one sign-book is excluded, that book
contributes 0 (`engine.py:473-475`) and the period's net exposure silently changes — a
market-neutral book becomes 100% net short for that period. The probe reproduces it.
Decide and document; at minimum it should raise a quality flag of its own.

### 5. `next_open` mode fills at the open but measures returns close-to-close

**Risk.** This is the mode that exists to be the realistic one, and its two tracks
disagree about when the position started. Lowest severity of the five, and resolvable by
documentation — but not as currently written, because the module docstring presents the
choice as affecting only the measurement *date*, never the price basis.

**Evidence.** `engine.py:641,647-648`: the return series uses `adj_close` at the fill
dates in both modes, while the ledger uses `open` in `next_open` mode (`engine.py:591`,
`fill_column`).

Probe: buy at the 2020-03-02 open of 100; that session closes at 110.

```
gross_returns: 2020-03-02  +0.100000
```

The fill-day intraday gain is credited to the period *ending* on the fill date — the
outgoing book — not to the incoming book that actually bought at that open. Acceptance
criterion 11 only checks the ledger's fill prices, which is why this passed. For a
month-end momentum book the systematically-skipped day is the first day of short-term
reversal against freshly-bought winners, so the direction flatters.

**Remedy.** Derive an adjusted open for the return basis in `next_open` mode
(`raw_open * adj_close / raw_close` on the same bar — `prices_for_returns` already
carries all three), or rename the mode and state plainly that entry is measured at the
next session's close.

---

## Verified clean (probed, not read)

- **Look-ahead through the engine.** A spy strategy recorded every context across both
  execution modes against a hostile price provider that ignores the requested window and
  returns the full panel. `ctx.asof` equals the decision date at every rebalance; the
  maximum price date the strategy could reach never exceeds `asof`; `prices()` carries no
  `adj_close`; `next_open` fill and return dates are the next session, never the same
  session.
- **Dividend accounting.** A $5 dividend on a $100 stock inside the holding period
  produced exactly +5.263158% (100/95 − 1) in the period it went ex, and 0.0 in every
  other period — counted once, on the adj_close basis, PIT-clean per the M02 verdict.
- **Costs.** Turnover-based and two-sided, matching the old repo's convention. 30%
  monthly turnover at 10bps one-way gives 0.72%/yr, bracketing the old repo's 0.78%/yr
  figure (0.48%/yr at 20% turnover, 0.96%/yr at 40%). The identity
  `transaction_cost_fraction == 2 * turnover * bps / 1e4` holds exactly. Borrow on a
  dollar-neutral book is 0.300%/yr at 30bps.
- **Forced-exit trigger.** "Price series ends before period end" only; `infer_delisting`
  is not called in the hot path and is a strict subset of that condition, which closes
  QUANT-NOTES M02 item 4 ("index removal precedes the final trade"). No `legacy_drop` or
  drop-from-average fallback exists anywhere in `src/quantlab/backtest/`.
- **Provenance.** `strategy_id`, `strategy_params`, full `backtest_config`, provider
  class names, `actions_cache_fetched_at` min/max, `quantlab_git_sha`, `run_timestamp`,
  `data_semantics_version` ("m03b") and `known_caveats` all present; `save`/`load`
  round-trips provenance exactly and `net_equity` to 0.0 absolute difference.
- **Extreme-return guard, bias direction.** Excluding a genuine +300% winner replaces it
  with its book's surviving average, so the measured return is *lower* than truth: the
  guard is a real bias and its direction is conservative **for a long book**. Because it
  truncates the right tail only, it also makes the return distribution look more
  left-skewed and thinner-tailed on the right than reality, which pushes PSR and DSR
  down — conservative again. `quality_flags.extreme_returns` surfaces the count, which is
  the right mitigation. The problem is finding 4: on a short book the same rule truncates
  the *left* tail of the position instead.

## Non-blocking notes (carried forward, see QUANT-NOTES.md)

- The ledger track runs entirely on raw prices and never credits dividends, so
  `snapshots` diverge from `net_equity` by roughly the cumulative dividend yield — on the
  order of 30% over the shipped 2012–2026 window at 2%/yr, not the `cost * gross` cross
  term the module docstring claims. The probe confirms the ledger stayed flat through the
  dividend fixture while the return series moved +5.26%.
- `quality_flags.missing_forward_prices` is assigned `forced_exits` (`engine.py:782`) —
  the same counter twice, not an independent measurement.
- `config.py`'s `delisting_haircut` comment labels the 0.0 default "the
  CONSERVATIVE-for-reported-performance setting" and then, in the same sentence, says it
  "understates the loss a real forced liquidation might take". Those contradict, and the
  packet says >0 is the conservative setting. The label is wrong in the adverse direction.
- `quantlab_git_sha` is captured with no dirty-tree flag. M04 ran from an uncommitted
  working tree, so the recorded sha names a commit that does not contain the code that
  produced the result.
- A strategy can call `ctx.prices_for_returns()` on its own decision context and receive
  `adj_close` plus raw OHL — verified directly. Inherited from M02/M03, not introduced
  here, and canary (i) is honest that it only asserts the engine never hands over a
  separate accounting-path context. The adj_close-out-of-signals guard is therefore
  convention plus per-plugin canaries, not construction.
- A single missing vendor bar at a fill date is treated as a forced exit. It is recorded
  rather than silent, so it is acceptable, but it is a permanent exit on what may be a
  one-day halt.

## What is needed to move to ACCEPT

Findings 1–4 are corrections to the accounting, each with a named remedy and each
needing a test that fails before the fix. Finding 5 may be resolved either by fixing the
return basis or by an honest rename plus documentation — orchestrator's call. No packet
requirement is itself methodologically wrong, so this is another loop iteration, not an
ESCALATE-TO-HUMAN.
