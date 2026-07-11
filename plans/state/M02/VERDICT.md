VERDICT: ACCEPT

# M02 quant-gate verdict — PIT context, EDGAR fundamentals, survivorship, corporate actions

Acceptance is conditional on carried item 1 below (a HARD pre-M03 sequencing
condition, recorded in plans/QUANT-NOTES.md). If the planner declines to insert
that packet before M03 builds momentum, treat that refusal as ESCALATE-TO-HUMAN —
do not proceed to M03 momentum on the current `prices()` semantics.

## Verification performed
- `python -m uv run pytest tests/` → 141 passed, 3 deselected (network);
  `ruff check` clean. Matches HANDOFF.2; code review (REVIEW.2.md: APPROVE)
  already mutation-tested canaries (a)-(c) against the production guards and
  independently reproduced the NATH fundamentals parity against the old repo.
- Own adversarial checks (scratchpad, not committed):
  1. Misbehaving `CorporateActionsProvider` that ignores `end` and returns a
     future-dated split → `PITDataContext.actions()` excluded it (hard slice
     at pit.py:228 works against a hostile provider, not just a polite fake).
  2. Split hazard quantified: synthetic 10:1 split, true 12-month price return
     0.0% → momentum computed on `prices()` raw close reads **-90.0%**;
     the same ratio on adjusted prices reads exactly 0.0%. The hazard the
     handoff documents is real, catastrophic, and currently unguarded.
  3. EDGAR gate boundary: a fact with `filed == asof` is visible; `asof` one
     day earlier hides it. Day-granularity `filed <= asof` confirmed (see
     carried item 2).

## The central design decision: `prices()` raw vs `prices_for_returns()` adj_close

**Accepted for M02, with a binding condition on M03.** Reasoning:

- The developer took the packet's explicitly sanctioned escape hatch, and took
  it honestly: the decision path is raw OHLCV only, column-gated by a
  module-level constant, adversarially pinned by canary (e) (a fixture with a
  deliberately different adj_close proves nothing leaks), and the split-
  discontinuity limitation is documented in code, module docstring, and
  handoff. Zero look-ahead by construction is the correct property to
  prioritize in the milestone that *defines* the strategy-visible surface.
  Refusing to ship new, unparitized adjustment arithmetic in the platform's
  most safety-critical spot was the right conservatism — an as-of replay built
  this iteration would have had no parity anchor and (until REVIEW.md finding 1
  was fixed) would have sat on a cache that froze transient failures as
  "no splits ever", silently yielding unadjusted prices per ticker.
- But raw-for-signals is NOT tolerable for M03 momentum (option (a) rejected).
  My check 2: a 10:1 split reads as -90% on a flat stock. This is not noise; it
  deterministically flips the sign for every splitter in the lookback, and
  splitters are disproportionately past winners — exactly the names a momentum
  strategy must rank correctly. S&P 500 constituents split regularly; a 12-month
  lookback guarantees several such corruptions at any rebalance. A referee would
  reject any momentum result computed this way, and unlike look-ahead it doesn't
  flatter returns — it silently destroys the signal, which is worse than failing.
