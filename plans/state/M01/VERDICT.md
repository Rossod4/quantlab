VERDICT: ACCEPT

# M01 Quant-Gate Verdict — Data layer I (interfaces, cache, quality, prices + constituents)

Code review reached APPROVE (REVIEW.2.md). This gate reviews methodological
soundness only. All four focus areas hold up; the milestone makes it harder,
not easier, to fool ourselves. Two carried-forward notes for M02 and two
minor observations are recorded below — none block acceptance.

## Verification (gate-executed)
- `python -m uv run pytest tests/ -q` → 76 passed, 3 deselected (network tier). Matches HANDOFF.2.md.
- `python -m uv run ruff check` → clean (only the harmless removed-rule PD901 warning).
- Two adversarial probes of my own (below) both confirmed the guards fire.

## Focus area (a) — As-of constituents semantics: SOUND, no look-ahead
`_membership_from_table` resolves membership via `table.index.asof(date)`, which
by construction returns the last change-row label `<= date`. Equality is
inclusive and future rows are unreachable.

Adversarial probe (shifted the boundary, per my operating manual) against
`tests/fixtures/constituents_slice.csv`, where TSLA's row is dated 2020-09-21:
```
2020-09-20  TSLA in? False | NVDA in? False
2020-09-21  TSLA in? True  | NVDA in? False   <- appears exactly on the effective date
2020-09-22  TSLA in? True  | NVDA in? False   <- 2023 NVDA row never leaks backward
```
Between-rows (asof 2019-01-01 → the 2018-06-07 row, TSLA excluded) and
before-first-row (`ValueError`, matching the old repo) are both covered by
committed tests and re-confirmed. No path lets a rebalance on `t` see an index
change recorded after `t`.

- Announcement-vs-effective dating: the fja05680 community CSV keys on the
  change/effective date, and the module docstring already documents that these
  dates are best-effort and "may be slightly imprecise" and that the latest
  weeks may lag. That is a data *precision* limitation, not a look-ahead bug —
  imprecise-but-not-future dating cannot manufacture look-ahead here because the
  lookup only ever reads rows `<= asof`. Acceptable and honestly disclosed.
- Ticker-normalization collisions: `normalize_ticker` is `replace(".", "-")`,
  applied only to the *output* list, never to the index used for the as-of
  lookup. A hypothetical collision (two dataset symbols mapping to one Yahoo
  symbol) would at worst produce a duplicate entry in the returned list — it
  cannot alter which change-row is selected and so cannot leak membership. No
  methodological exposure.

## Focus area (b) — Delisted "known empty range" cache metadata: no future leak; one coverage hazard to carry to M02
The sidecar meta records the *requested* range at write time, so a ticker whose
data legitimately stops early (delisted) is treated as fully cached instead of
being re-fetched forever. Two questions from the packet:

1. *Can it leak future knowledge of a delisting into an earlier backtest date?*
   No. `YFinancePriceProvider.get_prices` trims the assembled panel to the
   requested `[start, end]` window (yfinance_prices.py:152), and this trim is
   load-bearing. Adversarial probe: seeded a GONE cache running to 2015-06-30
   with meta requesting through 2026, monkeypatched `_download_batch` to raise,
   then requested only `[2012-01-01, 2012-12-31]`:
   ```
   rows: 260  min: 2012-01-03  max: 2012-12-31   no post-window leak: True
   ```
   The 2013–2015 rows the cache holds are not returned, and no re-fetch occurs.
   A strategy dated 2012 sees no hint that the name later delisted. The only
   thing the metadata stores is the requested range, which is never exposed to
   strategy code.

