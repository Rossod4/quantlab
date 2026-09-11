VERDICT: ACCEPT

M03 (strategy framework + momentum/value/blend plugins) is methodologically
sound. The ported signal math is verbatim, the PIT surface holds against an
adversarial probe that would have changed every selection had it leaked, and
the orchestrator-authorised `filing_lag_sessions` extension is genuinely
restrict-only. Nothing in this milestone weakens a bias guard.

Nothing below blocks the milestone. Section 4 records ten carried items for
later packets, two of which (4.1 and 4.2) are material to backtest realism and
must be resolved before any M04 result is quoted as a return.

---

## 1. What I verified, independently of HANDOFF.md and REVIEW.md

Packet verification commands, re-run at the gate:

- `uv run pytest tests/ -q`: exit 0, 213 dots, no red.
- `uv run ruff check .`: all checks passed. `ruff format --check .`: 51 files
  already formatted.

Every check below is my own, written from scratch in a scratchpad outside the
repo, not a re-reading of the developer's or reviewer's tests. The working
tree was not mutated: `git status --short` and `git diff --stat` are
byte-identical to the state I was handed (`pit.py` +43/-3,
`test_lookahead.py` +59, same untracked set).

### 1.1 Ported math is verbatim (mechanical, not by eye)

I parsed both repos and compared the ported functions' ASTs with docstrings
stripped, which ignores comments and formatting but catches any arithmetic or
control-flow change:

| function | AST-identical body |
|---|---|
| `compute_momentum_signal` | yes |
| `select_top_n` (momentum) | yes |
| `select_bottom_n` | yes |
| `compute_value_ratios` | yes |
| `_rank_lower_is_better` | yes |
| `compute_composite_score` | yes |
| `select_top_n` (value) | yes |

The loss-maker rule therefore ports exactly: `_rank_lower_is_better`'s
`values.where(~(values <= 0), other=np.inf)` is unchanged, so non-positive
ratios tie at the worst percentile as a group rather than sorting in as
artificially cheap, and `compute_value_ratios`' explicit
`pe > 0 and annual_eps_growth > 0` guard on the growth-adjusted leg is
unchanged. `MIN_AVAILABLE_METRICS = 2` is unchanged.

### 1.2 Look-ahead: the public Strategy/PITDataContext surface (probe 1)

Fixture: 70 tickers, daily bars 2018-01-02 to 2021-12-31, `asof` 2020-06-30.
Providers deliberately misbehave. The price provider ignores the requested
window and returns all 26,600 post-`asof` rows; the actions provider returns
two splits dated after `asof`; the facts table carries 210 rows filed after
`asof`, including restated equity, share counts and EPS that reorder the value
ranking. Price paths invert hard after `asof` so a price leak flips the
momentum ranking end to end.

For each of the five shipped YAML configs I built two contexts, one on the
leaky providers and one on providers pre-truncated at `asof`, and compared
`generate_targets` output:

| config | identical, leaky vs clean | n | net | gross |
|---|---|---|---|---|
| momentum_12_1 | yes | 30 | 1.0 | 1.0 |
| momentum_ls | yes | 60 | 0.0 | 2.0 |
| momentum_130_30 | yes | 60 | 1.0 | 1.6 |
| value_composite | yes | 30 | 1.0 | 1.0 |
| blend_50_50 | yes | 60 | 1.0 | 1.0 |

The blend is included deliberately: it hands its children the same `ctx` it
receives, so this covers the meta-strategy path.

**Probe power (probe 3).** An equality result is worthless if the fixture
could not have detected a leak, so I checked what the same code produces with
the hard slice removed: the formation month moves from 2020-06-30 to
2021-12-31 and the top-30 momentum selection shares **0 of 30** names with the
correct one. The fixture has power; the equality above is the slice working.

Acceptance criterion 5 is confirmed in the same table, exactly rather than
approximately: net and gross land on 1.0 / 0.0 / 2.0 / 1.6 to 12 decimal
places.

### 1.3 Momentum convention vs the old repo (probe 2)

