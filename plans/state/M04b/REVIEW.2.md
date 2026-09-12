REVIEW: APPROVE

## Verification performed (iteration 2, after quant-gate VERDICT.md REJECT)

- `uv run pytest tests/ -q`: exit 0, 491 dots (was 444; +47 new tests, matches handoff).
  `uv run ruff check`: All checks passed. `uv run ruff format --check`: 81 files formatted.
- `git diff --stat` matches `HANDOFF.2.md`'s file list exactly; `git status --short` before
  and after my checks is identical (no mutation testing was needed this iteration - the
  files I mutation-tested in iteration 1, `pit.py`/`panel_store.py`/`adjustment.py`, are
  untouched by this iteration's diff, confirmed byte-identical to the diff I already
  verified: `adjustment.py`'s diff hash and content are unchanged).
- 664 parquet files present, matching pre-gate count; no writes occurred under `data/`
  from any command I ran (I only read files or copied the cache to a scratch tempdir).

### Finding 1 (negative cache masking real data) - fixed, verified independently

`has_sufficient_price_cache` now checks quarantine, then a real non-empty parquet, and only
falls through to a `no_data` sidecar when there is no usable parquet at all;
`yfinance_prices.py` guards every `write_price_cache_no_data_meta` call with
`read_cache(...) is None` first. I scanned the entire live shared cache directly: zero
tickers have both `no_data: true` and an on-disk parquet, and every quarantined ticker
still has its parquet (query run against all 826 sidecars). The gate's exact repro is now a
regression test (`test_transient_empty_download_never_overwrites_a_healthy_tickers_sidecar`).

### Finding 2 (quality scan / quarantine) - implemented and independently reproduced byte-for-byte

I copied the real `data/cache/{prices,actions}` to a scratch directory and ran
`scan_price_cache` myself, cold, from a fresh Python process with membership history from
the real `SP500CommunityConstituentsProvider` - not the developer's own run. Result: **47
quarantined, identical set** to what's recorded in the live cache's sidecars (no missing,
no extra). Spot checks, all against real data, not fixtures:
- APC/FB/SPLS/EA: flagged (`symbol_reuse_new_listing`), confirmed via a direct call to
  `symbol_reuse_new_listing_reason` with the real membership start, first cached bar, and
  requested_start for each.
- AMTM/SNDK/IBM/MSFT/JNJ: not flagged, confirmed the same way (IBM/MSFT/JNJ's first bar
  sits exactly at the cache's own 2010-06-01 floor; AMTM/SNDK's first bar predates their own
  membership start).
- GR: quarantined via `symbol_reuse_across_gap`, not the new-listing check (its first bar
  equals `requested_start` exactly) - correctly caught by the other detector.
- Padding-aware zero-volume: EA/EQR are flagged only for reuse, not zero-volume (padding
  exclusion fixed); FERG/AMCR are not quarantined at all; CCE/MHS still fire at 100%
  zero-volume over real bars.
- The ≥3-jump rule: KDP is not quarantined at all (single event); MI/POM/STI are
  quarantined only via the reuse detector, never via a jump count; BMC/CBE/TIE/PTV/CPWR/MEE
  all retain `unexplained_price_jump` with counts of 5-329, all ≥3.
- I independently recomputed the final one-liner from raw artifacts, not the handoff's
  prose: `net_equity.parquet` in `timed_run_out6/` gives CAGR=17.66%, maxDD=-23.25%
  (my own calculation from the equity curve); `coverage_report.json`'s `overall_bound` is
  28.37% (≈28.4%); `provenance.json` shows `run_seconds=510.42`, `quarantined_count=42`,
  `masked_start_count=0`. All match the quoted one-liner exactly.

**One thing the gate should weigh, not a code defect:** `scan_price_cache` and
`heal_or_flag_new_listings` still have no automatic caller anywhere in `src/` - they were
run manually against the shared cache this iteration (disclosed plainly in HANDOFF.2's
deviations). The *enforcement* of an existing quarantine verdict is genuinely wired into
the read boundary (`has_sufficient_price_cache`, `price_availability_from_cache`), but the
*detection* pass is not automatic on every backtest run or every fresh download - it is a
periodic/manual audit, consistent with the gate's own alternative ("split finding 2 into
its own packet... M04b can be accepted on findings 1 and 3 alone provided the number is
withdrawn"), except here the number was corrected rather than merely withdrawn. Whether
that satisfies "wire into the ingestion boundary" as originally worded is a gate policy
call, not a correctness bug - flagging for the gate's attention.

### Finding 3 (unscored) - fixed and directly regression-tested at the engine level

`TargetWeights.unscored` is additive and defaults to empty; `momentum.py`/`value.py` each
report only names they could not score, with tests for every distinct failure reason
(missing price, missing shares_outstanding, insufficient fundamentals for momentum/value
respectively); `blend.py` unions children's `unscored`. `engine.py`'s
`_EqualWeightStrategy` fixture now self-reports its excluded names (no engine-side
inference at all), and a new negative-regression test,
`test_unscored_by_date_does_not_flag_names_merely_not_selected`, directly reproduces the
gate's exact scenario (a top-N strategy over a larger universe) and asserts
`unscored_by_date == {}`. I confirmed by reading `engine.py` that the old
`declared - weights.keys()` inference is gone, not merely superseded.

### Cross-cutting checks

- `masked_start` (survivorship.py) is wired into `coverage_gap` and `price_availability_
  from_cache`; `provenance.masked_start_count`/`masked_start_tickers` and
  `provenance.quarantined_count`/`quarantined_tickers` are present, and both `known_caveats`
  code paths exist (I found both messages in `engine.py`, and confirmed at least one fires
  correctly in the final run's provenance - the other's precondition, `masked_start_
  tickers` non-empty, is legitimately false for this run's own [2012, 2026] window, so it
  correctly does not appear).
- Frozen numerics / canaries: `adjustment.py`, `pit.py`, `panel_store.py`, `calendar.py`
  are untouched by this iteration's diff (confirmed identical to the diff I already
  verified in iteration 1, including a byte-for-byte check of `adjustment.py`'s diff);
  `tests/parity/` is still untouched and passing.

## Findings

1. (minor, non-blocking) `src/quantlab/backtest/engine.py`'s docstring justifying why
   `unscored_by_date` stays a separate `quality_flags` entry cites "REVIEW.md finding 5,
   iteration 2" - no `REVIEW.md` I have access to (mine, iteration 1) has a finding 5 on
   this topic, and I could not find this exact rationale in `VERDICT.md` or
   `plans/QUANT-NOTES.md` either (the closest QUANT-NOTES.md item is about a different
   milestone's reporting duplication). Likely an internal design note mislabeled with a
   citation that doesn't resolve. Fix the citation or drop it; the reasoning itself is sound.
2. (minor, non-blocking) `tests/test_quality.py::test_membership_start_by_ticker_takes_
   the_earliest_appearance` only exercises tickers with a single, unbroken membership span,
   so it cannot distinguish "most recent span start" from "earliest-ever appearance" - the
   exact distinction `membership_start_by_ticker`'s docstring says the function exists to
   get right (the SNDK/old-vs-new-company case). The implementation is correct by
   inspection (it overwrites `starts[ticker]` on every fresh appearance, so a later span
   wins), and I confirmed it empirically against real data (SNDK's real membership_start
   resolved to its 2025 re-entry, not its pre-2010 original listing, in my independent
   re-scan). Still, add a synthetic test with an actual gap (present, absent, present again)
   to lock this in directly.

No blockers. All three quant-gate findings are fixed and independently reproduced against
real cache data and real run artifacts, not just re-read from the handoff's prose.
