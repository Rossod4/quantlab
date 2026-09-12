# M04b HANDOFF.2 — quant-gate cycle 1 (REJECT) fixes

**The previously-quoted 17.84% net CAGR is WITHDRAWN**, and every intermediate number quoted
during this iteration (17.81%, 17.83%) is superseded by **17.66%** below. The cache
contained demonstrably corrupt/reused price series (TIE, BMC and, it turned out, 40 more)
that reached the portfolio; see VERDICT.md finding 2. The final number comes from a cache
the quality scan has quarantined all of them out of.

## Finding 1 — negative cache masking real data (fixed)
`has_sufficient_price_cache` (data/cache.py) checks a REAL, non-empty parquet before ever
consulting a `no_data` sidecar. `yfinance_prices.py` no longer writes `no_data` when a
parquet already exists for that ticker. Regression test reproduces the gate's exact repro.

## Finding 2 — QualityGate wired in; scan run on the shared cache (three review rounds)
`data/quality.py` gained cache-scoped checks plus `scan_price_cache(cache_dir)`, quarantining
via `write_quarantine_meta` (merged, never overwriting positive metadata). Getting this
right took three corrections after the first scan:

**Round 1** (price-arithmetic only) over-quarantined 22 tickers — live large caps (EA, EQR,
FERG, AMCR, COL, HOT, SW, CPWR, ...) purely from yfinance's zero-volume batch-download
padding, plus single-jump corporate events (KDP, MI, POM, STI). Fixed: `zero_volume_fraction`
excludes padding rows (volume=0 AND close repeats the prior row) before computing anything;
zero-volume alone quarantines only above a hard 0.50 bar, the softer 0.20 bar needs an
accompanying implausible price level (20x); `unexplained_jump_dates` excuses a split within
±3 sessions, not only the exact date; jump-based quarantine needs ≥3 dates, not one.