The old repo built its month-end panel as `daily_prices.resample(freq).last()`
(`src/backtest/engine.py:126`, `long_short_engine.py:186`). The new
`_month_end_prices` pivots on calendar month instead. On a clean daily panel
the two agree exactly:

- month-end index: identical list of dates.
- month-end values: identical to 1e-12 (`np.allclose`, atol 1e-12, rtol 0).

Running the OLD repo's own `compute_momentum_signal`, `select_top_n` and
`select_bottom_n` directly on the old-style panel reproduces the new
strategy's weights exactly.

Skip month, checked by hand rather than by trusting the index arithmetic: at
`asof` 2020-06-30 the skip leg reads 2020-05-31 and the lookback leg
2019-06-30, eleven months apart, i.e. the return from t-12 to t-1 with the
most recent month skipped. That is the textbook 12-1 specification and it
matches the old repo.

Insufficient history: I deleted the skip-month bars for one ticker and the
lookback-month bars for another. Both vanish from the scored set and neither
appears in the long or the short book. They are excluded before ranking, never
ranked low. This matters for the short leg specifically, since a name silently
scored as missing would otherwise be shorted.

The signal is computed on `close` (the as-of adjustment replay), never
`raw_close`: grep over `src/quantlab/strategies/` finds `raw_close` in exactly
one executable line (`value.py:267`, a level metric), `volume` and
`prices_for_returns` in docstrings only.

### 1.4 Value leg: price-level pairing across a split (probe 4)

REVIEW.md minor 2 notes that no single end-to-end test exercises a
split-spanning fixture through `generate_targets`. I wrote that test at the
gate. Fixture: four names, `asof` 2020-09-30, a 4:1 split on 2020-08-31,
filings dated 2020-07-30 (before the split).

- `raw_close` at `asof` equals `close` at `asof` for every name, confirming
  the as-of adjustment factor is exactly 1.0 on the `asof` row.
- The strategy's selection through the full
  `ctx.prices` then `compute_value_ratios` then `compute_composite_score` then
  `select_top_n` pipeline is identical to my hand computation using raw price
  at `asof` multiplied by the filing in force at `asof`.

M02b carried item 1 is satisfied end to end, not only at the `_asof_raw_price`
unit level. See 4.1 for the residual hazard this fixture also exposed.

### 1.5 `filing_lag_sessions`: is the restrict-only guarantee real? (probe 5)

Yes, with one docstring correction (4.9).

- Lag 0, 1, 2 on a session `asof` give effective gates 2020-01-15, 01-14,
  01-13. Monotone backwards; each visible filing set is a subset of the last.
- A negative lag raises `ValueError` at the point of use, so look-ahead
  through this parameter is not expressible, not merely unused.
- End to end at the strategy level, not just the context: with a same-day
  after-hours filing that would flip the selection, `filing_lag_sessions=0`
  sees equity `{AAA: 9.0, BBB: 90000.0}` and picks BBB; the DECIDED default of
  1 sees `{AAA: 2000.0, BBB: 2000.0}` and picks AAA. The default genuinely
  hides the same-day filing.

`prices()` is untouched by the extension. `DataRequirements` is untouched,
which is right: the lag is a per-call restriction, not a data footprint, and
declaring it would have invited a strategy to widen it.

### 1.6 `strategy_id` (probe 5)

Stable and sensitive in the right direction:

- Key order in the YAML is irrelevant (`sort_keys=True`).
- An omitted default and an explicitly written default hash the same, because
  the id hashes the validated pydantic dump, not the raw YAML.
- Every selection-affecting param changes it: `book`, `n_long`,
  `lookback_months`, `skip_months`, and `filing_lag_sessions`.
- Reconstructing the same params in a fresh process gives the same id
  (sha256 of canonical JSON; no clock, no object identity, no insertion order).

There is no param in any of the three plugins that changes the id without
affecting selection. Blend is the exception and is recorded at 4.8.

### 1.7 Blend algebra (probe 6)

