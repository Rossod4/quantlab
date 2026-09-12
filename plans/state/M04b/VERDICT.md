VERDICT: REJECT

# M04b quant gate — cycle 1

Scope: `plans/M04b-engine-perf.md`, `plans/state/M04b/HANDOFF.md`, `REVIEW.md`, the
M01/M02b/M04 carried items in `plans/QUANT-NOTES.md`, and the real-run artifacts
(`timed_run.log`, `timed_run_out2/`).

Tree at gate time: 444 tests pass, `ruff check` clean. All 92 tracked `.py`/`.yaml` files
are md5-identical to my pre-gate baseline — no repo file was mutated by this gate, nothing
under `data/` was touched or deleted, and no `git stash` was run. Every probe ran from the
session scratchpad. I worked only in this worktree.

The engineering here is good and most of it verifies cleanly, including the two things I
would most expect to break: the panel store is genuinely untrusted, and the perf changes
to frozen numerics really are numerically inert. The rejection rests on three findings, one
of which this milestone introduced and two of which it is the first to expose with real
data.

---

## Blocking findings

### 1. The negative price cache can mask a ticker's REAL cached data, and survivorship then reports that ticker as fully covered

**Attribution: introduced by this milestone.** The packet's item 3 claims to close the M01
frozen-transient-failure hazard with a TTL. It closes the *permanent* freeze and opens a
new, silent 30-day one.

**Risk.** A live index member disappears from every strategy's view while
`price_availability_from_cache` reports `has_data=True, masked_end=None` — full coverage.
The selection effect is neither measured nor surfaced, which is CLAUDE.md invariant #2.

**Evidence.** `data/providers/yfinance_prices.py:130` calls
`write_price_cache_no_data_meta` unconditionally when a ticker comes back with no rows
inside an otherwise-successful batch, and `write_json_meta` replaces the sidecar wholesale.
`data/cache.py`'s `has_sufficient_price_cache` then checks the `no_data` branch *before* it
ever looks at the parquet file, and returns an empty frame.

Reproduced on a ticker with 14 years of good cached data:

```
1. healthy cache      -> rows=3781   (real data served)
   sidecar now: {'no_data': True, 'fetched_at': ..., 'requested_start': '2012-01-01', ...}
   parquet still on disk: True, 3781 rows
2. after ONE transient empty download -> rows=0
3. survivorship sees: has_data=True last_bar=2026-06-30 masked_end=None
```

A whole-batch failure correctly writes nothing, so the exposure is the per-ticker empty
result inside a successful batch — which is exactly what yfinance returns for a
rate-limited or partially-failed multi-ticker download, the reason this provider throttles
at all. The condition that triggers a re-fetch of already-good caches is also real and was
hit during this milestone's development: the handoff records that a calendar-day-sized
warmup window "landed outside the shared cache's actual prefetched range and triggered a
mass re-fetch". A mass re-fetch during a vendor blip would blank a large fraction of the
universe for 30 days with the coverage bound reporting nothing.

**Currently latent, not realised.** I counted the shared cache: 826 price sidecars, 162
`no_data`, and **zero** sitting on a non-empty parquet. So this did not move the 17.84%
number. It is a trap, not a present error.

**Remedy.** Honour the `no_data` branch only when there is no usable parquet — fall through
to the existing cache otherwise — or do not write the sidecar when a parquet already
exists. Add a test that a healthy cache survives a transient empty download. If the
masking is ever deliberate, it must set `masked_end` so survivorship counts it.

### 2. `data/quality.py` has no production caller, so no ingestion validation runs — and the first real run ingested demonstrably corrupt price series that reached the book