**Round 2** (membership-aware reuse detection) added `symbol_reuse_new_listing_reason`: a
ticker whose cached first bar is much later than its point-in-time index membership start is
presumed to be a DIFFERENT company now trading under a reused symbol (confirmed directly:
Yahoo returns "Data doesn't exist" for EQR/AVB/EA/LEG's pre-2026 history). **First version of
this check compared only to membership start and flagged ~180 tickers** — nearly every
long-standing constituent (IBM, MSFT, JNJ, ...) whose S&P membership simply predates this
shared cache's own 2010-06-01 prefetch floor, a documented, deliberate limitation of the
cache's fetch window, not a data anomaly. **Fixed**: the check now requires the first bar to
exceed BOTH the ticker's own cached `requested_start` AND its membership start (by the same
400-session tolerance) — a ticker whose data starts exactly at the cache's own known floor is
never flagged regardless of how old its membership is. Also fixed `membership_start_by_ticker`
to track each ticker's MOST RECENT contiguous membership span (a symbol that left and was
later reused/re-admitted is dated to its latest span, not its original decades-old entry).
A `heal_or_flag_new_listings(cache_dir, price_provider, ...)` function gives every candidate
one real re-fetch attempt (clearing its sidecar, calling the provider's normal write path)
before trusting the verdict — run once against the real cache: **all 41 candidates came back
`still_late`** (zero healed), confirming Yahoo genuinely has nothing earlier for the current
holder of each of these symbols.

**An operational mistake during round 2**: the first (over-broad) membership scan cleared
~180 tickers' sidecars (to force re-evaluation) before the bug was caught, which lost their
`requested_start`/`requested_end` fields (never their parquet — all 664 price files stayed
present and byte-identical throughout). Repaired by restoring the standard shared-cache
range (`2010-06-01`/`2026-09-11`, confirmed identical across the whole pre-mistake cache) to
every affected sidecar before rescanning with the corrected logic.

**Final scan**: 664 tickers scanned, **42 quarantined** in the momentum backtest's own
tracked universe (47 across the whole cache; 5 — including PTV itself — were never
point-in-time S&P members in the 2012–2026 window). Reasons: `PTV`/`BMC`/`CBE`/`TIE`/`MEE`/
`CPWR` (unexplained price jumps, 5–329 dates), `MHS`/`CCE` (zero-volume, 90–100% of real
bars), `GR` (symbol-reuse-across-a-gap, 4.4x), and 34 membership-based reuse cases (`ADT`,
`APC`, `AVB`, `BBBY`, `BEAM`, `CAM`, `COL`, `CSRA`, `EA`, `EMC`, `EQR`, `FB`, `FOX`, `FOXA`,
`HAR`, `HOT`, `INFO`, `IR`, `LB`, `LEG`, `LIFE`, `MI`, `MMI`, `NE`, `NFX`, `PCL`, `POM`, `S`,
`SBNY`, `SCG`, `SE`, `SHLD`, `SPLS`, `STI`, `SUN`, `TE`, `TEG`). Verified against explicit
negative controls `AMTM`/`SNDK` (genuine new S&P members whose membership start ≈ first
bar — never flagged) and positive controls `APC`/`FB`/`SPLS`/`EA`/`PTV`/`BMC`/`TIE`/`CBE`/
`MEE` (all flagged), both directly against the real cache and via a synthetic end-to-end test.

**Residual, documented limitation**: the membership-timing heuristic cannot catch a reuse
case where the NEW company's own Yahoo data start happens to closely track its OWN recent
index entry (e.g. `Q`, mentioned in review but not in the required test set) — indistinguishable
from a genuine new listing by date comparison alone. This is a conservative failure mode
(under- not over-quarantining) and is noted in `symbol_reuse_new_listing_reason`'s docstring.

**`masked_start`** (survivorship.py, mirrors `masked_end`): populated whenever a ticker's
point-in-time membership began before its cached first bar. For THIS run's own
[2012-01-01, 2026-06-30] window it affects **zero** tickers (every gap it's technically true
for — e.g. IBM's cache not reaching back to 1996 — predates 2012, so `coverage_gap`'s
per-year check never triggers on it); the mechanism and its provenance/`known_caveats`
wiring are implemented and tested for when it does matter.

## Finding 3 — unscored ≠ not-selected (fixed)
`TargetWeights` gained an additive `unscored: dict[str, str]`. `momentum.py`/`value.py`
record only names they could not score; `blend.py` unions children's `unscored`; the engine
reads `targets.unscored` directly instead of inferring `universe − weights.keys()`. Collapsed
`unscored_by_date` from ~473 names/rebalance to a median of 85.

## Timed re-run on the final, corrected cache
- `time uv run quantlab backtest --config configs/backtests/momentum_12_1_2012_2026.yaml`:
  **8m32.428s** (`provenance.run_seconds = 510.42`) — under the 10-minute bound.
- **Final one-liner**: `net CAGR=17.66% Sharpe=0.98 maxDD=-23.25% coverage_bound=28.4%
  forced_exits=1 extreme_returns=0 unscoreable_dates=0`. Coverage bound rose materially,
  22.3%→28.4% — correctly: 42 genuinely-corrupt names now count as lacking coverage instead
  of reading as fully covered. This is the honest measurement and is reported, not
  suppressed, per instruction.
- `provenance.quarantined_count = 42`, `masked_start_count = 0` for this run;
  `known_caveats` states both plainly.

## Verification
`uv run pytest tests/ -q`: exit 0, **491 dots** (was 444 before this iteration). `uv run
ruff check` / `format --check`: clean. Cache integrity verified throughout: 664 parquet
files present before and after every scan/heal/repair step; only sidecar JSON was ever
written.

## Deviations / scope notes
- Touched `data/quality.py`, `data/corporate_actions.py` (`read_cached_actions`),
  `data/survivorship.py`, `backtest/result.py`, `core/types.py`,
  `strategies/{momentum,value,blend}.py` — none in the original packet's Context list, all
  required by the gate's three findings.
- `scan_price_cache`/`heal_or_flag_new_listings` have no CLI caller (M09's `quantlab data
  scan`/`refresh`, per QUANT-NOTES.md's carried item) — run manually this iteration.
- Not addressed (non-blocking, carried unchanged): `retry_after_days` / no_data-suppressed
  count not yet in provenance; M09 force-clear CLI for no_data/quarantine sidecars
  mechanism-ready, no CLI.
