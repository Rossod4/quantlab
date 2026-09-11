VERDICT: ACCEPT

M03b closes the M03 verdict's MATERIAL stale-share-terms finding and the M06
blend-id item. I re-measured both on my own M03 gate fixtures rather than on
the packet's tests: the split-spanning name moves from the best composite rank
to the worst, P/E and P/B land on their true values to 1e-9, and the blend id
is now order- and default-insensitive while staying weight- and
param-sensitive. The frozen EDGAR numerics are byte-identical across 4,000
randomised differential trials. Nothing here weakens a bias guard.

Section 4 records five carried items. Item 4.1 is a narrower survival of the
original hazard and must be understood before an M04 value result is quoted;
item 4.2 is a test-coverage gap on the one window bound nobody has
mutation-tested.

---

## 1. Verification

Packet commands, re-run at the gate:

- `uv run pytest tests/ -q`: exit 0, 226 dots, no red.
- `uv run ruff check .`: all checks passed. `uv run ruff format --check .`:
  52 files already formatted.

Working tree restored and confirmed byte-identical after my two mutations:
`src/quantlab/data/pit.py` md5 `3ad184826c7a5d78c79631aa6723b8af` before and
after, and `git diff --stat` unchanged at 520 insertions across 8 files.

### 1.1 Probe A — the M03 MATERIAL finding, re-measured on the same fixture

I re-ran my own M03 gate fixture unmodified: four names, `asof` 2020-09-30, a
4:1 split on 2020-08-31, all filings dated 2020-07-30 and therefore in
pre-split share terms.

| | M03 | M03b | true |
|---|---|---|---|
| SPLT P/E | 6.25 | 25.000000000 | 25.0 |
| SPLT P/B | 0.416667 | 1.666666667 | 5/3 |
| SPLT composite rank | 1 of 4 (cheapest) | 4 of 4 | 4 of 4 |
| top-2 selection | FLAT, SPLT | FLAT, MIDD | FLAT, MIDD |

The context now delivers `shares_outstanding` 160.0 from a filed 40.0 and
`ttm_eps` 5.0 from a filed 20.0, with
`shares_outstanding_split_factor` and `ttm_eps_split_factor` both 4.0 and
`share_terms_asof` 2020-09-30. Both ratios are within 1e-9 of truth, and the
name is excluded from the book rather than selected into it. The finding is
closed.

**The fix is pinned, not incidental.** I forced the restatement factor to a
constant 1.0 and re-ran: five tests fail, including
`test_gate_fixture_pe_and_pb_correct_after_a_4_for_1_split`,
`test_split_at_asof_is_applied_even_with_a_filing_lag`,
`test_two_splits_after_filing_compose` and the end-to-end
`test_split_spanning_name_lands_at_its_true_composite_rank_not_the_best`.
Reverted; green again.

### 1.2 Probe B — the lower bound

The window is strict on the left. Measured directly:

| split ex-date | factor applied |
|---|---|
| `filed - 1d` | 1.0 |
| `filed` | 1.0 |
| `filed + 1d` | 4.0 |

So the code reads `filed <` strictly, matching the packet. **The ASC 260
argument in HANDOFF.md is stated correctly** for EPS: ASC 260-10-55-12
requires retroactive restatement of per-share amounts for a split occurring
before the financial statements are issued, so a split between period end and
issuance is already in the filed figure, and the relevant window really is
`(filed, asof]` rather than `(period_end, asof]`.

**Which side the boundary belongs on.** A split ex-dated on the filing date is
genuinely ambiguous at EDGAR's day granularity: the ex-date opens the market
that morning, and a filing dated that day is normally issued later the same
day, so ASC 260 would have the filer restate. That supports the shipped strict
`<`. But the two readings fail in opposite directions, and they are not
equally bad:

- Shipped (`<`, no restatement at the boundary). If the filer did not in fact
  restate, the figure stays in pre-split terms, P/E reads too low, and the name
  looks cheap. That is a spurious buy.
- Alternative (`<=`, restate at the boundary). If the filer did restate, the
  figure is restated twice, P/E reads too high, and the name looks expensive.
  That is a missed name.

