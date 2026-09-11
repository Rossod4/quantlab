# Carried-forward quant-gate notes

Non-blocking hazards flagged at earlier gates; each milestone packet below MUST address
its items (developer: implement or justify; quant-gate: verify closure).

## From M00 verdict (plans/state/M00/VERDICT.md)
- **→ M01:** `Bar` has no OHLC sanity validation — enforce at the ingestion boundary
  (quality.py), raising/flagging via `DataQualityError`. [folded into M01 packet]
- **→ M02:** `adj_close` is look-ahead-contaminated by nature (future splits/divs baked
  in). PITDataContext must not expose it for decision-making: either adjust as-of, or
  reserve adj_close strictly for return accounting, never signals. Also: frozen pydantic
  models are shallow — inner dicts of TargetWeights/PortfolioSnapshot mutable; PIT
  snapshot caching must defensively copy or deep-freeze.
- **→ M04:** `rebalance_dates(month_end|weekly)` emits a spurious rebalance on a
  range-terminal non-boundary day (e.g. window ending 2023-06-15 books a rebalance on
  6/15). Engine must handle explicitly (drop terminal partial period or document).
- **→ M04:** `prev_trading_day` is strict for session inputs — do not repurpose for
  inclusive PIT as-of alignment.

## From M01 verdict (plans/state/M01/VERDICT.md)
- **→ M02:** the delisted-ticker "known empty range" cache metadata cannot distinguish
  a real delisting from a one-time truncated vendor response — a transient truncation
  gets frozen as "complete" and later data is permanently masked. Cannot inject future
  into past (coverage-only risk), but survivorship.py must surface such masked ranges
  in the coverage gap, and the M09 data-refresh path should offer a metadata-invalidate.
- **→ M02 (reinforces existing note):** adj_close must be gated out of signal-visible
  paths in PITDataContext, and tests/canaries must include a canary asserting signal
  code cannot receive adj_close.

## From M02 verdict (plans/state/M02/VERDICT.md)
- **→ CLOSED at M02b cycle 2 (ACCEPT, plans/state/M02b/VERDICT.2.md). M03 momentum is
  UNBLOCKED.** The as-of adjustment replay shipped in `data/adjustment.py`, wired into
  `PITDataContext.prices()`, parity-fixtured, and canary-pinned; the actions-cache
  staleness policy and its fetch-failure hole are both closed. Cross-time price
  signals on `prices()` are now permitted — using `close`, never `raw_close` (see the
  M02b carried items below). Original requirement, for the record:** as-of
  adjustment replay. `prices()` is raw/unadjusted; a 12-month momentum across a 10:1
  split reads -90% on a flat stock (verified at the gate). Required: adjusted decision
  prices = raw close × cumulative factor from corporate-action events with
  ex-date <= asof; parity fixtures with hand-computed factors for real sequences
  (e.g. AAPL/TSLA 2020-08-31 splits + a dividend run); explicit decision whether this
  changes `prices()` semantics or adds an accessor BEFORE the Strategy ABC freezes;
  an adversarial actions-path canary; actions-cache staleness handling (fetch-once
  cache is blind to splits after fetch time). Any M03 signal comparing `prices()`
  values across time before this lands is a REJECT at the gate. Planner declining
  this sequencing = ESCALATE-TO-HUMAN.
- **→ M03/M04: CLOSED at M03 (ACCEPT, plans/state/M03/VERDICT.md §3).** The DECIDED
  one-session lag ships as `PITDataContext.fundamentals(ticker, *,
  filing_lag_sessions=0)` (restrict-only; negative raises `ValueError`) forwarded by
  a `ValueParams.filing_lag_sessions` defaulting to 1 and wired into
  configs/strategies/value_composite.yaml. Gate-verified end to end: the default
  hides a same-day after-hours filing that would otherwise flip the selection.
  Original requirement, for the record:** EDGAR gate is day-granular
  (`filed <= asof`): a same-day, often after-hours filing is visible to a same-day
  close decision. Adopt a one-session filing lag (or evaluate fundamentals at the
  prior session), or document and defend the convention in the backtest spec.