**Attribution: not introduced here.** This is the M00→M01 carried item ("enforce at the
ingestion boundary (quality.py), raising/flagging via `DataQualityError`"), still open. But
M04b's acceptance criterion 5 is what makes it a finding now: it requires the run's
differences from the old repo to be explained, and says "anything else is a finding".

**Evidence.** Every `quality` reference in `src/` is either `quality_flags` (the engine's
unrelated counters) or a docstring. `QualityGate` is exercised only by
`tests/test_quality.py`. Neither `providers/yfinance_prices.py` nor `data/pit.py`
references it. The OHLC-sanity and outlier scans that would catch the below are dead code
on the real path.

Yahoo reassigns delisted tickers to unrelated instruments. The platform requests a
delisted S&P constituent by bare symbol and caches whatever currently trades under it.
From the shared cache, with two genuinely expensive stocks as controls:

| ticker | reality | cached close min / median / max | zero-volume bars | order-of-magnitude buckets |
|---|---|---|---|---|
| PTV | Pactiv, acquired 2010, ~$33 | 0.01 / 22,500 / 1,330,000 | 47.7% | 7 |
| BMC | BMC Software, private 2013, ~$45 | 532 / 13,300 / 30,050 | 23.2% | 3 |
| TIE | Titanium Metals, acquired 2012, ~$16 | — / — / 28,200 | — | interleaved |
| NVR | genuinely ~$3,000/share | 575 / 2,847 / 9,924 | 0.0% | 2 |
| AZO | genuinely ~$790/share | 186 / 790 / 4,355 | 0.0% | 2 |

The controls are clean and continuous; the contaminated ones are not. TIE's January 2012
rows interleave real ~$16 bars at ~1.7M volume with ~$7,000–8,200 bars at ~11,000 volume
and 1.40 bars at zero volume — at least three instruments under one symbol. BMC's cache
runs to 2022 for a company taken private in 2013.

These reached the portfolio. `holdings_history.json` shows TIE held on 2012-01-31 and
2012-06-29 and BMC on 2013-08-30. TIE entered the very first book at an `avg_cost` of
8,200 on a January momentum move of 7,000 → 8,200, a fabricated signal from a fabricated
instrument, and its return is inside the quoted 17.84% CAGR.

The bias direction is uncontrolled and it is concentrated in precisely the delisted names
this platform added delisting machinery to handle.

**Remedy.** Wire `QualityGate` into the price ingestion boundary and add two checks it
does not have: a zero-volume session on a date the calendar calls a session (a listed US
equity essentially never has one), and an adjacent-session close ratio beyond a threshold
that no split in the gated actions history explains. Then re-scan the shared cache, quarantine
the affected tickers, and do not quote a headline number until that scan is recorded.

### 3. `quality_flags.unscored_by_date` conflates "not selected" with "could not be scored", which makes the guard it implements undetectable at real scale

**Attribution: the mechanism is M04's, unchanged here.** It only became visible with a
real selective strategy; every M04 engine test used a strategy that holds the whole
universe.

**Evidence.** The engine records `ctx.universe()` minus `targets.weights.keys()`. For a
top-30 momentum book on a ~500-name universe that is everything not selected:

```
unscored_by_date: 173 rebalance dates, 467-476 names each (median 473)
holdings per rebalance: 30
```

Roughly 82,000 entries across the run. The M03-verdict item this exists for — surface the
value leg's silently dropped unpriceable names — cannot be read out of that. A handful of
genuinely unscoreable names is indistinguishable from 473 merely-unselected ones.

**Remedy.** Record only names the strategy could not score, which means the strategy has to
say so rather than the engine inferring it from a set difference. The additive
`TargetWeights.unscored` field the M03 verdict already contemplated is the natural place.
Failing that, at minimum stop calling this a quality flag and rename it, so nothing
downstream reads it as a data-quality signal.

---

## Verified clean

**Panel store (item 2, item 4, acceptance criterion 6).** Genuinely untrusted. A hostile
store carrying 208 rows dated after `asof`, with poisoned 999.0 prices:

```
provider vs clean-store prices() identical: True
provider vs HOSTILE-store prices() identical: True
max date the strategy could see: 2020-01-31 | asof: 2020-01-31
any poisoned 999.0 value reached the strategy: False
adj_close in decision-path prices(): False
prices_for_returns on decision ctx: raised UndeclaredDataError
accounting path provider vs store identical: True
```

The store substitutes only the `source.get_prices(...)` line in `_sliced_price_panel`; the
hard slice and `_assert_no_future_dates` run unchanged after it, and the actions store goes
through the same gate. The accounting panel cannot leak into a decision context: both read
the same store, but `prices()` still strips `adj_close` and applies the adjustment replay,
and the M04 `accounting` gate still raises.

I also A/B-tested the whole engine, store-backed against a store forced to know nothing so
every lookup falls back to the provider:

```
gross_returns / net_returns / net_equity / benchmark_returns / turnover
  index_equal=True   max_abs_diff=0.000e+00   (all five)
holdings identical: True
```

Bit-identical. The store changed no result.

`_benchmark_returns` is the one price access that bypasses `PITDataContext` entirely, and
it carries its own explicit lookahead assert. I confirmed it fires — my first A/B attempt
tripped it with a full-panel fallback provider and it raised `LookaheadError` naming 22
offending rows rather than silently using them.

**Frozen numerics (item 4).** The working tree differs from `main` by exactly three
non-comment lines, all hoisting `to_numpy()` out of the per-ticker loop. I ran my own
randomised differential, 4× the reviewer's:

```
trials=1200  distinct (n_tickers,n_rows) shapes=275  mismatches=0
raised-identically=2
RESULT: BYTE-IDENTICAL (frozen numerics preserved)
```

Adversarial shapes included duplicate ex-dates carrying both action types, splits and
dividends on the same day, single-row tickers, NaN closes, unsorted panels, and varying
ticker orderings. Two trials made both versions raise `DataQualityError` with identical
messages. `raw_arrays` cannot go stale because `result`'s columns are written only after
the loop, and both versions copy rather than alias.

**Actions read-memo.** The staleness check is untouched — it re-evaluates per call with
that call's own `end`. Probed directly: warming the memo with a fresh call then asking
beyond `fetched_at` still raises `StaleActionsCacheError`, and after an out-of-band sidecar
refresh the same instance self-heals and serves. The memo can only err toward raising a
staleness error a re-read would clear, which is the conservative direction.

**Calendar bounds (item 3).** Pinned to the literals 1990-01-01 and 2040-12-31, with no
wall-clock input. Three clock reads remain in `src/`: `run_timestamp` in provenance
(benign, it records when the run happened), the actions-staleness `_today()` (pre-existing,
M02b, documented), and the new negative-cache `_today()` — see the carried item below. The
window clamp is correct and, for a 2012–2026 run with lookbacks under 400 sessions, never
binds.

## Item 5 — the first real number

**I have not reconciled 17.84% against the old repo's 15.7%; that is M09's job.** On what
this packet can and cannot explain:

- **Window clamp: cannot have moved it.** It only binds when a request reaches before
  1990; the widest lookback here lands in 2010.
- **Benchmark from the store: cannot have moved net CAGR.** It changes only the benchmark
  series, and the engine A/B above reproduced `benchmark_returns` bit-identically anyway.
- **Negative cache: could have, but did not.** It is the one mechanism here that can remove
  a live name from a strategy's view (finding 1), and zero of the 162 `no_data` sidecars
  currently sits on a non-empty parquet.
- **Finding 2 definitely moved it**, by an amount nobody can currently state, and that is
  not this packet's doing.

**Coverage bound 22.3% needs no explaining — it is consistent with the old repo's 12.6%
once the statistic is matched.** The per-year series declines monotonically from 22.33% in
2012 to 0.99% in 2026, which is the expected signature of delisted names accumulating as
you go back in time. Its mean is 11.73%, within a point of the old repo's 12.6% no-price
gap. The 22.3% is the worst single year, which is exactly what the M04 verdict defined
`overall_bound` to be. `masked_tickers` is empty in every year, consistent with the ~150
absent names having no parquet at all rather than a metadata-masked one.

## Non-blocking, carried

- **The negative-cache TTL makes a run's data visibility wall-clock dependent, and nothing
  records it.** The same config run today and in 31 days can see different tickers.
  `retry_after_days` does not appear in provenance, nor does any count of tickers suppressed
  by a live `no_data` sidecar. This milestone pinned the calendar for exactly this
  reproducibility reason and then introduced a new today-dependence a layer down. Record
  both in provenance.
- My M04 carried item asking for a dirty-tree flag is discharged: `provenance.dirty` is
  present and reads `True` for this run. `run_seconds` (556.2 s... recorded as 557.19) is
  present as required by item 6.
- Timing: 9m19s against a 10-minute bound and a 3-minute target. Within the acceptance
  criterion. The remaining cost sits in `apply_asof_adjustment`'s per-ticker loop, correctly
  left alone as frozen numerics.

## What is needed to move to ACCEPT

Finding 1 is a small, contained code change plus a test. Finding 3 is a scoping change to
one quality flag. Finding 2 is the substantial one and may warrant its own packet rather
than another M04b iteration — wiring `QualityGate` in, extending it with the two checks
above, and re-scanning the shared cache is data-layer work, not engine work. If the
orchestrator splits it out, M04b can be accepted on findings 1 and 3 alone **provided the
17.84% number is withdrawn from circulation until the scan exists** — it is currently a
number with known-corrupt inputs in its first book, and a referee would ask about TIE.
