VERDICT: REVISE

## Verification run (reviewer-executed)
- `python -m uv run pytest tests/ -v` → **75 passed, 3 deselected** (network tier), matching the handoff.
- `python -m uv run ruff check` → clean.
- `python -m uv run ruff format --check` → 16 files already formatted, clean.
- Acceptance criteria 1, 3, 4, 5, 6, 7 verified directly against the test suite and are met.
  Criterion 2 (as-of membership, no look-ahead) verified by hand against the fixture CSV — see
  below.

## Findings

### 1. [BLOCKER] `.gitignore:2` silently ignores the entire M01 deliverable — `src/quantlab/data/` is untracked by git
`git status` only lists `tests/test_*.py` and `tests/fixtures/` as untracked. None of the actual
production code this packet creates — `src/quantlab/data/{__init__,interfaces,cache,quality}.py`
and `src/quantlab/data/providers/{__init__,yfinance_prices,sp500_constituents,norgate_prices}.py`
— shows up at all, tracked or untracked. Confirmed the cause:

```
$ git check-ignore -v src/quantlab/data/interfaces.py src/quantlab/data/providers/yfinance_prices.py
.gitignore:2:data/	src/quantlab/data/interfaces.py
.gitignore:2:data/	src/quantlab/data/providers/yfinance_prices.py
```

`.gitignore` line 2 is a bare, unanchored `data/` pattern, added in M00 (commit `975824c`) to
ignore the *runtime cache directory* (`configs/platform.yaml`'s `cache_dir: data/cache`). Because
the pattern isn't anchored to the repo root, git matches it against any directory named `data`
anywhere in the tree — including the new `src/quantlab/data/` package this milestone creates.
Right now everything "works" (pytest picks the files up off disk regardless of git tracking) which
masks the problem, but `git add -A` / `git commit` will never pick up a single file of this
milestone's actual source. Left as-is, this milestone cannot be merged — the diff would contain
only tests and fixtures, no implementation.

**Fix expected:** anchor the ignore rule to the repo root so it only matches the top-level cache
dir, e.g. `.gitignore:2` `data/` → `/data/` (and `reports/` → `/reports/` for the same reason,
since `configs/platform.yaml`'s `reports_dir: reports` is the only thing that rule should cover —
no `src/quantlab/reports` exists yet, but the footgun is identical). After the fix, re-run
`git status` and confirm all of `src/quantlab/data/**` shows up as untracked/stageable, and that
`data/cache/` (once populated by a run) is still correctly ignored.

Not the developer's fault that `.gitignore` predates this package, but it's squarely in scope to
catch and fix before handoff — the milestone's own files colliding with a pre-existing ignore rule
is exactly the kind of thing "changed files" review is supposed to catch.

## Minor (non-blocking)

### 2. `src/quantlab/data/quality.py:106` — `_scan_outliers` pivots via `pivot_table`, which silently averages duplicate (date, ticker) rows instead of surfacing them
```python
wide = panel.pivot_table(index=panel.index, columns="ticker", values="adj_close")
```
`pivot_table`'s default `aggfunc="mean"` means a panel with an accidental duplicate (date, ticker)
row — itself a data-quality bug — gets silently averaged away rather than flagged, unlike the old
repo's `find_price_outliers`, which took an already-deduplicated wide frame as input so this case
never arose. Not required by any acceptance criterion (verified via `test_no_false_positives_on_normal_returns`
and the +60%/+10% test, both of which pass), but worth a follow-up given `QualityGate`'s whole
purpose is "don't trust the vendor silently" — a `pivot_table(..., aggfunc="mean")` masking bad
input runs slightly against that spirit. Consider asserting no duplicate (date, ticker) pairs, or
using `pivot` (which raises on duplicates) instead of `pivot_table`.

### 3. `src/quantlab/data/quality.py:67` — flag ordering changed from the old repo's "worst offenders first" to `[date, ticker]`
The old repo's `find_price_outliers` sorted flags by `|daily_return|` descending. The ported
`QualityGate.scan` sorts by `["date", "ticker"]` instead (needed anyway once OHLC-sanity flags are
merged in, since they don't have a `daily_return` magnitude to sort by). This is a presentation
change, not a numerical one, and isn't constrained by any acceptance criterion — flagging only
because CLAUDE.md invariant 4 ("ported numerical logic is frozen") is worth a conscious pass/fail
call on for any port-with-behavior-change, and this one is a fine, deliberate call, not a bug.

## Acceptance-criteria spot checks (for the record)
- **Criterion 2 (no look-ahead between membership rows):** `tests/test_constituents.py::test_fixture_membership_between_change_rows_uses_earlier_row`
  asserts `membership("2019-01-01")` — strictly between the fixture's `2018-06-07` and
  `2020-09-21` rows — returns `{AAPL, MSFT, XOM, BRK-B, JPM}` (the earlier row) and explicitly
  excludes `TSLA` (only added in the later row). `_membership_from_table` implements this via
  `table.index.asof(date)`, which by construction can only resolve to the last label `<= date`.
  Verified correct by hand against `tests/fixtures/constituents_slice.csv`. The before-first-row
  case (`test_fixture_membership_before_first_row_raises`) raises `ValueError`, documented in the
  handoff as matching the old repo's behavior exactly (confirmed against
  `MomentumValueStrategy/src/data_layer/constituents.py::get_membership`, same `ValueError` shape
  and message).
- **yfinance 1.5.1 adaptation** (`src/quantlab/data/providers/yfinance_prices.py:117`, the
  `isinstance(raw.columns, pd.MultiIndex)` check replacing the old repo's `len(batch) == 1`
  special case): minimal and behavior-preserving — it only changes *how* the single-ticker-batch
  shape is detected, not what's done with it once detected. Confirmed via the old repo's
  `data_layer/prices.py:174-177` for comparison.
- **pandas 3.x `DataFrame.stack().dropna()` adaptation:** unchanged from the old repo's own
  pandas-2.x-era fix (same line, same comment carried forward) — not actually a new adaptation,
  correctly identified as such in the handoff.
- **`DEFAULT_CONSTITUENTS_URL`** (flagged in the handoff as a best-effort reconstruction): checked
  against `MomentumValueStrategy/src/config.py:17-20`'s `CONSTITUENTS_URL` — byte-for-byte
  identical. No discrepancy; the handoff's open question is resolved.

Everything else — cache round-trip, delisted-ticker no-refetch (both the cache-layer test and the
end-to-end `YFinancePriceProvider` test), ticker normalization, `QualityGate` threshold
sensitivity (+60% flagged, +10% not), OHLC sanity flags, norgate stub contract, `build_provider`
factory including unknown-name `ConfigError`s naming the offending value — all pass and assert
real values, not just "runs without error." Once finding 1 is fixed (a `.gitignore` one-liner,
not a code change), this should be a quick re-review.