- **→ M04:** before BacktestResult embeds `overall_bound`: sample membership at
  rebalance dates (or quarter-ends, as the old script did) rather than year-ends, or
  relabel the bound "worst sampled year-end"; and the PriceAvailability constructor
  must populate `masked_end` from cache sidecar metadata, else masked truncations go
  uncounted by design.
- **→ M04:** forced delisting exits (CLAUDE.md invariant #3) must trigger on "price
  series ends before window end" itself, not solely on `infer_delisting()` events —
  the deliberately conservative inference under-detects when index removal precedes
  the final trade.

## From M02b verdict (plans/state/M02b/VERDICT.md, confirmed at VERDICT.2.md)

**All four M03-addressed items below are CLOSED at the M03 gate (ACCEPT,
plans/state/M03/VERDICT.md §3), verified by the gate's own probes, not by
re-reading the handoff: (value leg) the composite selection through the full
`generate_targets` pipeline on a split-spanning fixture is identical to the hand
computation using raw price at asof x filing in force — but see "From M03 verdict"
item 1 below for the residual stale-share-terms hazard this exposed; (ABC docs +
canary) the rule is stated as binding in `strategies/base.py` and the canary fails
with score -0.9 under the `raw_close` mutation; (volume) documented, and grep
confirms no strategy reads `volume` in executable code; (raw OHL) documented as an
escalation trigger, no plugin calls `prices_for_returns()`. The M04/M09 items below
remain OPEN against their own milestones. Original text retained for the record:**

- **→ M03 (value leg):** `prices()['close']` is a total-return-comparable LEVEL, not
  a traded price, for every row before the last gated ex-date — splits rescale it to
  as-of share terms and dividends subtract accumulated distributions. Level metrics
  (P/E, P/B, market cap, penny-price floors) must read the `asof` row, where the
  factor is exactly 1.0 and the value is the true traded price, or else use
  `raw_close`. A per-share figure from a pre-split filing NEVER reconciles with a
  split-adjusted historical price; pairing raw price at t with the filing in force
  at t is the consistent combination.
- **→ M03 (Strategy ABC):** `raw_close` is strategy-visible in `prices()` and still
  carries the full split discontinuity (the M02 verdict's -90%). The ABC docs must
  state that cross-time price signals use `close` and never `raw_close`; consider a
  canary asserting a momentum computed on `raw_close` is not what the engine feeds a
  strategy.
- **→ M03:** `volume` is the ONLY unadjusted column left in `prices()` — M02b cycle 2
  applies the identical per-date factor to `open`/`high`/`low` as to `close`, so
  `low <= close <= high` now survives a gated ex-date. A split multiplies share volume
  by the ratio, which the replay does not model, so any dollar-volume or turnover
  liquidity screen spanning a split is still discontinuous. Never multiply `volume` by
  an adjusted price column across an ex-date.
- **→ M03/M04:** raw `open`/`high`/`low` are no longer retained by `prices()` — only
  `raw_close` is. A rule needing the true traded intraday range (a stop-loss level, a
  gap or limit-price check) must take it from `prices_for_returns()`, which is the
  accounting path and still carries raw OHLC.
- **→ M04 (engine):** a stale or unfetchable actions history now BLOCKS `prices()` for
  the whole call (`StaleActionsCacheError` / `ActionsFetchError`, uncaught). Correct
  and deliberate — but the engine must decide what a rebalance does when one ticker in
  the universe fails. Dropping the offender and continuing is a selection effect: it
  must be counted in the coverage gap (CLAUDE.md invariant #2), not swallowed.
- **→ M04 (paper/live runner):** actions-cache staleness is day-granular and
  fetch-once. A run whose `asof` advances past the cache's `fetched_at` starts
  raising `StaleActionsCacheError` mid-run. The runner needs an explicit refresh
  policy, not an incidental one.
- **→ M09 (data refresh):** `refresh_actions_cache()` has no operational caller — no
  CLI subcommand, no network-tier path. It is the ONLY way to clear a
  `StaleActionsCacheError`, and a pre-M02b actions cache raises on every `prices()`
  call, so today there is no in-product recovery. Wire it into the data-refresh
  command alongside the M01 metadata-invalidate note above.

## From M03 verdict (plans/state/M03/VERDICT.md)

- **→ CLOSED at M03b (ACCEPT, plans/state/M03b/VERDICT.md §1.1/§3).** `PITDataContext.
  fundamentals()` now restates `shares_outstanding` (`*= factor`) and `ttm_eps`
  (`/= factor`) into as-of share terms using splits with `filed < ex_date <= asof`,
  from the same gated actions path `prices()` uses. Re-measured at the gate on the
  ORIGINAL M03 fixture: SPLT's P/E 6.25 → 25.0 and P/B 0.417 → 1.667 (both within
  1e-9 of truth), its composite rank 1-of-4 → 4-of-4, and it is now EXCLUDED from the
  book instead of selected into it. Frozen EDGAR numerics verified byte-identical over
  4,000 randomised differential trials. One narrower residual survives — see "From M03b
  verdict" item 1 (TTM EPS mixed-share-terms sum). Original finding, for the record:**
  per-share fundamentals go stale across a split
  between the filing date and the decision date. `market_cap = raw_close(asof) *
  shares_outstanding` and `pe = raw_close(asof) / ttm_eps` pair a post-split price
  with pre-split share terms; the error is the full split ratio. Measured at the
  gate on a 4:1 split 30 days after the filing: P/E reads 6.25 vs 25.0, P/B 0.417 vs
  1.667, and the name moves from the WORST composite rank (0.875) to the BEST (0.250)
  and into the book. Not look-ahead, and inherited from the old repo (frozen by
  CLAUDE.md invariant #4), but adverse in direction: splits follow big run-ups, so
  the value book is biased toward buying recent winners and calling them cheap. Fix
  needs the filing date or a restatement exposed through the data layer (restate
  per-share figures by the cumulative split factor for ex-dates in (filed, asof], or
  price off `raw_close` at the filing date). That is a data-layer change and may
  warrant its own packet rather than M04 — orchestrator's call. Until resolved, no
  M04 value or blend result should be quoted without this caveat.
- **→ M04 (engine), MATERIAL:** the blend nets WEIGHTS; the old repo blended each
  sleeve's NET returns (`combine_strategies`). Gross returns are identical (linear in
  weights); net-of-cost returns are not, because turnover and borrow are not. Measured
  at the gate: 30 names long in the value sleeve and short in the momentum sleeve
  cancelled to zero weight, taking gross from 1.5 to 0.5. An engine charging spread
  and borrow on the netted book charges nothing for those positions where the old repo
  charged both sleeves. M04 must decide explicitly — costs per sleeve or on the netted
  book — and document it; the netted book understates costs and flatters the blend.
- **→ M04 (engine):** `strategies/momentum._month_end_prices` pivots on calendar
  months PRESENT in the panel, so a month with no rows for any ticker produces no row
  and the 12-rows-back lookup silently reaches 13 calendar months back, for every name
  at once. The old repo's `resample("ME").last()` emitted an all-NaN row, which
  `compute_momentum_signal` correctly excluded. Reproduced at the gate: deleting
  Nov-2019 moved the lookback row from 2019-06-30 to 2019-05-31. Engine must assert
  the month index is contiguous (or reindex to a full month range) before signalling.
- **→ M04 (engine):** the value leg drops unpriceable names silently —
  `_asof_raw_price` returns None on an empty `ctx.prices([t], 1)`, and
  `compute_value_ratios` skips `not f.shares_outstanding`. Names that stopped trading
  before asof leave the value universe with no record. Selection effect: must land in
  the coverage-gap bound (CLAUDE.md invariant #2), not be swallowed.
- **→ M04 (engine):** `MomentumStrategy` treats the LAST calendar month present in
  the panel as the formation month, complete or not. Textbook on a real month-end;
  mid-month the formation price is the asof price and the skip leg is the previous
  month-end, i.e. a sub-one-month skip. Drive momentum from
  `rebalance_dates(freq="month_end")` or document the mid-month semantics. Interacts
  with the M00 item on a spurious rebalance at a range-terminal non-boundary day.
- **→ M04 (engine):** momentum raises `ValueError` when the scored universe is too
  thin for `n_long` + `n_short` to stay disjoint. Failing loudly is right, but an
  uncaught raise aborts the whole backtest. Needs an explicit policy: abort, or record
  the date as unscoreable and count it in the coverage gap. Never silently shrink the
  books.
- **→ M04 (engine):** a blend hands every child the SAME ctx, built from the blend's
  UNION of `DataRequirements` — a superset of each child's own declaration. A child
  that over-reaches its own footprint raises `UndeclaredDataError` standalone but NOT
  inside a blend, so acceptance criterion 3's guard does not survive composition.
  Engine should construct a per-child ctx from that child's own `requires()`.
- **→ CLOSED at M03b (ACCEPT, plans/state/M03b/VERDICT.md §1.6/§3).**
  `BlendStrategy.strategy_id` now hashes a sorted list of `(child.strategy_id, weight)`
  pairs plus the blend's own non-`children` params. Gate-verified: child-order swap and
  omitted child defaults give the SAME id; a weight change, a child param change,
  swapping the two weights BETWEEN children, and nesting a blend as a child all still
  give different ids. See "From M03b verdict" item 4 for the separate registry-keying
  gap this exposed. Original item, for the record:** the blend's `strategy_id` hashes
  the children's RAW
  config dicts, not their `strategy_id`s. Verified at the gate: swapping child order
  gives a different id for an identical portfolio, and omitting a child's default
  param gives a different id though the child ids are identical. Over-counting trials
  is the conservative direction for the multiple-testing penalty, so not a bias risk —
  but the registry cannot recognise a repeat of the same blend, which is part of its
  job. Canonicalise the blend id as an order-insensitive function of the children's
  own `strategy_id`s and weights.
- **→ CLOSED at M03b (gate-verified in the working tree).** Both wordings fixed:
  `fundamentals()`'s docstring now reads "identical ... for a session `asof` ... and
  strictly narrower - never wider - for a non-session `asof`", and
  `configs/strategies/value_composite.yaml` now says the lag IS enforced. Original
  item, for the record:** two stale claims shipped in M03.
  (a) HANDOFF.md and `PITDataContext.fundamentals()`'s docstring say
  `filing_lag_sessions=0` is "byte-identical" to the pre-extension gate — true for a
  SESSION asof, but for a non-session asof the old code gated at `filed <= asof` and
  the new code gates at the last session on or before it (Saturday 2020-01-18 -> gate
  2020-01-17). Strictly narrower, so restrict-only is unharmed; reword to "identical
  for a session asof, strictly narrower otherwise". (b)
  `configs/strategies/value_composite.yaml:2-4` still says the lag is "currently
  unenforceable - see ... the escalation"; the escalation was resolved in the same
  milestone and the parameter IS enforced. Delete or rewrite — a comment claiming a
  live bias guard is inert is wrong in the worst direction.

## From M03b verdict (plans/state/M03b/VERDICT.md)

- **→ M04, or a follow-on data-layer packet:** TTM EPS can still be a MIXED-share-terms
  sum. `ttm_eps_filed` is the LATEST filed date among the summed components, which is
  the right date only when every component is stated in the terms in force on it. True
  once a later filing's restated comparatives are in the facts (the dedup then makes the
  answer exact, gate-verified), and on the annual-fallback path. NOT true in the window
  between a split and the filing that restates the comparatives, when the TTM comes from
  four standalone quarters. Measured at the gate: a 4:1 split between the 2nd and 3rd
  component filings leaves `ttm_eps` at 10.0 against a correct 4.0 (2.50x overstated),
  so P/E is understated by the same factor and the name looks CHEAP — the same adverse
  direction as the original M03 hazard. Bounded, and much smaller than M03's:
  `shares_outstanding` is never affected, so market cap, P/B and EV/EBITDA stay exact;
  only the P/E leg (and the growth-adjusted leg derived from it) moves. On the gate's
  own fixture it shifted the composite 0.917 → 0.750 without changing the rank or the
  selection. Correct fix = restate EACH component by the splits after ITS OWN filed date
  then sum, which needs per-component data out of the provider (data-layer change, not
  engine work). Until then an M04 value result must carry this caveat for names that
  split during the window.
- **→ M04 (test, must-fix):** the window's LOWER bound `filed <` is untested.
  Mutation-confirmed at the gate: changing `_split_factor_since_filed`'s
  `splits.index > filed` to `>= filed` leaves the full suite green at 226 dots. This is
  the mirror of the blocker code review caught on the UPPER bound and it survived both
  review iterations because both mutations aimed at the right edge. Add a test pinning a
  split ex-dated exactly ON the filed date (factor 1.0). Decide it deliberately: the two
  readings fail in OPPOSITE directions — shipped `<` leaves a non-restated figure stale
  and the name looks cheap (spurious BUY); `<=` double-restates a compliant filer's
  figure and the name looks expensive (missed name). Shipped side is correct on ASC 260
  (a same-day split precedes intraday issuance) but is the side whose failure mode is a
  spurious buy. Related nuance for the same test: for `shares_outstanding` the governing
  date is the cover page's "latest practicable date", which PRECEDES the filing date, so
  keying that field on `filed` is slightly too late and errs the same adverse way —
  worth a docstring sentence even if the code keeps using `filed`.
- **→ M04 (engine):** `fundamentals()` now depends on the corporate-actions path.
  Gate-verified: with a raising actions provider and `needs_actions=False`,
  `fundamentals()` propagates the failure. `_gated_actions_by_ticker` is deliberately
  independent of `DataRequirements.needs_actions` (already true for `prices()`), but
  this is NEW for `fundamentals()`, so a stale or unfetchable actions cache now blocks
  the VALUE leg too, for a strategy that declares no actions need. Correct — silently
  skipping the restatement would reintroduce the hazard — but M04 needs ONE policy
  covering both paths, and dropping the offending ticker must be counted in the coverage
  gap (CLAUDE.md invariant #2). Reinforces the open M02b item on a blocked ticker at a
  rebalance.
- **→ M06 (trials registry):** `strategy_id` does not encode DATA SEMANTICS, so a
  config's id is stable across a change that alters its results.
  `value_composite-b6fdfec048` is byte-identical before and after M03b even though the
  strategy's output on a split-spanning universe changed materially (momentum ids are
  unchanged too, correctly, since nothing about them moved). The registry keys on
  `strategy_id`, so pre- and post-M03b runs of the same YAML would record as the SAME
  trial and a genuine change in results would read as noise. Key the registry on
  `strategy_id` PLUS a platform/data-semantics version, and record M03b as the first
  boundary.
- **→ M04 (minor, perf):** repeated per-ticker fetches compound. `fundamentals()` fetches
  the ticker's full actions history on every call and `value.py`'s `_asof_raw_price`
  already fetches the same history again via its per-ticker `ctx.prices([t], 1)` — two
  full action fetches per ticker per rebalance, inside a Python loop over the universe.
  Separately `BlendStrategy.strategy_id` reconstructs every child through
  `load_strategy` on each access and `generate_targets` reconstructs them again.
  Correctness unaffected; reinforces M03 REVIEW.md minor 3. Worth one batching pass when
  M04 wires in a real provider.
