# M01 Handoff (iteration 2) — revision after REVIEW.md

All three findings addressed. Base implementation unchanged except as noted below;
see HANDOFF.md for the original design decisions.

## Finding 1 [BLOCKER] — `.gitignore` bare `data/` hid `src/quantlab/data/`: FIXED
- `.gitignore` lines 2-3 anchored to repo root: `data/` → `/data/`, `reports/` → `/reports/`,
  with a comment explaining they cover only the runtime dirs from `configs/platform.yaml`.
- Verified per the review's instructions:
  - `git check-ignore -v src/quantlab/data/interfaces.py src/quantlab/data/providers/yfinance_prices.py`
    → no match (exit 1); previously matched `.gitignore:2:data/`.
  - `git check-ignore -v data/cache/probe.parquet` (probe file, removed after) → still matches
    `/data/` — the runtime cache remains correctly ignored.
  - `git status --porcelain -uall` now lists all 8 implementation files under
    `src/quantlab/data/**` as untracked/stageable, plus tests, fixtures, and plans/state/M01.

## Finding 2 [minor] — `pivot_table` silently averaged duplicate (date, ticker) rows: FIXED
- `src/quantlab/data/quality.py`: new `QualityGate._scan_duplicates(panel)` runs before the
  outlier scan. Every occurrence after the first of a duplicate (date, ticker) pair is flagged
  with reason `duplicate_row` (a duplicate row IS a data-quality bug — flagging beats averaging,
  matching the gate's "don't trust silently" purpose). The outlier scan then runs on the
  first-occurrence-only panel and uses `pivot` (raises on duplicates) instead of
  `pivot_table` (averages them), so the invariant is enforced structurally, not by convention.
- Kept as flag-not-raise: per the packet, `DataQualityError` is reserved for wholly corrupt
  input; a stray duplicate row is a flaggable defect, not corruption.
- New test: `tests/test_quality.py::test_duplicate_date_ticker_rows_are_flagged_not_silently_averaged`
  (asserts exactly one `duplicate_row` flag at the right (date, ticker), and no spurious
  outlier flags from the duplicate).
- Two targeted `# noqa` suppressions with inline rationale: PD010 (rule prefers `pivot_table`,
  whose default aggfunc is the exact silent-averaging failure mode this fix removes) and
  PD013 (rule prefers `melt`; `stack().dropna()` is the old repo's frozen ported logic).

## Finding 3 [minor] — flag ordering `[date, ticker]` vs old repo's worst-first: KEPT, justified
- Deliberate, not accidental: `scan` merges three heterogeneous flag types (OHLC sanity,
  duplicates, outliers), and only outlier flags carry a `daily_return` magnitude to sort by —
  "worst offenders first" is undefined for the other two. `[date, ticker]` gives a single
  deterministic ordering across all flag types, which matters more for M03+ backtests recording
  flag counts than presentation order. The magnitude is still embedded in each outlier reason
  string (e.g. `outlier_return:+200.0%`), so worst-first is recoverable by the caller.
  Presentation-only change; no numerical logic touched (consistent with CLAUDE.md invariant 4).

## Files changed this iteration
- `.gitignore` (anchored patterns + comment)
- `src/quantlab/data/quality.py` (`_scan_duplicates`, `pivot_table`→`pivot`, noqa rationale)
- `tests/test_quality.py` (one new test)
- `plans/state/M01/HANDOFF.2.md` (this file)

## Verification
- `uv run pytest tests/ -v` → **76 passed, 3 deselected** (network tier; was 75+3, +1 new test)
- `uv run ruff check` → clean; `uv run ruff format --check` → clean
- git verification commands as listed under Finding 1

## Open questions
- None new. HANDOFF.md's `DEFAULT_CONSTITUENTS_URL` question was resolved by the reviewer
  (byte-identical to the old repo's `CONSTITUENTS_URL`).
