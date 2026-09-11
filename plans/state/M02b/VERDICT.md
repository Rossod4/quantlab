VERDICT: REJECT

# M02b quant-gate verdict — as-of adjustment replay + actions-cache staleness

The design is right. The formula, its provenance, the ex-date gate, the
defense-in-depth re-gate, the same-day composition argument and the strict
staleness policy are all correct, and I verified the arithmetic independently.
What fails is **totality**: the replay has never been exercised against a
realistic corporate-action history, and it has a silent bypass. Two of the four
findings below are hard blockers that make `prices()` either crash or silently
return the exact unadjusted series this packet exists to eliminate.

## Verification performed
- `uv run pytest tests/ -q` → 156 passed, 3 deselected. `uv run ruff check` → clean.
  Matches HANDOFF.md and REVIEW.md.
- Independent arithmetic: NVDA 1210/10 = 121.0; AAPL 500/4 = 125.0; dividend
  1 - 2/100 = 0.98 → 98.0; same-day (1/3)·(1-4/40) = 0.3. All match the fixtures.
- Reverse split (yfinance value 0.2 = 1-for-5): pre-split 10.0 → 50.0, ratio across
  the ex-date exactly 1.0 for a flat-value stock. Correct, and not currently fixtured.
- Exactness across an ex-date for a flat-value stock: **confirmed exact, both event
  types.** Split 10:1, flat value → adjusted ratio 0.0 to float64 exactness
  (raw reads -0.9). Cash dividend where the price falls by exactly D → adjusted
  ratio exactly 0.0 (raw reads -2.0%). The composition is exact because every
  individual factor is computed from the untouched raw series, never from a
  partially-adjusted price — the developer's commutativity argument holds.
- Factor at `asof` itself is exactly 1.0 (no gated ex-date is strictly greater than
  the last date), so the `asof` row of `prices()` is the true traded price. This is
  what makes a clean P/E possible at the decision date — see carried item 1.

## Findings (numbered, each blocking unless marked)

### 1. BLOCKER — `prices()` raises `ValueError` for any dividend payer whose dividend history predates the price window

`pit.py:164` fetches actions from `_EPOCH` to `asof` — the ticker's ENTIRE history —
and hands them to `apply_asof_adjustment` together with a price panel trimmed to
`lookback_days` sessions. `adjustment.py:87-92` then tries to compute
`close_prev_ex` for every gated dividend, including ones whose ex-date is years
before the panel's first row, finds no prior close, and raises.

Reproduced (scratchpad, not committed): a KO-like ticker with quarterly dividends
from 2015, `asof=2024-12-10`, `lookback_days=60`:

```
RAISED ValueError : no raw close available strictly before ex-date 2015-03-31 to
compute the dividend adjustment factor (close_prev_ex)
```

**Methodological risk.** This is not a corner case — it is every dividend payer in
the S&P 500 at every realistic lookback. The decision path is non-functional for
roughly four hundred names, which means the replay has never actually run against a
real action history; the eleven passing fixtures all happen to place every ex-date
after the panel's first row. It also raises a bare `ValueError` rather than a typed
`DataQualityError`, inviting a future caller to catch and continue.

**Required remedy.** In `apply_asof_adjustment` (NOT in `adjustment_factors`, whose
standalone contract should stay strict), drop actions whose ex-date is `<=` the
ticker's first available price date before computing factors. This is
output-preserving: such an event's factor applies only to prices strictly before its
ex-date, and there are none in the panel, so it contributes 1.0 to every row today.
It also makes `close_prev_ex` total — every surviving event has at least one panel
row before it. Add a regression test with a multi-year quarterly dividend history
and a bounded lookback. Note in the docstring that `close_prev_ex` is the last panel
close before the ex-date, which is the true prior session only when the panel has no
gap there.

### 2. BLOCKER — a transient fetch failure silently disables adjustment, bypassing the staleness guard entirely

`corporate_actions.py:189-202`: when the first download fails, `get_actions` returns
`_empty_actions()` **before** the staleness block at 206-220 is reached. Reproduced
with a monkeypatched `_download_actions` raising `ConnectionError`:

```
fetch-failure path -> DataFrame rows: 0   (no raise, even for end=2030-01-01)
cache file written? False | meta written? False
```

