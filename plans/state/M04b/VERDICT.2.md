VERDICT: ACCEPT

# M04b quant gate — cycle 2

Scope: developer iteration 2 (`plans/state/M04b/HANDOFF.2.md`), `REVIEW.2.md`, the three
cycle-1 findings, the review's policy question, and the corrected real run
(`timed_run_out6/`).

Worktree at gate time: 491 tests pass, `ruff check` and `ruff format --check` clean. All 92
tracked `.py`/`.yaml` files are md5-identical to my pre-gate baseline — no repo file was
mutated by this gate. Nothing under `data/` was written or deleted; every cache access below
was read-only, and the network-touching probe asserted on any download attempt rather than
making one. No `git stash`. I worked only in this worktree.

All three cycle-1 findings are fixed, each re-verified by re-running my original
reproduction unchanged. The quality work in particular is better than what I asked for: the
detector survives adversarial probing in both failure directions, and the coverage bound got
*worse* because the measurement got more truthful, which is the right direction for this
platform.

---

## Cycle-1 findings, re-probed

**Finding 1 — negative cache masking real data. FIXED, both layers.**

My cycle-1 reproduction, unchanged: a ticker with 3,781 real cached bars now serves all
3,781 after a `no_data` sidecar is forced on top of it, against 0 at cycle 1.
`has_sufficient_price_cache` checks the parquet before the sidecar. I also tested the
write side, which my cycle-1 probe did not reach: forcing a re-fetch that comes back empty
on a ticker that already has a parquet leaves the sidecar's `no_data` flag **absent**, and
the parquet intact. Both layers hold independently.

**Finding 2 — QualityGate wired in. FIXED, and the detector holds under adversarial probing.**

Enforcement is automatic and total at the read boundary. Probed offline, with
`_download_batch` replaced by a function that raises on any call:

| ticker | state | parquet rows | rows served |
|---|---|---|---|
| TIE | quarantined | 2,237 | 0 |
| EA | quarantined | 6 | 0 |
| PTV | quarantined | 1,602 | 0 |
| IBM | clean | 4,095 | 1,131 |
| AAPL | clean | 4,095 | 1,131 |
| NVR | clean | 4,095 | 1,131 |

No network attempt for any of them. A quarantine verdict cannot be bypassed.

The membership-reuse detector is the part most likely to do damage if wrong, so I probed
the function directly rather than trusting the shipped verdicts. Eleven synthetic boundary
cases, all matching expectation:

- Long-standing constituents whose first bar sits **at** the cache's own 2010-06-01 floor
  (IBM, MSFT, JNJ patterns) — never flagged, because the check requires the first bar to
  exceed the sidecar's `requested_start` as well as membership start. This is the fix for the
  round-2 over-flagging and it is the correct one.
- A genuine new member whose data starts just before joining, and one with a 22-session gap
  after joining — never flagged.
- A 399-session gap — clean; 400 — flagged. The tolerance boundary is exact and sits at
  roughly nineteen months, which is a sane place for it.
- EA-like and EQR-like reuse — flagged.
- Missing `requested_start` or missing membership — silent. Conservative, and it motivates
  a carried item below.

Against the real cache, both directions again: every long-standing large cap I checked
(IBM, MSFT, JNJ, AAPL, XOM, PG, KO, JPM), the benchmark SPY, and the three genuinely
high-priced names my own cycle-1 price threshold falsely flagged (NVR, AZO, FICO) are all
clean with first bars exactly at the floor. The two genuine recent listings (SNDK
2025-02-13, AMTM 2024-09-24) are clean despite late first bars. Every confirmed reuse case
is quarantined. Note the division of labour works: TIE, BMC and PTV have *early* first bars
and were caught by the price-arithmetic detectors, not the membership one.

47 tickers quarantined cache-wide, 42 in the run's tracked universe, matching the handoff.

On the round-2 operational mistake, which I checked because the repair was manual: the
cache is now self-consistent. 664 parquet files, 826 sidecars, **zero** parquets without a
sidecar and **zero** sidecars missing `requested_start`. The only two distinct requested
ranges are `2010-06-01→2026-09-11` (601) and `→2026-09-12` (63), the difference being the
healing re-fetches run a day later. Nothing was lost.

**Finding 3 — unscored vs not-selected. FIXED.** `unscored_by_date` now runs 8 to 157 names
per rebalance with a median of 87, against 467–476 with a median of 473 at cycle 1. The wide
spread across dates is itself the evidence that it is now measuring something rather than
computing a set difference.

## The policy question — ruled: the split satisfies my finding, and is the better design

The review asks whether detection having no automatic caller satisfies "wire into the
ingestion boundary". It does, and I would not want it otherwise.