The shipped side is correct on the standard and is the side whose failure mode
is a spurious buy. That is defensible, and it is what the packet decided, so it
is not a rejection — but it is untested, which item 4.2 addresses.

### 1.3 Probe C — the upper bound, including a hostile provider

| case | factor | expected |
|---|---|---|
| split at `asof`, `filing_lag_sessions=1` | 4.0 | 4.0 |
| split at `effective_asof`, lag 1 | 4.0 | 4.0 |
| split one session after `asof` | 1.0 | 1.0 |
| hostile provider: splits 7.0 and 11.0 after `asof` plus a real 2.0 before | 2.0 | 2.0 |

The hostile case is the load-bearing one. A provider that ignores its `[start,
end]` arguments and returns two post-`asof` splits alongside one real pre-`asof`
split yields exactly 2.0, not 154.0. The window cannot be extended past `asof`
through the provider, because `fundamentals()` reuses `_gated_actions_by_ticker`,
which hard-slices to `ex_date <= asof` and then asserts, rather than making a
second raw provider call. The upper bound is `asof` and not the lagged
`effective_asof`, which is right: the filing lag governs which filings are
visible, while a split is a market event knowable on its ex-date.

### 1.4 Probe D — the TTM EPS latest-component-filed rule

The rule is **exactly right when its premise holds and conservatively wrong in
the adverse direction when it does not.** Its premise is that a later filing's
restated comparatives are present in the facts and win the dedup.

Constructed case: four standalone quarters filed 2019-08-05, 2019-11-05,
2020-02-14 and 2020-05-08, with a 4:1 split on 2019-12-01 falling between the
second and third filings, and no restated comparatives filed yet.

| | value |
|---|---|
| `ttm_eps_filed` (latest component) | 2020-05-08 |
| split 2019-12-01 is before that, so factor | 1.0 |
| `ttm_eps` returned | 10.0 |
| correct all-post-split TTM | 4.0 |
| overstatement | 2.50x |

An overstated TTM EPS understates P/E by the same factor, so the name looks
cheaper than it is — the same direction as the original M03 hazard. Two
controls confirm the diagnosis rather than a coding error:

- With the restated comparatives present, `ttm_eps` comes back 4.0, exact.
- On the annual-fallback path, where the TTM is one annual figure filed after
  the split, the answer is correct with nothing to restate.

**How much is left.** I re-ran my gate fixture with SPLT's TTM built from four
quarters straddling the split. `shares_outstanding` is restated exactly, so
P/B comes back exactly 1.666667; only P/E is distorted, reading 7.69 against a
true 25.0 on a 3.25x TTM overstatement. The composite moves 0.917 to 0.750 and
SPLT still ranks 4 of 4 and is still excluded. Compare M03, where both legs
carried the full 4x and the name moved from worst to best. The residual is one
of up to four composite legs rather than two, and it cannot touch market cap,
P/B or EV/EBITDA, because `shares_outstanding` is a single instant fact with a
single filed date and is always restated exactly. It is a real but much smaller
hazard, recorded at 4.1.

### 1.5 Probe E — frozen EDGAR numerics

I extracted the pre-M03b module from HEAD and ran a randomised differential
test: 4,000 random fact tables through both versions, with mixed tag pooling,
standalone quarters, cumulative and annual durations, junk durations, restated
duplicates and random `asof` dates. 678 trials populated both per-share fields.

**Zero field mismatches** across all seven shared fields, including None-ness
and the diluted-to-basic fallback. A second 1,500-trial pass confirmed each
provenance date is None exactly when its value is None. The new helpers are
additions, not modifications: `_most_recent_instant`,
`_most_recent_instant_with_end`, `_ttm_duration` and `_annual_growth` are
untouched, and `tests/parity/` passes unchanged.

### 1.6 Probe F — the blend id against my M06 item

Both cases I named in M03 verdict item 4.8 are fixed, and nothing that should
distinguish two blends has been collapsed:

| case | id |
|---|---|
| child order swapped | same |
| child default params omitted | same |
| reconstructed from the same dict | same |
| a weight changed | different |
| a child param changed | different |
| the two weights swapped between children | different |
| nested blend as a child | resolves, different from flat |

The last row matters: sorting `(child.strategy_id, weight)` pairs must not lose
which child received which weight, and it does not. Building the blend id from
each child's own `strategy_id` inherits that id's default-insensitivity, so the
fix is structural rather than a special case.

### 1.7 Probe G — bias guards, re-verified rather than assumed

I re-ran my full M03 adversarial suite against this tree, because
`fundamentals()` now consumes the corporate-actions path and could have opened
a leak there:

- **Look-ahead, all five configs.** Leaky providers returning 26,600 post-`asof`
  price rows, 210 post-`asof` filings and two post-`asof` splits still produce
  weights identical to a clean-provider run, for every config including the
  blend. Net and gross conventions unchanged: 1.0/1.0, 0.0/2.0, 1.0/1.6.
- **Purity and declaration gating.** Calling `generate_targets` twice returns
  identical weights with params unmutated, for momentum long-short, value and
  blend. An under-declared strategy still raises `UndeclaredDataError` on all
  four accessors.
- **Field filtering.** Declaring only `stockholders_equity` returns exactly
  that one key: no per-share field and no provenance key leaks through.
- **Scope of the restatement.** Adding a 2:1 split changes only
  `shares_outstanding`, `ttm_eps` and their two factor keys. Totals
  (`stockholders_equity`, `total_debt`, `cash`, `ttm_ebitda`) and the
  `annual_eps_growth` ratio are bit-identical, as the docstring claims.
- **No raw action data reaches the strategy** through the returned dict.

One behavioural change is new and is not a weakening, but does need an engine
policy: see 4.3.

### 1.8 M03 documentation defects

Both are fixed. `configs/strategies/value_composite.yaml` now states the lag is
enforced. `fundamentals()`'s docstring now reads "identical ... for a session
`asof` ... and strictly narrower - never wider - for a non-session `asof`",
which is the precise claim.

---

## 2. Answer to the specific question: does anything weaken a bias guard?

No. The restatement only ever consumes splits with `ex_date <= asof`, drawn
from the same gated path `prices()` uses, and a split's ex-date is the date the
market itself repriced, so using it involves no information unavailable at
`asof`. If anything the convention is conservative: a split is announced weeks
before its ex-date, so gating on ex-date uses the knowledge later than a
participant actually had it.

The guard that could have been weakened — `UndeclaredDataError` — is intact:
provenance keys appear only when their own field is declared, and no undeclared
field crosses the boundary.

---

## 3. Closing the items addressed to M03b

**M03 verdict 4.1 (MATERIAL, stale share terms) — CLOSED**, with the residual
at 4.1 below carried forward. Measured at 1.1 on the gate's own fixture: rank 1
of 4 becomes rank 4 of 4, P/E 6.25 becomes 25.0, P/B 0.417 becomes 1.667.

**M03 verdict 4.8 (M06 blend id) — CLOSED.** Measured at 1.6. Both named cases
give the same id; weight, param, weight-assignment and nesting all still
differentiate.

**M03 verdict 4.9 and 4.10 (documentation defects) — CLOSED.** See 1.8.

The remaining M03 items (4.2 blend cost model, 4.3 month-index contiguity, 4.4
unpriceable names, 4.5 formation-date convention, 4.6 overlap-guard policy, 4.7
per-child context) are untouched by M03b and remain open against M04.

---

## 4. Carried forward

### To M04, or a follow-on data-layer packet

**4.1 TTM EPS can still be a mixed-share-terms sum. Narrower than the M03
hazard, same adverse direction.** `ttm_eps_filed` is the latest filed date
among the summed components, which is the right date only when every component
is stated in the terms in force on it. That holds when a later filing's
restated comparatives are in the facts, and the dedup then makes the answer
exact. It does not hold in the window between a split and the filing that
restates the comparatives, when the TTM is built from four standalone quarters.
Measured: a 4:1 split between the second and third component filings leaves
`ttm_eps` at 10.0 against a correct 4.0, a 2.50x overstatement, and P/E is
understated by the same factor, so the name looks cheap.