Not writing the cache is right and the reasoning in the comment is right. Returning
empty to the PIT path is not. Before M02b an empty actions frame was benign
metadata; after M02b it means "no adjustment", so a transient network blip now makes
`prices()` return the raw, split-distorted series with no error at all. Because it is
per ticker, a partial failure corrupts only some names in a cross-sectional momentum
rank — a plausible-looking ranking with a few -90% outliers, which is worse than a
hard failure. This is the same principle the developer correctly adopted one branch
away ("we don't know when this was fetched must never silently pass through to an
as-of decision"), violated here.

**Required remedy.** The fetch-failure branch must raise a typed error (reuse
`StaleActionsCacheError` or a sibling `DataQualityError`) naming the ticker and the
underlying failure, still without writing the cache. Add a test. Reviewer finding 4's
end-to-end `PITDataContext` test becomes mandatory alongside it: the invariant "a
missing or stale actions history blocks a decision, never degrades it" must be pinned
by a test that goes through `prices()`, not only through the provider.

### 3. BLOCKER (minimum remedy is documentation) — adjusted close and raw OHL coexist in the same row

Reproduced across the NVDA split with `asof` after the ex-date:

```
              open    high     low  close  raw_close
2024-06-07  1200.0  1215.0  1195.0  121.0     1210.0
  close <= high ? True    close >= low ? False
```

`close` is ten times below `low` on the same row. Any consumer touching two columns
at once — an ATR, a gap or range measure, a "close near the high" filter, or a
sanity check asserting `low <= close <= high` — silently produces nonsense across
every split in the lookback. The packet does permit skipping OHLC adjustment if
documented, so I am not overruling the packet, but the current wording ("only `close`
is as-of adjusted") states a limitation while concealing the consequence: a reader
reasonably assumes the row stays internally consistent.

**Required remedy, preferred:** apply the same per-date factor to `open`/`high`/`low`
— it is the identical factor array, a two-line change — and state that `volume` is
NOT adjusted (a split multiplies share volume by the ratio). **Acceptable minimum:**
leave OHL raw but say so explicitly and with this example in both the
`adjustment.py` module docstring and `PITDataContext.prices()`'s docstring, in the
words "`close` is on a different scale from `open`/`high`/`low` in the same row
before any gated ex-date; never combine them."

### 4. BLOCKER — a dividend at or above `close_prev_ex` silently yields non-positive adjusted prices

`_event_factor` guards `close_prev_ex <= 0` but never guards the resulting factor.
Reproduced: a 45.0 distribution against a 40.0 prior close gives factor -0.125 and

```
check3 oversized special dividend: NO RAISE, adjusted closes = [-5.0, 5.0]
```

Negative prices in the decision path, and the momentum ratio flips sign. Reachable
from a genuine liquidating distribution and, more likely, from a yfinance dividend
value in the wrong units — precisely the vendor error this platform exists to catch
rather than propagate.

**Required remedy.** Raise a typed `DataQualityError` naming the ticker, ex-date,
amount and `close_prev_ex` when an individual or composed factor is `<= 0`. Add a
fixture.

### 5. Reviewer's non-blocking findings — all four upheld, fold into this cycle

Since the milestone is returning anyway, do all of them.
1. Tighten `TOL` in `tests/test_adjustment.py` from `1e-9` to `1e-12`. The packet
   says 1e-12 and the real error is ~1e-16; there is no reason to assert looser than
   the stated bar.
2. Add the one-line note that `adjustment.py`'s internal re-gate is a second layer
   canary (f) does not exercise (pit.py's slice shields it), pinned instead by the
   direct `apply_asof_adjustment` parity tests. The reviewer's mutation test B is the
   right evidence to cite.
3. Add the staleness note to the `CorporateActionsProvider` ABC
   (`interfaces.py:82-88`). I agree with the developer that enforcement should stay
   out of the ABC as a non-abstract contract note — forcing every test fake to
   implement it would be disproportionate — but finding 2 shows the guarantee is
   thinner than one class docstring suggests even for the single existing provider,
   so the contract new implementers read must state it. The `NorgatePriceProvider`
   stub is price-only and cannot bypass anything today; a future
   `NorgateCorporateActionsProvider` could, and nothing at the interface or in
   `pit.py` would notice.
4. See finding 2 — now mandatory, not optional.

## On the questions put to this gate

- **Convention and provenance: correct.** `1/R` for a split with yfinance's
  "new shares per old share" ratio, `1 - D/close_prev_ex` for a cash distribution,
  reverse-cumulative product applied to prices strictly before each ex-date. That is
  CRSP-style backward adjustment as documented, and the `side="right"` boundary
  (a price ON the ex-date already trades post-event) is right.
- **Exactness across an ex-date for a flat-value stock: exact**, both splits and
  dividends, to float64. Verified independently above.
- **Price-level consumers: NOT consistent, and it needs a note carried to M03** —
  carried item 1 below. Not a defect in this milestone, but M03 will walk into it.
- **Strict "missing `fetched_at` is stale": sound.** It fails loud, in the
  conservative direction, and the day-granularity limitation is honestly documented.
  Finding 2 is the hole in it, not the policy.
- **Provider-level enforcement point: acceptable**, with reviewer finding 3's
  contract note. `pit.py` passes `end=asof` at both call sites and `_asof` has no
  setter, so there is no bypass through the public API today.
- **`prices()` docstring precision for the M03 Strategy ABC to freeze against: not
  yet.** It is precise about what `close` is and about the ex-date gate. It is silent
  on the three things a strategy author will actually get wrong: that `close` is a
  total-return-comparable level rather than a traded price for historical rows, that
  `raw_close` still carries the full split discontinuity, and finding 3's cross-column
  incoherence. Fix those three sentences and the contract is freezable.

## Not blocking, carried

`refresh_actions_cache()` has no operational caller anywhere in the package — no CLI
subcommand, no network-tier path. A user with a pre-M02b actions cache now gets a
`StaleActionsCacheError` out of `prices()` and no in-product way to clear it. The
strict policy is right; the missing escape hatch is an M09 item, recorded in
plans/QUANT-NOTES.md.

## Re-review scope

Findings 1-5 only. Do not reopen the formula, the gate, the enforcement point or the
staleness policy — they are accepted. `plans/state/M02/VERDICT.md` carried item 1
stays OPEN until this cycle passes; M03 momentum remains blocked.