Blended weights equal the manual linear combination to 1e-15, and both
conventions carry through:

- Net is exactly linear. A 50/50 blend of the dollar-neutral momentum book
  (net 0.0) and value (net 1.0) nets 0.5.
- Gross is sub-additive, as it must be, with equality only when no name is
  held long in one sleeve and short in another. In my fixture all 30 value
  longs were also momentum shorts, so gross came out 0.5 against a
  weighted-sum bound of 1.5. The arithmetic is correct; the modelling
  consequence is recorded at 4.2.
- Child weights not summing to 1.0 are rejected at construction.
- The blend stamps its own `strategy_id` on the result.

### 1.8 Purity and declaration gating

Calling `generate_targets` twice on the same context returns identical
`TargetWeights` and leaves `params` unmutated, for momentum long-short, value
and blend. A deliberately under-declared strategy raises `UndeclaredDataError`
on all four accessors: `universe()`, `fundamentals()`, `actions()`, and
`prices()` beyond the declared lookback. `load_strategy` round-trips all five
YAMLs; an unknown name raises `UnknownStrategyError` naming the three
registered strategies.

---

## 2. The interface extension: is it sound, and does restrict-only hold?

**Sound.** The EDGAR gate is day-granular, so `filed <= asof` hands a same-day
after-hours 10-Q to a decision made at that day's close. A one-session lag is
the standard conservative fix and matches the orchestrator's DECIDED
convention. Putting it on `fundamentals()` as a per-call keyword rather than
on the context constructor is the better of the two designs: the context stays
hard-bound to one `asof`, the strategy cannot rebind it, and a strategy that
wants fundamentals as of an earlier date must ask for strictly less, never
more.

**Restrict-only holds.** Three independent reasons, all checked:

1. The gate can only move backwards. `_fundamentals_effective_asof` snaps to
   the last session on or before `asof`, then steps back by `prev_trading_day`
   in a loop. Both operations are monotone non-increasing, so the effective
   date never exceeds `asof` for any non-negative lag, and the visible filing
   set is always a subset of the pre-extension set.
2. Negative lags are unrepresentable. `ValueError` at the point of use, not
   only via pydantic upstream, so the guard survives a direct call.
3. The canary is real. I re-ran the developer's reverse mutation
   independently: switching the stepping to `next_trading_day` makes canary (g)
   return `[300.0, 300.0, 300.0, 300.0]` instead of
   `[300.0, 200.0, 100.0, None]`.

`prev_trading_day` is strict for session inputs, which the M00 verdict warns
against repurposing for inclusive as-of alignment. Here it is correct, because
the value is already snapped to a session before the loop runs. That is the
one subtlety in the extension and it is handled.

One correction to the claim as written: see 4.9. The guarantee holds; the
"byte-identical" wording does not, for a non-session `asof`.

---

## 3. Closing the carried items addressed to M03

**M02 verdict, item 2 (day-granular EDGAR gate) - CLOSED.** The one-session
lag ships as `filing_lag_sessions`, defaulting to 1 in `ValueParams` and wired
into `configs/strategies/value_composite.yaml`. Verified end to end at 1.5:
the default hides a same-day filing that would otherwise change the selection.
The parity tests are unaffected because they call the frozen functions
directly with a prices dict and never construct a context, so no `asof` and no
lag enters them. That satisfies the packet's "pin 0 for old-repo
comparability" intent by construction rather than by pinning.

**M02b verdict, item 1 (value leg, price levels) - CLOSED.** `_asof_raw_price`
reads `raw_close` on the single most recent row. Verified at 1.4 through the
full pipeline on a split-spanning fixture, against a hand computation. See 4.1
for the residual hazard.

**M02b verdict, item 2 (Strategy ABC docs + canary) - CLOSED.** The ABC
docstring states the rule as binding (`base.py:17-31`). The canary exists,
exercises the real production path, and I re-ran the mutation: switching
`_month_end_prices` to `raw_close` fails it with score -0.9.