The property that matters is that corrupt data cannot reach a book unnoticed. Enforcement
delivers that: it is automatic, total, offline-proof, and it fails closed. Detection is a
different kind of operation — a full-cache pass that needs a point-in-time membership
provider and, in the healing path, live network access. Running that on every backtest would
be slow, would make results depend on when the scan happened to run, and would put a network
dependency inside a run that is supposed to be offline and deterministic. A disclosed manual
pass with `quantlab data scan` scheduled in M09 is the right shape.

There is one residual, and it is narrow. `checked_at` is stamped only on quarantined
tickers — 47 of them — so 779 clean tickers carry no scan marker at all. A cache that has
**never been scanned** is therefore indistinguishable from one scanned and found clean, and
`provenance.quarantined_count` would read 0 in both cases. That does not affect this run,
whose scan is documented and whose 42 quarantines are in provenance, but it is the third
time in this project that a guard has existed without a way to tell whether it ran. Carried
to M09 as a must-fix with a one-line remedy.

## What moved 17.84% to 17.66%

Nine quarantined names were held in the withdrawn run, across 22 name-rebalances out of
5,190 — 0.42% of all position-periods:

```
HAR 4, FOXA 4, COL 3, FOX 3, TIE 2, SCG 2, IR 2, CBE 1, BMC 1
```

TIE and BMC, the two names I identified by hand at cycle 1, are among them and are now out
of the book. A 0.18 percentage-point CAGR reduction from removing 0.42% of position-periods
is a proportionate magnitude, and the direction is down — which is what you expect if the
contaminated series were manufacturing spurious momentum winners. That is a consistency
check on the fix, not a reconciliation; the 17.66%-versus-15.7% comparison remains M09's.

## Coverage bound 28.4% — what it now means

The per-year series declines monotonically from 28.37% (2012) to 2.2% (2026), mean 14.68%,
against 22.33%/11.73% before the scan. The rise is the 42 quarantined names now counting as
lacking coverage instead of reading as fully covered. **The bound got worse because the
measurement got more honest**, which is exactly what CLAUDE.md invariant #2 exists to
produce, and it is reported rather than suppressed.

Its meaning has widened and the report says so. It is now: the worst single calendar year's
percentage of that year's point-in-time index members, sampled at the last rebalance date in
that year, whose cached price data is unusable — where unusable covers three distinct
causes, not one. The report keeps them separable rather than folding them into an
undifferentiated number: `quarantined_tickers` (30 in 2012), `masked_tickers` (0) and
`masked_start_tickers` are each carried per year, and `provenance.quarantined_count` (42)
and `masked_start_count` (0) are recorded with a `known_caveats` entry stating the symbol-reuse
cause in plain language. A reader can decompose the 28.4% without re-deriving it.

`masked_start` mirrors `masked_end` correctly and affects zero tickers for this window,
since every gap it is technically true of predates 2012. Implemented and tested for when it
matters.

## Verified clean (re-run this cycle, since engine.py and adjustment.py both changed)

- **Frozen numerics.** `adjustment.py` still differs from `main` by exactly the same three
  non-comment lines. My 1200-trial randomised differential: 275 distinct shapes, zero
  mismatches, two trials raising identical errors on both sides.
- **Panel store untrusted.** A hostile store with 208 post-asof rows carrying poisoned
  prices still produces output byte-identical to the provider path; no poisoned value
  reaches the strategy; no `adj_close` on the decision path; `prices_for_returns` still
  raises on a decision context.
- **Engine A/B.** Store-backed against a store forced to know nothing: `gross_returns`,
  `net_returns`, `net_equity`, `benchmark_returns` and `turnover` all bit-identical,
  holdings identical.
- **Timing.** 8m32s, `run_seconds` 510.42, under the 10-minute bound.

## Carried, non-blocking

`retry_after_days` and the count of tickers suppressed by a live `no_data` sidecar are still
absent from provenance, unchanged from cycle 1 and correctly listed as not addressed. The
M09 force-clear CLI for both sidecar kinds is mechanism-ready (`clear_quarantine_meta`
exists) without a caller. The documented under-detection case — reuse where the new
company's data start closely tracks its own recent index entry — is real, is conservative in
direction, and is noted in the detector's own docstring; it cannot be closed by date
comparison alone and needs a second signal, which is M09 work if it is ever worth doing.

M04b is accepted. The milestone makes it materially harder to fool ourselves than the tree
it started from: 42 corrupt series that previously reached the portfolio now cannot be read
at all, the coverage bound tells the truth about them, and the headline number was withdrawn
and restated rather than defended.