2. *Can it mask genuinely missing data?* Yes, in one direction, and this is the
   real (non-blocking) hazard: the metadata cannot distinguish "data ends here
   because the name delisted" from "the vendor returned a truncated response
   this one time." If a transient truncation is written to cache, the meta
   freezes that truncation as "complete" and later runs never re-fetch the data
   that genuinely exists — permanently, until the cache dir is deleted. Note the
   asymmetry that keeps this out of blocker territory: it can only ever *drop*
   later data, never inject future data into an earlier date, so it cannot
   directly inflate an earlier backtest via look-ahead. But a wrongly-truncated
   name that subsequently crashed would be dropped from later dates, which is a
   survivorship-flavoured coverage gap.
   → Carry to M02: `data/survivorship.py`'s coverage-gap bound (CLAUDE.md
     invariant 2) must be able to see and surface caches that end well before
     the requested end without a corroborating delisting event, so a frozen
     truncation shows up as measured coverage loss rather than a silent drop.
     M01's cache layer is a correct, no-look-ahead building block; the masking
     risk lives at the survivorship layer that consumes it.

## Focus area (c) — Long panel exposing both raw close and yfinance adj_close
`adj_close` is look-ahead-contaminated by construction: today's split/dividend
adjustments are baked back into every historical bar, so its level and its
day-over-day return at date `t` embed information not knowable at `t`. In M01
this is harmless in practice — providers are never handed to strategies (the
interfaces docstring and CLAUDE.md invariant 1 are explicit), and the only M01
consumer of `adj_close` is `QualityGate`, which uses it to *flag* data, not to
generate a signal. So there is no live exposure this milestone.

The hazard is entirely forward-looking and reaffirms the existing QUANT-NOTES
M02 item:
→ M02: `PITDataContext` must NOT expose `adj_close` for decision-making —
  either adjust as-of `asof`, or reserve `adj_close` strictly for return
  accounting and never feed it to signals. When M02 wires this, extend a bias
  canary (tests/canaries/) that fails if a strategy can read `adj_close`.

Minor, non-blocking: the `PriceProvider` docstring (interfaces.py:38-40)
describes `adj_close` neutrally ("pick the one it needs") without warning that
it is look-ahead-contaminated. Consider a one-line caution there so an M02
implementer does not naively route it into signal code. Not required for M01.

## Focus area (d) — Quality-gate semantics: SOUND
- Outlier rule: single-day `|adj_close.pct_change()| > 0.5` (threshold
  configurable). Using *adjusted* close means ordinary splits are already
  netted out and won't false-flag, while an unadjusted action slipping through
  still trips. Criterion 5 (+60% flagged, +10% not) passes. `adj_close` for
  quality flagging is fine — it is not a signal.
- OHLC sanity (from the M00→M01 carried note): `low <= open/close <= high`,
  `volume >= 0`, strictly positive prices; individual rows flagged, and
  `DataQualityError` raised only when *every* row fails (wholly-corrupt input) or
  required columns are missing. This is the right split between "flag a bad
  print" and "reject a corrupt response." The M00 gate's OHLC-sanity request is
  closed.
- Duplicate `(date, ticker)` rows are flagged `duplicate_row` and the outlier
  scan runs on the first-occurrence-only frame via `pivot` (raises on dupes)
  rather than `pivot_table` (which would silently average) — the anti-silent-
  averaging invariant is structural, not conventional. Good.
- Methodological note (non-blocking): `pct_change` on the wide pivot spans any
  missing-trading-day gaps, so a genuine multi-session move across a gap can be
  reported as a single-day outlier. This matches the frozen old-repo behaviour,
  and because the gate flags rather than drops, it is conservative (a caller
  records the flag; nothing is silently removed). Acceptable as-is; worth a note
  if M03 ever acts on flags automatically.

## Acceptance-criteria methodological confirmation
Criteria 2 (no-look-ahead as-of membership, incl. between-rows and before-first),
4 (delisted no-refetch + exact round-trip), and 5 (outlier threshold sensitivity)
are the methodology-bearing ones; all verified green this run and by the two
adversarial probes above. Criteria 1, 3, 6, 7 re-confirmed by the passing suite.

## Carried-forward to QUANT-NOTES (for the M02 packet to address)
1. M02 survivorship coverage-gap must surface caches that end before the
   requested end without a corroborating delisting, so a frozen vendor
   truncation registers as measured coverage loss, not a silent drop. (from (b))
2. M02 `PITDataContext` must not expose `adj_close` to signal code — adjust
   as-of or reserve for return accounting; add a bias canary. (reaffirms the
   existing M00→M02 note; also consider strengthening the `PriceProvider`
   docstring caution.) (from (c))