Bounds on the damage, all measured: `shares_outstanding` is never affected, so
market cap, P/B and EV/EBITDA stay exact; only the P/E leg and the
growth-adjusted leg derived from it move; the annual-fallback path is correct.
On my gate fixture the residual moved the composite 0.917 to 0.750 without
changing the rank or the selection. The correct fix is to restate each
component by the splits after its own filed date and then sum, which needs the
provider to expose per-component data rather than a single scalar — a data-layer
change, not engine work. Until then, an M04 value result should carry this
caveat for names that split during the backtest window.

**4.2 The lower bound `filed <` is untested. Mutation-confirmed gap.** I changed
`_split_factor_since_filed`'s window from `splits.index > filed` to
`splits.index >= filed` and the full suite stayed green at 226 dots. No test
distinguishes the two readings. This is the mirror of the blocker the code
review caught on the upper bound, on the other side of the same window, and it
survived both review iterations because both mutations were aimed at the right
edge.

Required: a test pinning a split ex-dated exactly on the filed date, asserting
factor 1.0. Worth deciding deliberately rather than by default, because the two
readings fail in opposite directions and the shipped one is the side that can
produce a spurious buy (see 1.2). A related nuance for the same test: for
`shares_outstanding` the governing date is the cover page's "latest practicable
date", which precedes the filing date, so using `filed` for that field is very
slightly too late and errs toward under-restatement — the same adverse
direction, and worth a sentence in the docstring even if the code keeps using
`filed`.

**4.3 `fundamentals()` now depends on the corporate-actions path.** Verified:
with a raising actions provider and `needs_actions=False`, `fundamentals()`
propagates the failure. `_gated_actions_by_ticker` is deliberately independent
of `DataRequirements.needs_actions`, which was already true for `prices()`, but
it is new for `fundamentals()`. So a stale or unfetchable actions cache now
blocks the value leg as well as the price leg, and a strategy that declares no
actions need can still fail on one. This is correct behaviour — silently
skipping the restatement would reintroduce the hazard — but M04 needs one
policy covering both paths, and dropping the offending ticker must be counted in
the coverage gap rather than swallowed. Reinforces the open M02b item on a
blocked ticker at a rebalance.

### To M06 (trials registry)

**4.4 `strategy_id` does not encode data semantics, so a config's id is stable
across a change that alters its results.** `value_composite-b6fdfec048` is
unchanged from M03 to M03b even though the strategy's output on a
split-spanning universe changed materially. The trials registry keys on
`strategy_id`, so pre- and post-M03b runs of the same YAML would be recorded as
the same trial, and a genuine change in results would look like noise. Momentum
ids are likewise unchanged, correctly, since nothing about them moved. Recommend
the registry key on `strategy_id` plus a platform or data-semantics version, and
that M03b be the first recorded boundary.

### Minor

**4.5 Repeated per-ticker fetches compound.** `fundamentals()` fetches the
ticker's full actions history on every call, and `value.py`'s `_asof_raw_price`
already issues a per-ticker `ctx.prices([t], 1)` that fetches the same history
again. That is two full action fetches per ticker per rebalance, in a Python
loop over the universe. Separately, `BlendStrategy.strategy_id` reconstructs
every child through `load_strategy` on each access, and `generate_targets`
reconstructs them again. Correctness is unaffected; this reinforces M03
REVIEW.md minor 3 and is worth one batching pass when M04 wires in a real
provider.

---

## 5. Note on the review iterations

The code review's blocking finding was real and well-chosen: the upper-bound
mutation did pass green through iteration 1. Both the developer and the reviewer
mutation-checked the fix, and I repeated the restatement-neutering mutation
independently with five failures. The iteration-2 change from one shared
`share_terms_split_factor` to per-field
`shares_outstanding_split_factor`/`ttm_eps_split_factor` is the right call and
removes a reporting inconsistency rather than documenting around it. My one
addition is that the same class of gap remains on the window's other edge (4.2).