**M02b verdict, item 3 (volume is unadjusted) - CLOSED.** Documented in the
ABC docstring, and grep confirms no strategy reads `volume` in executable code.

**M02b verdict, item 4 (raw open/high/low not in `prices()`) - CLOSED.**
Documented in the ABC docstring as an escalation trigger. No plugin calls
`prices_for_returns()`. The `filing_lag_sessions` escalation is the worked
example of the rule being followed rather than worked around, which is the
behaviour the item was trying to produce.

The M02b items addressed to M04 and M09 (engine behaviour on a blocked ticker,
paper-runner refresh policy, `refresh_actions_cache` having no caller) are
untouched by M03 and remain open against their own milestones.

---

## 4. Carried forward

### To M04 (engine)

**4.1 Per-share figures go stale across a split between the filing and the
decision. Material.** Market cap is `raw_close(asof) * shares_outstanding`,
and P/E is `raw_close(asof) / ttm_eps`. Both fundamental inputs are stated in
the share terms in force at the filing date; the price is in the share terms
in force at `asof`. A split in between makes them inconsistent, and the error
is the full split ratio.

Measured on my probe-4 fixture, a 4:1 split thirty days after the filing:

| metric | as implemented | split-consistent |
|---|---|---|
| P/E | 6.25 | 25.0 |
| P/B | 0.417 | 1.667 |
| composite rank | 0.250 (best of four) | 0.875 (worst of four) |

The name goes from the bottom of the ranking to the top and is selected into
the book. This is not look-ahead, since no future information is used, and it
is inherited from the old repo, so CLAUDE.md invariant 4 correctly forbade the
developer from fixing it inside M03. But the direction is adverse: splits
follow large price run-ups, so the value book is biased toward buying recent
winners and calling them cheap. `EntityCommonStockSharesOutstanding` is a
cover-page figure as of the filing date, and `ttm_eps` sums four quarterly
`EarningsPerShareDiluted` facts that may straddle a split, so both legs are
exposed.

The fix needs the filing date, or a restatement, exposed through the data
layer, because `fundamentals()` returns values only. Options: restate
per-share figures by the cumulative split factor for ex-dates after the filing
and on or before `asof`, inside `get_point_in_time_fundamentals`; or price off
`raw_close` at the filing date instead of at `asof`. Either is a data-layer
change, so this may warrant its own packet rather than being folded into M04.
Orchestrator's call. Until it is resolved, no M04 value or blend result should
be quoted without this caveat attached.

**4.2 The blend nets weights; the old repo blended net returns. Material to
cost realism.** `combine_strategies` computed `w * r_momentum + (1-w) *
r_value` on series that were each already net of that sleeve's own costs. The
new blend combines target weights, so the engine sees one netted book. Gross
returns are identical, because return is linear in weights. Net-of-cost
returns are not, because turnover and borrow are not linear in weights. My
probe showed the extreme case: 30 names long in the value sleeve and short in
the momentum sleeve cancelled to zero weight, taking gross from 1.5 to 0.5. An
engine that charges spread and borrow on the netted book would charge nothing
for those 30 positions, where the old repo charged both sleeves. M04 must
decide explicitly whether costs are charged per sleeve or on the netted book,
and document it. Charging on the netted book understates costs relative to the
ported baseline and flatters the blend.

**4.3 `_month_end_prices` can silently mis-date the lookback leg.** It pivots
on calendar months present in the panel, so a month with no rows for any
ticker produces no row, and the twelve-rows-back lookup then reaches 13
calendar months back instead of 12, for every name at once, with no error. The
old repo's `resample("ME").last()` emitted an all-NaN row for such a month,
which `compute_momentum_signal` correctly excluded. Reproduced: deleting
November 2019 from a clean panel moved the lookback row from 2019-06-30 to
2019-05-31. A full-month blackout across an entire universe is unlikely in
production but is exactly what a thin fixture or a vendor outage produces. The
engine should assert the month index is contiguous, or reindex to a complete
month range, before calling the signal.