- Adjusted-for-signals with a documented bound (option (c)) is rejected as the
  standing solution. The honest technical statement: ratios of globally
  back-adjusted closes ARE point-in-time clean (multiplicative factors for
  ex-dates after the later endpoint cancel — my check 2 shows the adj ratio is
  exact), which is also precisely why `prices_for_returns()` is legitimate for
  return accounting over elapsed periods. But (i) only *ratio* consumers are
  clean — price-level filters and any per-share-fundamental × price combination
  (P/E, P/B — this platform's value leg) are contaminated because pre-split
  filings don't match post-split-adjusted prices; (ii) yfinance recomputes the
  adjusted series retroactively, so signals on it are not reproducible across
  cache refreshes; (iii) it would repeal the platform's simplest bright line
  (strategies never see adj_close — QUANT-NOTES M00/M01, canary (e)) in
  exchange for a convenience. The old repo's use of auto-adjusted prices for
  signals was tolerable only for pure momentum ratios; this platform's stated
  purpose is to be harder to fool than the old repo.
- Therefore option (b): **the as-of adjustment replay (raw close × cumulative
  factor from real split/dividend events with ex-date <= asof) must land as its
  own parity-fixtured packet BEFORE M03 computes any cross-time price signal on
  `prices()`.** Carried item 1 specifies the packet's required contents.
  `corporate_actions.py` (real, independently-ex-dated events, non-poisoning
  cache after the REVIEW.md fix) is the right building block and is already in
  place.

## Other review targets — findings

- **Survivorship `coverage_gap` correctness: sound, with two honesty caveats
  carried to M04** (item 3). The 30%/0% criterion-4 numbers, the zero-member
  year → 0% convention, and the masked-truncation surfacing (QUANT-NOTES M01
  closure) are all correct and pinned by tests; `overall_bound` = worst year,
  not average — right choice. Caveats: (i) membership is sampled at year-ends
  only (the old script sampled quarter-ends), so a name that joined and left
  between consecutive year-ends — precisely a survivorship-critical case — is
  never counted; full-year members missing data ARE counted every year, so the
  undercount is confined to sub-year tenures, but "conservative ceiling" must
  not be overclaimed. (ii) A member with `has_data=True`, `last_bar_date` before
  the reference date, and `masked_end=None` counts as covered — honesty rests on
  the M04 caller populating `masked_end` from the cache sidecar metadata.
- **Delisting inference: conservative in the correct direction.** After the
  REVIEW.md-3 tightening (member as of last trade AND non-member as of end;
  ValueError → None), it can only miss events, never fabricate them, and only
  ever claims UNKNOWN. Residual: when index removal precedes or coincides with
  the final trade (the common S&P sequence), `membership(last_trade_date)`
  already excludes the ticker → no event inferred. Fine for a heuristic, but
  M04's forced-exit invariant (CLAUDE.md #3) must therefore NOT key solely off
  `DelistingEvent` presence — carried item 4.
- **Filed-date gating in the PIT path: correct and verbatim-ported** (parity
  independently reproduced by code review; every extraction helper gates
  `filed <= as_of_date`, restatement dedup keeps latest filed within the gate).
  One day-granularity subtlety carried (item 2): a filing filed ON the decision
  date is visible to a same-day close decision, yet 10-K/10-Qs commonly post
  after 16:00 ET — an intraday look-ahead of hours on filing days. The port
  mandate (frozen numerics) makes M02 the wrong place to change it; M03/M04 must
  decide the convention (evaluate fundamentals at `asof - 1` session, or a
  filing-lag parameter) before results are produced.
- **Canaries genuinely pin the guards.** (a)/(b)/(c) verified by code review via
  production-code mutation (canary (c) now delegates to the real
  `_membership_from_table`); (d)/(e) fail-on-removal by construction; my check 1
  confirms the un-canaried `actions()` path also survives a hostile provider.
  Gap: no *committed* adversarial canary covers `actions()` (test_pit.py's fake
  provider politely honors `end` itself, so it doesn't isolate the production
  slice). Not blocking — the packet's canary list (a)-(e) is complete and the
  slice + LookaheadError assertion are unit-tested — but CLAUDE.md invariant #6
  says extend canaries when adding data paths: fold an actions canary into the
  adjustment-replay packet (item 1), where actions become decision-relevant.
- **QUANT-NOTES closure check (M00/M01 items due at M02):** adj_close gated out
  of the decision path with an adversarial canary — closed. Masked cache ranges
  surfaced in CoverageReport — closed (test_coverage_gap_surfaces_cache_
  metadata_masked_truncation). Defensive copies on every accessor (frames
  `.copy()`, fresh dicts/lists) with canary (d) pinning mutation isolation —
  closed.

## Carried conditions and notes (recorded in plans/QUANT-NOTES.md)

1. **HARD, pre-M03-momentum — as-of adjustment replay packet.** Contents:
   adjusted decision prices = raw close × cumulative adjustment computed ONLY
   from corporate-action events with ex-date <= asof; parity fixtures with
   hand-computed factors for known real sequences (e.g. AAPL 4:1 2020-08-31,
   TSLA 5:1 2020-08-31, plus a dividend sequence); an explicit decision whether
   adjusted prices change `prices()` semantics or arrive via a new accessor —
   made BEFORE M03's Strategy ABC freezes the signature; an actions-path
   adversarial canary; and actions-cache staleness handling (the cache is
   fetch-once-forever — safe for older data, but a cache fetched at T is blind
   to splits after T, which would reintroduce the raw-discontinuity bug for any
   asof beyond T; needs refresh-or-metadata before a long backtest).
   Until this lands, any M03 signal comparing `prices()` values across time is
   a REJECT at this gate.
2. **→ M03/M04:** `filed <= asof` is day-granular; same-day (often after-hours)
   filings are visible to a same-day close decision. Adopt a one-session filing
   lag (or evaluate fundamentals at the prior session) or explicitly document
   and defend the convention in the backtest spec.
3. **→ M04:** before `BacktestResult` embeds `coverage_gap`'s `overall_bound`:
   (i) sample membership at rebalance dates (or at least quarter-ends, matching
   the old script) rather than year-ends, or relabel the bound as
   "worst sampled year-end"; (ii) the `PriceAvailability` constructor must
   populate `masked_end` from cache sidecar metadata, else masked truncations
   go uncounted by design.
4. **→ M04:** forced delisting exits must trigger on "price series ends before
   backtest window" itself, not solely on `infer_delisting()` returning an
   event — the tightened inference deliberately under-detects when index
   removal precedes the final trade.