**4.4 The value leg drops unpriceable names silently.** `_asof_raw_price`
returns `None` when `ctx.prices([ticker], 1)` is empty, and those names are
excluded from scoring with no record. A name that stopped trading before
`asof` therefore leaves the value universe invisibly. That is a selection
effect and must land in the coverage-gap bound per CLAUDE.md invariant 2, not
be swallowed. The same applies to names dropped by `compute_value_ratios`'
`not f.shares_outstanding` skip.

**4.5 Formation-date convention must be driven from month-end rebalances.**
`MomentumStrategy` treats the last calendar month present in the panel as the
formation month whether or not it is complete. Called on a real month-end this
is the textbook formation point. Called mid-month, the formation price is the
`asof` price and the skip leg is the previous month-end, so the skip is less
than a full month. The engine must drive momentum from
`rebalance_dates(freq="month_end")`, or document the mid-month semantics. This
interacts with the M00 carried item about a spurious rebalance on a
range-terminal non-boundary day.

**4.6 Policy needed for the momentum overlap guard.** `generate_targets`
raises `ValueError` when the scored universe is too thin for `n_long` and
`n_short` to stay disjoint. Failing loudly is right, but an uncaught raise
mid-backtest aborts the whole run. M04 needs an explicit policy: abort, or
record the date as unscoreable and count it in the coverage gap. Silently
shrinking the books is not acceptable.

**4.7 A blend weakens the under-declaration guard for its children.** Every
child is handed the same context, built from the blend's union of
`DataRequirements`. That union is a superset of each child's own declaration,
so a child that over-reaches its own footprint raises `UndeclaredDataError`
standalone but not inside a blend. Acceptance criterion 3's guard does not
survive composition. Recommend the engine construct a per-child context from
that child's own `requires()` rather than reusing the blend's.

### To M06 (multiple-testing trials registry)

**4.8 Blend `strategy_id` over-differentiates.** It hashes the children's raw
config dicts, not their `strategy_id`s. Two consequences, both verified:
swapping the order of two children gives a different blend id for an identical
portfolio; omitting a child's default param gives a different blend id even
though the child ids are identical. Over-counting trials is the conservative
direction for a multiple-testing penalty, so this is not a bias risk, but the
registry cannot recognise that the same blend was run twice, which is part of
what it is for. Recommend canonicalising the blend id as an order-insensitive
function of the children's own `strategy_id`s and weights.

### Documentation defects (must fix; no code change)

**4.9 The "byte-identical" claim is not exact.** HANDOFF.md and
`fundamentals()`'s docstring both state that `filing_lag_sessions=0` is
byte-identical to the pre-extension gate. It is identical for a session
`asof`, but for a non-session `asof` the old code gated at `filed <= asof`
while the new code gates at the last session on or before `asof`. For a
Saturday `asof` of 2020-01-18 the gate moves to 2020-01-17. This is strictly
narrower, so the restrict-only guarantee is unharmed and the change is in the
conservative direction, but the wording should read "identical for a session
asof, strictly narrower otherwise", because a future reader will rely on the
stronger claim.

**4.10 `configs/strategies/value_composite.yaml:2-4` is stale and actively
misleading.** The comment says `filing_lag_sessions` is "currently
unenforceable - see ... the escalation". The escalation was resolved in this
same milestone and the parameter is enforced. Same as REVIEW.md minor 1. A
future reader is told the DECIDED conservative default is inert when it is
not, which is the worst direction for a comment about a bias guard to be
wrong in.

---

## 5. Note on REVIEW.md's minors

Minor 1 is upgraded to a must-fix documentation defect at 4.10, not because it
blocks the milestone, but because it misstates the status of a bias guard.
Minor 2 is discharged: I wrote the missing end-to-end split-spanning test at
the gate (1.4) and it passes exactly. Minor 3 (per-ticker `ctx.prices` calls
in a loop) is a performance note and I have nothing to add, beyond observing
that each such call also refetches and re-slices that ticker's corporate
actions, so the cost is larger than it looks once M04 wires in a real provider.
