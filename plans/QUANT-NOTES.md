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

## Closure status of every M04-addressed item, at the M04 gate cycle 1 (plans/state/M04/VERDICT.md)

Recorded here as a block rather than as inline edits so the original wording of each
item above stays intact for the record. Verdict: REJECT — items 3 and 6 below are the
only ones that do not close.

1. **M00, spurious terminal rebalance — CLOSED.** `_drop_terminal_partial_period` +
   `_is_genuine_period_boundary` in `backtest/engine.py`, with a test at a non-boundary
   end date (2020-06-15 → last kept date 2020-05-29) and a companion test that a genuine
   final boundary is kept.
2. **M00, `prev_trading_day` not repurposed — CLOSED.** Gate-verified by grep: it is not
   referenced anywhere in `src/quantlab/backtest/`.
3. **M02, coverage bound at rebalance dates + `masked_end` populated — REMAINS OPEN.**
   Both mechanisms shipped and are tested (`coverage_gap(sample_dates=)`;
   `price_availability_from_cache` against a real cache dir), but the engine feeds
   `price_availability_from_cache` the set of names the strategy HELD rather than the
   universe, so `overall_bound` measures "fraction of the index not bought" and the
   masked-truncation path is never reached for a name the strategy stopped holding. See
   VERDICT.md finding 1, with a reproduction (10-name fully-cached universe, top-3
   strategy, bound reads 70.0 against a truth of 0.0).
4. **M02, forced exit triggers on "price series ends" not solely `infer_delisting` —
   CLOSED.** The engine checks only the superset condition; `infer_delisting` is not
   called in the hot path and no `legacy_drop`/drop-from-average fallback exists in
   `src/quantlab/backtest/`. (The RETURN booked on that path is wrong for a separate
   reason — VERDICT.md finding 3 — but the trigger itself is right.)
5. **M02b, raw OHL reachable only via `prices_for_returns` — CLOSED as documented.** No
   plugin calls it. See the new M05/M09 item below on the accessor being reachable from a
   strategy's own decision context.
6. **M02b/M03b, one per-ticker data-failure policy covering `prices()` and
   `fundamentals()`, counted rather than swallowed — CLOSED on the policy, deliberately
   divergent on the counter.** `_FilteringConstituentsProvider` probes the shared
   corporate-actions fetch at context-construction time, so one policy and one counter
   serve both accessors; the >5% abort path and a literal `ValueStrategy` hostile-actions
   case are both tested. The drops land in `quality_flags.dropped_tickers_by_date`, NOT
   in `coverage_report`, which is a documented divergence from the packet's literal
   wording; the reasoning (a per-rebalance, often non-price event cannot be expressed in
   a per-ticker, per-year price-availability model without overstating the year's gap) is
   accepted at this gate as it was at code review. See the new M06/M07 item below.
7. **M02b, paper/live runner actions-cache refresh policy — NOT M04.** Paper trading is
   explicitly out of the M04 packet's scope. Carries forward unchanged.
8. **M03, blend costs netted vs per-sleeve — CLOSED.** Netted by construction (the engine
   diffs consecutive already-blended `TargetWeights`), per the orchestrator's decision,
   documented in `configs/backtests/blend_50_50_2012_2026.yaml` and in `engine.py`, with a
   magnitude test (0.30 per-sleeve turnover vs 0.0 netted on the offsetting fixture).
9. **M03, month contiguity — CLOSED.** `momentum._month_end_prices` reindexes to the full
   contiguous month range; the test deletes a month and asserts an all-NaN row rather
   than a silent 13-month lookback.
10. **M03, value-leg silent drops surfaced — CLOSED into `quality_flags.unscored_by_date`.**
    Generalised to any strategy (declared universe minus weights keys). Same deliberate
    divergence as item 6 on where it is counted.
11. **M03, formation-month semantics — CLOSED as documented** (developer's call, which the
    packet explicitly allowed): mid-month `asof` is documented as unsupported in
    `momentum.py`'s module docstring rather than enforced by raising.
12. **M03, unscoreable-date policy — CLOSED.** `abort_on_unscoreable` defaults True;
    abort and record-and-hold-prior are both tested, and a forced-exited name's freed
    weight goes to cash rather than being redistributed.
13. **M03, per-child context for blends — CLOSED.** `set_context_factory` on the blend,
    wired by the engine, with a bug-reproduction pair (an overreaching child does not
    raise without the factory, does raise with it), a spy proving each child gets its own
    `requires()`, and a nested blend-of-blends propagation test.
14. **M03b, TTM EPS mixed-share-terms caveat — CLOSED.** `provenance.known_caveats` is
    populated whenever the strategy declares `ttm_eps`; gate-verified present and
    JSON-round-tripping.
15. **M03b, the `filed <` LOWER bound is untested — CLOSED.**
    `tests/test_share_terms.py::test_split_exactly_on_the_filing_date_has_zero_effect`
    pins the boundary and `test_split_one_day_after_the_filing_date_is_applied` pins the
    other side.
16. **M03b, per-context actions memoisation — CLOSED.** `PITDataContext` caches each
    ticker's gated actions frame per instance and returns a copy; three call-count tests
    cover the shared fetch, per-ticker independence, and no leakage across instances.
    Blend child construction is cached separately.
17. **Packet item 11, semantics version — CLOSED.** `core/semantics.py` defines
    `DATA_SEMANTICS_VERSION = "m03b"`; gate-verified in `provenance`.

## From M04 verdict (plans/state/M04/VERDICT.md)

- **→ M05 (metrics):** never compute metrics from `BacktestResult.snapshots`. The ledger
  track runs on raw prices and never credits dividends, so it diverges from
  `net_equity` by roughly the cumulative dividend yield — on the order of 30% over the
  shipped 2012–2026 window at 2%/yr, not the `cost * gross` cross term `engine.py`'s
  module docstring claims. Gate-verified: on a $5-dividend fixture the return series moved
  +5.2632% while the ledger stayed exactly flat. Metrics belong on
  `net_returns`/`net_equity`; `snapshots` is for position inspection only. The docstring's
  "agree to first order" sentence should be corrected when M04 is re-cut.
- **→ M05 (metrics) / M06 (validation):** `quality_flags.extreme_returns` counts a
  RIGHT-TAIL-ONLY truncation of the return distribution. Excluding a genuine large winner
  lowers the measured mean (conservative) but also makes the series look more left-skewed
  and thinner-tailed on the right than reality, and skewness and kurtosis are direct PSR
  and DSR inputs. Any run with a nonzero count must surface it in the one-line summary and
  beside any PSR/DSR figure, not only inside the result object.
- **→ M05 / M07 (reporting):** `quality_flags.missing_forward_prices` is assigned the
  `forced_exits` counter itself (`engine.py:782`), not an independent measurement. Do not
  report it as a second, corroborating number.
- **→ M06 (trials registry):** `provenance.quantlab_git_sha` carries no dirty-tree flag.
  M04 itself ran from an uncommitted working tree, so the recorded sha names a commit that
  does not contain the code that produced the result. Record a `dirty: bool` (or the
  emptiness of `git status --porcelain`) alongside the sha, or the registry keys a trial
  to the wrong code. Compounds the existing M03b item about keying on `strategy_id` plus a
  semantics version.
- **→ M06 / M07:** `coverage_report.overall_bound` and
  `quality_flags.unscored_by_date`/`dropped_tickers_by_date` are, by the accepted
  divergence in item 6 above, deliberately separate measurements of two different selection
  effects. Any headline "how much of this book can I not trust" figure must combine both;
  reporting the bound alone understates. Once VERDICT.md finding 1 is fixed, the bound
  means: the worst single calendar year's percentage of that year's point-in-time index
  members — sampled at the last rebalance date in that year — with no cached price history
  at all or a cache metadata-masked before that date. It is a ceiling on names invisible to
  the strategy, never a return impact.
- **→ M07 (reporting):** whatever resolution ships for VERDICT.md finding 5, the report must
  state which price the entry is measured at. Today `next_open` mode fills the ledger at the
  next session's open while measuring returns close-to-close over the same dates, so the two
  tracks disagree about when the position started.
- **→ M09 (data refresh), reinforcing the open M02b item:** `refresh_actions_cache()` still
  has no operational caller, and M04 has now shipped a `quantlab backtest` CLI — so a stale
  actions cache is a user-visible run failure with still no in-product recovery path. Wire
  it into the data-refresh command alongside the M01 metadata-invalidate note.
- **→ M05 / M09 (canaries):** a strategy can call `ctx.prices_for_returns()` on its OWN
  decision context and receive `adj_close` plus raw OHL — gate-verified directly. This is
  inherited from M02/M03, not introduced by M04, and canary (i) is honest that it only
  asserts the engine never hands over a separate accounting-path context. The
  adj_close-out-of-signals guard is therefore convention plus per-plugin canaries, not
  construction. Consider a canary asserting no registered strategy's source calls
  `prices_for_returns`, so the M02b escalation trigger fires on the way in rather than at a
  later gate.

## Orchestrator decisions (recorded for the gate; Alex delegated these)
- **Capacity gate at retail stake, 2026-09-12 (M06 cycle-3 carried item, decided for M09):**
  Alex's real stake is £100–500. `intended_capital_usd` stays 1000; the capacity gate is
  demoted to a new `informational` class in configs/validation.yaml — always reported with
  the AUM ceiling, spread percentiles and the old repo's $95M–$335M context, never affecting
  the verdict. Flip back to soft in config if institutional size is ever traded.
- **M08 loop cap, 2026-09-12:** M08 exhausted the two quant-gate cycles (cycle 2 rejected on a
  regression introduced by the shared-filter fix: staleness swallowed → refresh never runs; plus
  an unjournaled broker.account failure). Escalated to Alex; Alex approved ONE narrow third
  cycle scoped to VERDICT.2.md (proactive sidecar-driven refresh per the packet's own text,
  guarded account fetch in _refuse, three non-blocking notes).

- **M06 loop cap, 2026-09-12:** M06 exhausted the two quant-gate cycles; escalated to Alex
  with a one-screen summary; Alex approved ONE narrow third cycle scoped to VERDICT.2.md
  (headline pinning in the overlap resolver, exception-path exclusion capture, DSR
  non-monotonicity disclosure, capacity trivial-pass sentence, RC/SPA size bound).

- **M06 finding 4 (purged CV on fixed-parameter strategies), 2026-09-11:** a purged
  K-fold cannot yield genuine out-of-fold evidence when nothing is refitted per fold.
  Decision: the gate and statistic are renamed `subperiod_oof_sharpe` with a reason string
  stating purge/embargo have no effect by construction; `purged_kfold_splits` stays as a
  tested utility; a genuine purged CV over the sensitivity grid (fit = best grid point per
  training fold) is carried to post-v1. No fake CV ships.
- **M06 finding 1 (DSR rising with N):** trials deduplicated by net-return hash; trial
  variance floored at the null sampling variance of a per-period Sharpe, 1/(n−1); SR* = 0
  only for N = 1. The "over-counting is conservative" claim is deleted everywhere.
- **M06 finding 3:** every gate uses the result's embedded benchmark by default; CLI
  override is loud on every reason line.

- **M04 finding 4 (extreme guard on shorts), 2026-09-11:** the old repo's
  `long_short_engine.py` (lines 280-291) applied the SAME upside-only glitch guard to the
  bottom (short) basket, with per-book counts. The engine's trigger is therefore inherited
  parity under CLAUDE.md invariant #4, not a new defect. Decision: keep the trigger as
  `extreme_return_policy=exclude_legacy` (default; parity), count per book
  (`extreme_returns_long` / `extreme_returns_short`), emit a `known_caveats` entry when the
  short book had exclusions ("short book flattered"), and offer `flag_only` (count, never
  exclude). The sign-aware trigger the M04 verdict proposed is NOT adopted for the parity
  default because it would change frozen numerics; it may be added as a third policy in a
  later packet if a long-short strategy is ever promoted. Long-only strategies are
  unaffected. Gate may REJECT this reasoning; if so the decision escalates to Alex.
- **M03 filing lag, M03 fundamentals() restrict-only extension, M03b (filed, asof] window,
  M04 netted-book blend costing, M04 unscoreable-date policy, M04 accounting=True gate:**
  recorded in the respective packets' "Carried from" sections and handoffs.

## M04 gate cycle 2 — ACCEPT (plans/state/M04/VERDICT.2.md)

M04 is **ACCEPTED**. Dispositions below supersede the cycle-1 block above where they
conflict. Verified by re-running the cycle-1 reproductions unchanged against the
iteration-3 tree, not by re-reading the handoff.

- **M04 item 3 (coverage bound over the universe) — NOW CLOSED**, reversing the cycle-1
  "REMAINS OPEN". `all_universe_tickers` accumulates the union of `ctx.universe()` across
  rebalances, separate from the held set, and their union feeds
  `price_availability_from_cache`. The gate's own fixture (10-name fully-cached universe,
  top-3 strategy) now reads `overall_bound == 0.0`, against 70.0 at cycle 1; an
  independent fixture with a never-held masked name reads 10.0, ruling out a false-clean
  zero. The bound now means what the cycle-1 verdict defined it to mean.
- **M04 verdict findings 1, 2, 3, 5 — CLOSED.** Haircut reaches the reported series
  (`net_equity` 1.00/0.75/0.50 at haircuts 0.0/0.5/1.0, matching the ledger exactly);
  forced exits use the total-return basis (the reverse-split-then-delist fixture books
  0.0000, against +450% at cycle 1) and are now covered by the extreme-return guard on
  that consistent basis; `next_open` measures open-to-open (confirmed on a panel whose
  open and close move by different amounts: reads +0.200000, the open-to-open truth, not
  the close-to-close +0.300000). Parity tests unmodified, 9 passing.
- **M04 verdict finding 4 — ACCEPTED as inherited parity, not fixed. The cycle-1 verdict's
  framing of the provenance was WRONG and is corrected here.** The gate read the old repo
  directly: `MomentumValueStrategy/src/backtest/long_short_engine.py:268-291` applies the
  same upside-only guard to the SHORT basket with per-book counts, and its own comment
  anticipates this exact hazard ("a >300% underlying gain, if REAL, would be a
  catastrophic loss to a short seller, and this guard would hide it — is exactly why the
  exclusions are counted per book"). The trigger is therefore frozen numerics under
  CLAUDE.md invariant #4 and changing it would have been the violation. The orchestrator
  decision recorded above is sound as stated. Accepted on four gate-verified conditions:
  counted per book (`extreme_returns_long`/`extreme_returns_short`, surviving
  `save`/`load`); a `known_caveats` entry naming the short book fires under the default
  policy and not under `flag_only`; `flag_only` returns the truth; and no shipped backtest
  config is exposed (all four resolve to long-only; `momentum_130_30.yaml` and
  `momentum_ls.yaml` are referenced by no backtest config). Measured magnitude on the
  gate's dollar-neutral fixture: `exclude_legacy` reports +0.0000 for a period whose truth
  is −2.5000, so the hidden amount is 250% of capital. Strictly better than the old repo,
  which had the same trigger and no opt-out.
- **M04 verdict finding 4, degenerate-book edge — CLOSED.** `_weighted_return_excluding`
  returns the affected book names and the engine records them in
  `quality_flags.degenerate_excluded_book_dates`.
- **Orchestrator-added item 6 (structural accounting gate) — CLOSED.**
  `PITDataContext.__init__` takes `accounting: bool = False` and `prices_for_returns()`
  raises `UndeclaredDataError` otherwise. Gate-probed with a hostile strategy calling it on
  every rebalance in three positions — top-level, blend child, and nested blend grandchild
  — 12 child invocations, all raising. The engine defines one `context_factory`, passes
  that same closure to `set_context_factory`, and never sets `accounting`; only
  `_accounting_context` passes `True` and it is never exposed to a strategy. Canary (j)
  pins it and is mutation-confirmed.

### Adjustments to "From M04 verdict" above

- **The M05/M09 canary note is now SUPERSEDED by item 6.** The accessor is no longer
  reachable from a decision context by any existing path, so the guard is structural
  rather than convention plus per-plugin canaries. The residual is narrower and stays as a
  note for M09: a strategy that deliberately does `object.__setattr__(ctx, "_accounting",
  True)` can still reach it — gate-confirmed. No Python guard can prevent that and it
  requires obviously-subversive code, so the structural default plus canary (j) is the
  right level. A source-level canary asserting no registered strategy's source calls
  `prices_for_returns` remains optional belt-and-braces, no longer a gap.
- **The M05 note on `snapshots` is partly discharged.** `engine.py`'s module docstring no
  longer claims the ledger and `net_equity` "agree to first order" and now states plainly
  that M05+ must compute metrics from `net_returns`/`net_equity` only. The underlying fact
  is unchanged and the note stands as a binding instruction to M05, not as a defect.
- **The M05/M06 note on right-tail truncation now also covers the short book.** With
  `exclude_legacy` the truncation is upside-only on price, which on a short book removes
  the worst losses. Any long-short result must be read with `extreme_returns_short` and the
  `known_caveats` entry beside it, and M05's one-line summary must surface both.
- **The M06 dirty-tree-sha note and the M05/M07 `missing_forward_prices` note stand
  unchanged** — deliberately left open at this gate, neither being one of the five numbered
  findings.

### New carried item

- **→ whichever milestone first promotes a long-short strategy (not M05–M07 as currently
  scoped):** before any long-short or 130/30 result is quoted, decide the extreme-return
  trigger deliberately. The `exclude_legacy` default hides a short squeeze — the single
  worst outcome a short book can have — and the gate measured 250% of capital hidden on a
  contrived but not pathological fixture. The options are the sign-aware trigger the M04
  verdict proposed (`w * r > bound * abs(w)`, which changes frozen numerics and so needs
  its own parity decision), or `flag_only` as the default for long-short configs. Do not
  ship a long-short config on `exclude_legacy` without stating the choice; a referee will
  ask what the guard did to the short book's tail.

## From M05 verdict (plans/state/M05/VERDICT.md)

### Closure of the M05 items carried from M04

- **M04 item 1 (never compute metrics from `snapshots`) — CLOSED.** `metrics.summary()`
  reads only `net_returns`/`gross_returns`/`net_equity`/`gross_equity`/`turnover` and the
  benchmark series; `rolling.py` reads only `net_returns`. Gate-verified: the `Exploding()`
  sentinel test, which raises on any attribute or item access to `snapshots`, passes.
- **M04 item 3 (`missing_forward_prices` never a second number) — CLOSED.** The string
  appears nowhere in `ValidationBasic.flags`; `forced_exits`, `extreme_returns_long` and
  `extreme_returns_short` are each reported once and the long/short split is preserved.
  **The "once each" half of the item is NOT closed for `unscored_by_date` and
  `dropped_tickers_by_date`** — both are stated twice, once inside the combined
  coverage-and-selection flag and again as standalone flags. VERDICT.md finding 3.
- **M04 item 4 (coverage bound and unscored/dropped are separate selection effects) —
  CLOSED.** `_coverage_and_selection_flag` is emitted unconditionally, combines all three
  numbers, and carries the mandated "SEPARATE selection effects ... not additive into one
  headline number" wording.
- **M04 item 2 (nonzero extreme counts beside any Sharpe figure) — PARTIALLY CLOSED.**
  Satisfied for `ValidationBasic.flags`; NOT satisfied for the `quantlab validate`
  one-liner, which prints Sharpe/Sortino/Calmar but no extreme counts. VERDICT.md finding 4
  rules this required, not deferred.
- **M05/M09 canary item — CLOSED.** `tests/canaries/test_no_prices_for_returns_in_
  strategies.py` ships with its own planted-violation test, so the AST scan is
  mutation-confirmed rather than merely currently-passing.

### New carried items

- **→ M07 (reporting), and M06 wherever it quotes a rolling number:** the frozen ported
  `standard_metrics`/`rolling_window_metrics` build each window's equity as
  `(1 + returns).cumprod()` with NO leading 1.0, so **every rolling window and every
  walk-forward comparison column silently omits its own first return**: that return is
  cancelled out of the CAGR numerator and is invisible to `max_drawdown`'s `cummax`. On a
  `[-0.50, +0.10, +0.10, +0.10]` window the gate measured Max Drawdown `+0.0000` against a
  truth of `-0.5000`. This is a faithful port (the old repo's `_window_metrics` is
  identical) and `tests/test_rolling.py:30`'s `expected_growth = 1.01**11` deliberately pins
  it, so it must NOT be "fixed" in the ported path. M07's report text must state it wherever
  a rolling or walk-forward comparison figure is printed, and M06 must not gate
  `max_drawdown_floor` on a rolling column without accounting for it. `subperiod_table` is
  new code and IS being fixed under VERDICT.md finding 1.
- **→ M06 (trials registry):** `sensitivity._strategy_id_for_point` hashes only the config
  stem plus the point's params. It ignores `backtest_config` entirely even though the
  function receives it, so the SAME grid run over a different start/end window, cost model
  or execution mode produces byte-identical trial ids — gate-verified by rerunning a 9-point
  grid under a 2005–2010 config and a 2015–2020 config and getting the same nine ids.
  Two genuinely different trials then collide in the registry. This compounds the existing
  M03b/M04 items about `strategy_id` not encoding data semantics and about
  `provenance.quantlab_git_sha` carrying no dirty-tree flag. The registry key needs config
  and semantics, not just params.
- **→ M06 (trials registry):** the sensitivity trial id scheme is deliberately independent of
  `Strategy.strategy_id` (stated in `sensitivity.py`'s module docstring), so M06 cannot
  reconcile the base grid point with the headline run and will count it twice under two
  different ids. Over-counting N is conservative for DSR so this is not a defect, but M06
  should state which it is doing rather than leave the double entry unexplained.
- **→ M06 (verdict thresholds):** `no_cliff_score` is a relative-spread statistic over the
  neighbourhood's Sharpe multiset — it never reads the base point's OWN value, so it scores
  "base is the peak beside a cliff" and "base is the trough between two good points"
  identically (gate-measured: both `-1.0000` on `{-1, 1, 1}` versus `{1, -1, 1}`). It is a
  roughness detector, not a cliff-edge detector. Related: a uniformly terrible but flat
  neighbourhood (every point Sharpe `-0.80`) scores a perfect `+1.0000` and would pass
  `min_no_cliff_score: 0.5`. That is correct behaviour for a spread statistic and is
  harmless only because `min_net_sharpe: 0.3` gates separately — M06 must apply both, and
  must never quote the no-cliff score as evidence of quality.
- **→ M06:** `no_cliff_score`'s spread uses builtin `max()`/`min()`, which do NOT skip NaN,
  while its median uses `pd.Series.median()`, which does. A NaN Sharpe anywhere in the
  neighbourhood therefore makes the score depend on the order the grid was enumerated in.
  Unreachable today (a degenerate zero-vol backtest is needed), but M06 will run the grid on
  real strategies where a failed or degenerate point is possible. Make NaN handling explicit
  and deterministic, and count NaN points rather than absorbing them.
- **→ M06 / M07:** `walk_forward_blend` inserts no purge or embargo between a training block
  and the test block that immediately follows it. For already-realised strategy period
  returns this is standard walk-forward and the gate found no self-influence (verified with
  a planted fixture), but M06's purged-CV work should state why the walk-forward needs no
  embargo while the CV does, rather than leaving the asymmetry unexplained.
- **→ M06 / M07:** `walk_forward_blend`'s blend-of-net-returns convention is documented
  thoroughly and correctly in the module docstring, including an explicit "do not substitute
  for an M04 blend backtest's `net_returns`". The residual: the weight-choice stability
  conclusion transfers to the real netted-cost book only if the Sharpe RANKING across grid
  points is the same under both conventions, and nothing tests that. Before M07 quotes a
  walk-forward conclusion about a blend that will actually be traded, check the ranking
  agrees, or say that it was not checked.
- **→ M06 / M07:** `walk_forward_blend`'s tie-break is `s > best_sharpe` seeded from the
  first grid point. If the FIRST grid point's training Sharpe is NaN (zero-vol training
  window), every subsequent comparison against NaN is False and that step locks in the first
  weight tuple regardless of the others. Inherited from the old repo and frozen, so flag it
  rather than fix it; M06 should assert no chosen step had a NaN training Sharpe.
- **→ M06 / M07:** `metrics.summary()` computes `beta`, `information_ratio` and
  `tracking_error` on whatever dates the strategy and benchmark happen to share, and records
  the overlap nowhere. Gate-measured: beta moved from `-0.1602` to `-0.4855` and the
  information ratio flipped sign when the benchmark covered 6 of 60 months, silently. If
  VERDICT.md finding 6 is not fixed in M05, M06 must not print beta or IR without the
  overlap count beside them.
- **→ M06 / M07:** the "benchmark Sharpe exceeds strategy Sharpe" flag is a bare
  `benchmark_sharpe > net_sharpe` comparison, so it never fires when `benchmark_sharpe` is
  NaN (degenerate or missing benchmark). The report card then shows `beta: nan`,
  `benchmark_sharpe: nan` with no flag explaining why. Add an explicit "no usable benchmark"
  flag rather than relying on a comparison that silently abstains.
- **→ M06 / M07:** `sortino` uses target 0 and full-sample N (ddof=0) while `sharpe_ratio`'s
  denominator is `pd.Series.std()` at ddof=1. The Sortino convention is the standard
  lower-partial-moment one and is the right choice, but the two ratios are not on the same
  denominator footing and the docstring states neither. Whoever prints them side by side
  must say so.
- **→ M09 (canaries):** unchanged from M04 — a strategy that deliberately does
  `object.__setattr__(ctx, "_accounting", True)` can still reach `prices_for_returns`. The
  new M05 AST canary narrows this further at the source level but cannot close it.

### Adjustments to "From M05 verdict" above (M05 cycle 2, plans/state/M05/VERDICT.2.md)

M05 was ACCEPTED at cycle 2. All four blocking findings and both non-blocking findings from
cycle 1 are fixed, plus the three orchestrator-added items. The items above are amended as
follows; where an item is marked DISCHARGED it needs no action from a later milestone.

- **The M04 carried items are now ALL CLOSED.** Item 2 (nonzero extreme counts beside any
  Sharpe figure) is closed: the `quantlab validate` one-liner now carries
  `extreme_returns_long=N extreme_returns_short=M` when either is nonzero, and omits them
  when both are zero — gate-verified end-to-end through the real CLI. Item 3's "once each"
  half is closed: the combined coverage sentence now states the relationship without
  carrying either number, and a gate probe with six mutually distinct counts confirmed every
  counter appears exactly once across all flags. Items 1 and 4 were already closed at cycle 1
  and still hold.
- **The M07/M06 item on first-return blindness STANDS, and is now documented in-tree.** The
  frozen `standard_metrics`/`rolling_window_metrics` path was correctly NOT changed: the gate
  reran the old repo's own functions against the new ones across four shapes with a −50%
  first return planted, and every cell matched at 0.000e+00, with Max Drawdown still reading
  +0.0000 on the −50%-opening window. `standard_metrics`'s docstring now states the blindness
  explicitly, names it frozen under CLAUDE.md invariant #4, and instructs against reusing the
  helper for any new surface where the first return matters; `rolling.py`'s module docstring
  repeats it. **M07 must still state it wherever a rolling or walk-forward comparison figure
  is printed, and M06 must still not gate `max_drawdown_floor` on a rolling column without
  accounting for it.** The `subperiod_table` half of the item is DISCHARGED — that table now
  rebases from the true prior boundary in `net_equity` and reconciles to the headline curve
  exactly (all six shipped regimes at +0.0000 error, growth product on the table's own
  `Growth` column at 0.000e+00).
- **The M06 item on trial ids ignoring `backtest_config` — DISCHARGED.**
  `_strategy_id_for_point` now fingerprints `start`/`end`/`execution`, the four cost-model
  fields and `DATA_SEMANTICS_VERSION` alongside the params. Gate-verified: the same 9-point
  grid over a different window shares no id with the base run, a 25bps cost change shares no
  id, and the same config reruns to identical ids. This also partly discharges the standing
  M03b/M04 note about `strategy_id` not encoding data semantics — for sensitivity trials
  specifically; the note still stands for `Strategy.strategy_id` itself.
- **The M06 item on `no_cliff_score` NaN order-dependence — DISCHARGED.** NaN neighbours are
  filtered once before max/min/median, and `nan_points` records how many were excluded. The
  gate confirmed the original defect was real (builtin max/min give spread 1.0 on
  `[1.0, nan, 2.0]` and nan on `[nan, 1.0, 2.0]`) and that it is gone: identical scores under
  opposite axis enumeration orders, and an all-NaN neighbourhood returns NaN rather than a
  spurious 1.0 "perfectly flat".
- **The M06/M07 item on the benchmark comparison abstaining on NaN — DISCHARGED.** A
  degenerate benchmark now emits `no usable benchmark Sharpe (NaN) - cannot compare to
  strategy Sharpe`. Gate-verified live through the CLI.
- **The M06/M07 item on the benchmark overlap count — DISCHARGED.**
  `MetricsSummary.benchmark_overlap_periods` is recorded and `validate_basic` flags a short
  overlap against the new `benchmark_overlap_min_fraction` (0.9) in `configs/validation.yaml`.
  Note for M06: this is M05's first self-read threshold and is deliberately OUTSIDE the
  `thresholds` block reserved for M06; keep the two separate.
- **The M06/M07 item on Sortino's stated convention — DISCHARGED.** The docstring now states
  target 0, full-sample N at ddof=0, why full-sample N is the right lower-partial-moment
  choice, and the ddof mismatch against `sharpe_ratio`. The formula is unchanged. **The
  reporting half stands:** whoever prints Sortino beside Sharpe must still say the two
  denominators are not on the same footing.
- **The M06 item on `no_cliff_score` being a roughness rather than cliff-edge detector
  STANDS UNCHANGED.** The formula is the packet's own and was not altered. What changed is
  that `neighbourhood_size` and `neighbourhood_truncated` are now recorded and serialised, so
  M06 can at least tell an edge-truncated score from an interior one, and an even-length axis
  with no explicit `base_point` now raises rather than silently defaulting to an edge.
  Gate-verified: the cycle-1 five-point probe reproduces −0.6000 / +0.8500 / +0.9710 with
  `truncated=True/False/True`. M06 must still apply `min_net_sharpe` alongside
  `min_no_cliff_score` and must never quote the no-cliff score as evidence of quality.
- **The M06 item on reconciling sensitivity trial ids with `Strategy.strategy_id` STANDS.**
  The two id schemes remain deliberately independent, so M06 will still count the base grid
  point twice under two different ids. Over-counting N is conservative for DSR; M06 should
  state which it is doing.
- **The M06/M07 items on walk-forward STAND UNCHANGED** — no purge/embargo between adjacent
  train/test blocks (gate re-confirmed no self-influence against the current tree with the
  planted fixture); the blend-of-net versus netted-book Sharpe RANKING is still untested; and
  a NaN training Sharpe on the FIRST grid point still locks in that weight for the step.
  `walk_forward.py` was not touched by iteration 2.
- **The M09 canary item STANDS UNCHANGED.**

### New carried item from M05 cycle 2

- **→ M06 / M07 (defensive, low severity):** `rolling._rebased_subperiod_equity` computes
  `net_equity.index.get_loc(first_return_date) - 1`. A `net_equity` lacking the synthetic
  leading 1.0 makes that index −1, the slice wraps, and the row degrades silently — the gate
  measured `Growth=1.000000`, `CAGR=nan`, `Max Drawdown=0.000000` against a true growth of
  3.163726. Unreachable in-product (the only caller passes `result.net_equity`, which
  `engine.py:_equity_with_start` always prepends and `BacktestResult.load` round-trips), the
  requirement is documented in the helper's docstring, and the degraded output is
  conspicuously degenerate rather than plausibly wrong. A one-line guard raising when
  `first_pos == 0` would close it; worth doing if M06 or M07 adds a second caller.

## From M06 verdict (plans/state/M06/VERDICT.md) — REJECT, cycle 1

M06 was REJECTED at cycle 1. The closed-form statistics (PSR, DSR's `SR*` with the
Euler-Mascheroni term and both `Φ⁻¹` arguments, MinTRL, the purged-split construction,
White's and Hansen's recentring, the stationary bootstrap's `1/L` parameter, the
Corwin-Schultz port) were all re-derived independently at the gate and match to 0.0
absolute — none of them is at issue. Six blocking findings, all in the plumbing between
those formulas and the verdict. Full text and reproductions in VERDICT.md.

### Status of the items M06 was carrying

- **M04 item 1 (dirty-tree flag) — registry half CLOSED, report half NOT CLOSED.** The
  three-source `dirty`/`dirty_source` recording is implemented and tested, but
  `grep -n "dirty" src/quantlab/validation/report_card.py src/quantlab/cli.py` returns
  nothing: `ReportCard` has no provenance section and no `quantlab_git_sha`/`dirty`/
  `dirty_source` field. `registry.py`'s docstring asserts "`report_card.py` surfaces it in
  the provenance section", which is false. VERDICT.md finding 6. **Binding on M06 cycle 2.**
- **M04 item 2 (extreme counts beside PSR/DSR) — PARTIALLY CLOSED.** The caveat, with the
  long/short direction, is appended to the DSR (`report_card.py:449`) and MinTRL
  (`report_card.py:510`) gate reasons but NOT to the PSR gate's, though PSR consumes the
  same truncated skew/kurt. One line. VERDICT.md finding 11.
- **M04 item 3 (combined "untrusted fraction" line) — PARTIALLY CLOSED.** The combined
  sentence is produced by `validate_basic` and reaches `report_card.json` via
  `basic.flags[0]`, but `_report_card_markdown` (`cli.py:249-266`) renders only the gate
  table and `known_caveats`, so the one line telling a reader how much of the book is
  unmeasurable is absent from the human-readable report card. VERDICT.md finding 8.
- **M05 item 1 (three-part registry key; state the base-point counting) — CLOSED as to the
  key and the disclosure, but the STATED DIRECTION IS WRONG.** See the new item below.
- **M05 item 2 (never quote `no_cliff_score` alone) — PARTIALLY CLOSED.** `min_net_sharpe`
  is correctly gated alongside it and both must pass. But `nan_points`,
  `neighbourhood_size` and `neighbourhood_truncated` appear nowhere in `report_card.py`, so
  an edge-truncated or NaN-contaminated score is quoted with the same confidence as an
  interior one. VERDICT.md finding 11.
- **M05 item 3 (why walk-forward needs no embargo and CV does) — CLOSED in text**
  (`_PURGE_VS_WALK_FORWARD_NOTE`, unconditionally in `known_caveats`, and correct as
  reasoning). Note that it now describes machinery that does not act — see the new
  purged-CV item below.
- **M05 item 4 (blend ranking agreement) — CLOSED as a disclosure**
  (`_WALK_FORWARD_RANKING_NOTE`, added whenever a walk-forward is supplied). Vacuous in
  practice today because `validate --full` never supplies one.
- **M05 item 5 (no chosen walk-forward step had a NaN training Sharpe) — NOT VERIFIABLE,
  correctly disclosed** (`_WALK_FORWARD_NAN_TIEBREAK_NOTE`). Accepted as an open item;
  `WalkForwardResult` does not retain per-step training Sharpes. **→ M07:** if the
  walk-forward is ever quoted in a report, retain the per-step training Sharpe so this can
  be asserted rather than disclaimed.
- **M05 item 6 (overlap count / "no usable benchmark") — CLOSED.** A NaN benchmark Sharpe
  is an explicit hard-gate failure with its own reason string.
- **M05 item 7 (`max_drawdown_floor` on full-sample only; label the rolling convention) —
  CLOSED.** The drawdown gate reads `MetricsSummary.net_max_drawdown` and says so; the
  negative-rolling-fraction gate's reason states the frozen first-return-blind convention
  explicitly.
- **M05 item 8 (Sortino/Sharpe denominator conventions stated where printed) — NOT
  CLOSED.** Neither the report card nor `_validate_one_liner` (`cli.py:277-280`, which
  prints Sharpe and Sortino side by side) states the ddof=1 / ddof=0 mismatch. VERDICT.md
  finding 8. **Binding on M06 cycle 2 and carried to M07.**

### New carried items

- **→ M06 cycle 2 (blocking):** recording more trials RAISES the DSR. `var_sr_trials` is
  estimated from the same set `n_trials` counts, so a trial whose Sharpe sits near the mean
  raises `N` and shrinks `V̂` at once, and `SR* ∝ √V̂` shrinks faster than the `Φ⁻¹` term
  grows. Gate-measured end-to-end through `build_report_card` with the shipped
  `min_dsr: 0.95`: nine dispersed siblings plus a headline run give DSR 0.9024 (gate FAIL);
  recording 15 further backtests that differ from the headline ONLY in `initial_capital`
  (identical `net_returns`, new config hash, new key) gives N=25 and DSR 0.9647 (gate
  PASS). At 40 such reruns, 0.9872. Degenerate end: when every trial shares one Sharpe,
  `var_sr_trials == 0` and `deflated_sharpe.py:105-106` sets `SR* = 0` at ANY N — DSR
  measured 0.999641 identically at N = 2, 10, 100 and 100000. **The
  "over-counting N is conservative for DSR" claim in `registry.py`'s docstring and in
  `_REGISTRY_BASE_POINT_NOTE` is false as implemented and is currently printed to the
  reader as reassurance — it must be removed, not reworded.** This SUPERSEDES the M05
  carried item's "over-counting N is conservative; M06 should state which it is doing":
  stating it is not enough.
- **→ M06 cycle 2 (blocking):** `build_trial_matrix` labels columns by `key[0]`
  (`strategy_id`) alone, so trials differing only in the other two key slots collapse into
  one column. Gate-measured: 4 distinct registry keys with 4 stored series → K=2; two
  records sharing a `strategy_id` → K=1, and the `len(records) < 2` guard runs before the
  collapse so it does not fire. A Reality Check whose max is over one trial applies no
  multiple-testing correction, yet `reality_check_pvalue` is a HARD gate and the measured
  p=0.005 passes it.
- **→ M06 cycle 2 (blocking):** the RC/SPA benchmark is ZERO whenever `--benchmark` is not
  passed, while `net_sharpe_vs_benchmark` and MinTRL fall back to
  `result.benchmark_returns`. One card can test "beats SPY" on one gate and "makes money at
  all" on another, with nothing saying which. Gate-measured on the same six trials with an
  embedded SPY-like series: White RC p = 0.000 against zero, p = 0.272 against the embedded
  benchmark, with the hard bar at 0.10 — the same data passes or fails purely on a CLI
  flag. The benchmark choice must come from `configs/validation.yaml` and be printed.
- **→ M06 cycle 2 (blocking) and → M07/M08 (design, ESCALATED TO ALEX):** `cv_sharpe`
  discards the training positions (`purged_cv.py:123`), so the purge and the embargo cannot
  change its output. Gate-measured on one 144-month series: mean OOF Sharpe is
  0.7817692617 identically under `embargo=1`, `embargo=40`, `label_horizon=24`, and a
  training set containing every row including the test fold. The number is a
  contiguous-sub-period consistency statistic on a strategy already fitted on the whole
  sample, not out-of-sample evidence, and the gate name and reason string both claim
  otherwise. In-loop remedy is disclosure (rename or restate, plus a `known_caveats` entry
  and a test pinning the invariance). The design question — whether a genuine purged CV
  that refits per fold belongs in a later milestone — is Alex's call, not another loop
  iteration; the packet's own `cv_sharpe(returns, splits)` signature cannot express one.
- **→ M06 cycle 2 (blocking):** `ELIGIBLE_FOR_PAPER` is unreachable through
  `quantlab validate --full`. `record_sensitivity` and `seed_historical_blend_trials` have
  no caller outside `tests/`, so the packet's "records every sensitivity grid point" and
  "the Phase 3 five-weight sweep is pre-loaded" are unwired; `--full` passes neither
  `sensitivity=` nor `walk_forward=`. Gate-measured through the real CLI on a fixture with
  annualised Sharpe ≈ 2.0 and PSR = 1.0: verdict REJECTED, N=1, DSR NaN, rc/spa None —
  two hard gates fail on every first run, and the verdict thereafter depends on how many
  unrelated backtests share `reports_dir`.
  `tests/test_cli_validate.py:106` asserts only that the verdict is one of the three, which
  is why the suite is green. Direction is safe (over-conservative), but the milestone does
  not deliver a working decision function.
- **→ M06 cycle 2 / M07:** RC and SPA are over-sized at the shipped `block_len: 6.0`. 600
  simulations on i.i.d. data: size at the 0.10 bar is 0.123 (RC) / 0.128 (SPA) against a
  nominal 0.100, MC se 0.012; at `block_len=1` it is 0.092 / 0.105 with KS p = 0.33,
  confirming the statistic itself is right and the block length is the cause. At the
  suite's OWN test settings (T=40, K=4, `block_len=3.0`) 600 sims give KS p = 0.0070,
  below the suite's own `ks_p > 0.01` bar — the in-tree calibration test lacks the power to
  see what it certifies. Separately, `p_value = mean(boot >= obs)` can return exactly 0.0,
  which no continuous null admits; use `(1 + count) / (B + 1)`.
- **→ M07 (reporting):** `_report_card_markdown` renders only the gate table and
  `known_caveats`. Missing and needed by a referee: `N` as a NUMBER (the DSR reason
  contains the literal letter "N", `report_card.py:444`); the realised RC/SPA `K` and
  `n_periods`; a distinct reason when DSR is NaN because the registry was too thin, which
  today is indistinguishable from a DSR that failed; the coverage/selection "untrusted
  fraction" sentence; the Sharpe/Sortino ddof conventions; capacity's spread percentiles,
  which are computed and serialised but never shown.
- **→ M06 cycle 2 / M09 (thresholds, for Alex):** "intended capital" is
  `provenance["backtest_config"]["initial_capital"]` (`report_card.py:638`), whose default
  is $1,000,000 (`backtest/config.py:38`), so `capacity_min_multiple_of_intended_capital:
  100.0` is a $100M floor on the MINIMUM of the four ceilings. The old repo's own real-data
  range was $95M–$335M at an assumed 50-name book, so the low end fails; a 30-name book at
  ADV p10 reads $38M at 5% participation. This soft gate will almost certainly bind on real
  data and cap every strategy at RESEARCH_ONLY. Intended capital should be its own key in
  `configs/validation.yaml`, set deliberately — inheriting a backtest notional that means
  something else can fail in either direction (Alex's real account is retail-sized, which
  would make the gate trivially passable).
- **→ M06 cycle 2 / M07:** `build_trial_matrix` intersects all trials' date indices with no
  floor. Two 120-period trials overlapping by 60 produced a (60, 2) matrix — half the
  headline strategy's own history dropped from the test that gates its rejection, with no
  flag. A 3-period overlap would still yield a p-value the hard gate acts on. Add a
  minimum-common-periods threshold and report the retained fraction.
- **→ M07 (low severity, informational):** two gates are close to vacuous or to a coin
  flip on a 12-year monthly book and should be read as such. `min_psr: 0.95` binds only
  below an annualised Sharpe of about 0.47 (PSR = 0.939 at 0.45, 0.957 at 0.50, 0.9996 at
  1.00, and 1.0 at 2.0); and `mc_max_prob_drawdown_worse_than_observed: 0.5` sits at the
  approximate centre of its own statistic's null, so it fails roughly whenever the realised
  drawdown was milder than typical for the return distribution. Both are soft gates, so the
  cost is a cap at RESEARCH_ONLY, but neither should be quoted as evidence of quality.

### Adjustments to "From M06 verdict" above (M06 cycle 2, plans/state/M06/VERDICT.2.md)

M06 was REJECTED again at cycle 2, but far more narrowly. Five of the six cycle-1 blockers
are fully closed and were re-verified against the iteration-3 tree by re-running the
cycle-1 reproductions, not by re-reading the handoff. The items above are amended as
follows; DISCHARGED means no later milestone need act.

- **Cycle-1 finding 2 (RC under-counts trials) — DISCHARGED.** `_column_label` joins the
  full three-part key. Gate-verified: four distinct keys with four stored series, three
  sharing one `strategy_id`, now give matrix K=4 (was 2); two records sharing a
  `strategy_id` give K=2 (was 1, i.e. a Reality Check with no multiple-testing correction
  at all). The `< 2` guard now runs on `matrix.shape[1]`.
- **Cycle-1 finding 3 (RC/SPA benchmark silently zero) — DISCHARGED.**
  `reality_check.benchmark` is a real config key defaulting to `embedded`; the resolved
  source is printed in both gate reasons and in provenance. On the six-trial fixture that
  gave p=0.000 vs p=0.272 at cycle 1, the card now reports p=0.2687 against the embedded
  benchmark — the same series every other gate uses.
- **Cycle-1 finding 4 (purged CV inert and misnamed) — DISCHARGED as disclosure.** Renamed
  `subperiod_oof_sharpe`; the gate reason and a `known_caveats` entry both state that no
  model is refit per fold, that purge/embargo cannot change the value, and that it is NOT a
  purged cross-validation. Gate-reconfirmed invariant (0.7817692617 under embargo=1,
  embargo=40, label_horizon=24, and a fully-leaking training set). `purged_kfold_splits` is
  kept, correct, and reserved for a future fitted strategy. **The gate ACCEPTS the
  orchestrator's decision (a)**: no fake CV ships, and the genuine refit-per-fold CV over
  the sensitivity grid is carried post-v1. That reasoning is sound and is not escalated.
- **Cycle-1 finding 5 (ELIGIBLE_FOR_PAPER unreachable via the CLI) — DISCHARGED.**
  `_make_sensitivity_runner` is a real engine-backed factory; `--full` seeds historical
  trials, runs and records the sensitivity grid, and runs the walk-forward for blend
  families. The CLI test now pins `verdict == "ELIGIBLE_FOR_PAPER"` with zero failing gates
  against the REAL `configs/validation.yaml`, and a companion test pins REJECTED. The
  cycle-1 tautological assertion is gone.
- **Cycle-1 finding 6 (dirty flag never reached the report card) — DISCHARGED.**
  `ReportCard.provenance` carries strategy_id, semantics version, git sha, dirty,
  dirty_source, n_trials, n_trials_raw, dirty_trial_count, RC trial count K, RC/SPA
  benchmark source and headline retained fraction, all rendered in report_card.md, with a
  caveat when any counted trial came from a dirty tree. Gate-verified live
  (`dirty=True`, `dirty_source='provenance'`, `dirty_trial_count=2`).
- **Cycle-1 item 8 (markdown completeness) — LARGELY DISCHARGED.** N prints as a number,
  K prints on both RC and SPA gates, the coverage/selection "untrusted fraction" sentence
  is in Provenance, and a Headline metrics section prints Sharpe beside Sortino with the
  ddof convention stated beside them. **This also closes the M05 carried item 8** (Sortino/
  Sharpe conventions stated where printed). Capacity's spread percentiles remain JSON-only
  — fine, and now M07's to render.
- **Cycle-1 item 9 (intended capital) — DISCHARGED as to mechanism.** `intended_capital_usd`
  is its own config key (default 1000), no longer the backtest notional, and the gate reason
  states the resolved dollar figure. See the new item below for the half still open.
- **Cycle-1 item 10 (silent intersection truncation) — DISCHARGED, and the motivating case
  now works.** The gate's own two-same-length-offset-windows case, measured at cycle 1 as a
  silent (60, 2) truncation, now excludes the offset trial with a named reason while the
  aligned majority keeps its FULL 120 periods (matrix (120, 3), retained fractions
  offset 0.5 / majority 1.0 each). The cost of this fix is the new blocker below.
- **Cycle-1 item 11 (half-wired carried disclosures) — DISCHARGED.** The extreme-return
  caveat is now on the PSR gate as well as DSR/MinTRL, and `neighbourhood_size`/
  `neighbourhood_truncated`/`nan_points` appear in both the `no_cliff_score` and
  `min_net_sharpe` gate reasons. **This closes the remaining halves of the M04 carried item
  2 and the M05 carried item 2.**
- **The false "over-counting N is conservative for DSR" claim — REMOVED.** The base-point
  `known_caveats` note now states that over-counting is NOT generally conservative once
  `var_sr_trials` is estimated from the same trial set, and justifies the disclosure by the
  effect's small size rather than by a guaranteed direction. Correct as rewritten.
- **Cycle-1 finding 1 (DSR rises with more trials) — PARTIALLY CLOSED, residual carried
  below.** The return-series hash dedup fully neutralises the exact case the gate
  demonstrated (byte-identical cosmetic reruns: DSR now flat at 0.9024 through 40 reruns,
  N stays 10 distinct while the raw key count reaches 50), and the `1/(n_periods-1)`
  variance floor (a correct Lo 2002 small-sample null variance, on the right per-period
  footing) bounds the damage and restores monotonicity once it binds. Replicating the whole
  sensitivity grid — the workflow `--full` now produces automatically — moves DSR in the
  CORRECT direction (0.9024 at N=10 down to 0.4229 at N=73 across 8 cost levels).
- **Cycle-1 item 7 (RC/SPA over-sizing) — PARTIALLY CLOSED, carried.** `(1+count)/(B+1)` is
  in and works (minimum attainable p is now 0.00498 = 1/201, never exactly 0), and it shaved
  the over-sizing: 600 sims at the shipped `block_len=6.0` now give size 0.117 (RC) / 0.118
  (SPA) at the 0.10 bar, against 0.123/0.128 before; the `block_len=1` control reads
  0.085/0.093 with KS p=0.40, confirming the statistic is sound and the block length is the
  whole story. The developer explicitly declined to raise the in-tree calibration test's
  simulation count and said so rather than adjusting it silently — the right call, and the
  item stays carried. At the test's own settings 600 sims put RC's KS p at 0.0121, barely
  clearing its own 0.01 bar, and SPA's at 0.0016: **the test still cannot measure what it
  certifies.**

### New carried items from M06 cycle 2

- **→ M06 cycle 3 (BLOCKING):** the headline strategy can be excluded from its own Reality
  Check. `_resolve_overlap` treats every trial as an equally disposable removal candidate,
  including the headline. When the headline's window is offset from the majority of its
  family's recorded trials, it is dropped and the RC/SPA run over the survivors —
  `reality_check_pvalue`, a HARD gate, then answers about strategies that are not the one
  being validated. Gate-measured in the PERMISSIVE direction: three strong aligned trials on
  2014-2023 plus a worthless headline (per-period Sharpe ≈ 0) on an offset 2019-2028 window
  gives `headline_retained_fraction=0.5`, K=3, best_trial=`momentum-maj1`, p=0.0050, RC HARD
  GATE **PASS**, SPA soft gate PASS, with the headline absent from the matrix and the gate
  reason saying only "over K=3 realised trials". Remedy: pin the headline as never-removable
  in `_resolve_overlap`; if it cannot be retained above the floor, the Reality Check must
  FAIL with that named cause rather than run without it; assert in `report_card.py` that a
  non-None `rc` always has the headline label as a column, with a planted-case test.
- **→ M06 cycle 3 (BLOCKING, same fix):** when `build_trial_matrix` raises, the tuple unpack
  at `report_card.py:485` never runs, so `rc_excluded` and `retained_fractions` are silently
  discarded — `headline_retained_fraction` reads `None`, no exclusion caveat is emitted, and
  the RC gate reason claims "fewer than 2 registered trials with a stored return series"
  when in fact four trials each had one and the overlap resolver deadlocked. Gate-measured.
  Capture the exclusions on the exception path and give the `rc is None` branch a reason that
  distinguishes "too few trials recorded" from "excluded by the overlap floor" from "no
  common dates".
- **→ M06 cycle 3 (non-blocking) and M07:** DSR is still not monotone in N in the
  above-floor regime, and nothing in the report says so. Re-running only the HEADLINE under
  successive 1bp cost changes (a real, deterministic shift, not jitter) flips the `min_dsr`
  hard gate: DSR 0.9024 FAIL at 1 run, 0.9356 FAIL at 6, **0.9537 PASS at 10**, peaking
  0.9796 at 25 before the floor (0.006993 = 1/143) binds and the curve turns back down.
  Bounded, and inherent to estimating Bailey & López de Prado's `V[SR]` from recorded
  trials, so not blocking — but the report card must state that DSR is not monotone in N
  above the floor, and the regression test must cover the near-duplicate path, not only the
  byte-identical one it currently pins.
- **→ M06 cycle 3 (non-blocking):** the orchestrator's own decision (d) is half-implemented.
  `intended_capital_usd: 1000` landed and the gate reason states the resolved figure, but the
  required "the capacity gate is trivially passable at a retail stake" sentence exists only
  as a YAML comment — grepping `trivially` and `retail` across `report_card.py`, `cli.py`
  and `configs/validation.yaml` finds nothing else. A reader sees the capacity gate passing
  at 75000x against a 100x bar with nothing saying the bar is vacuous at this stake. Emit the
  sentence whenever the multiple clears the bar by more than an order of magnitude.
- **→ M07 (cosmetic, but this is the deliverable until M07 lands):**
  `_report_card_markdown` uses `{gate.value!r}`, so the rendered table shows
  `np.float64(1.0)` in the `no_cliff_score` row, and Calmar/Sortino render as bare `nan` in
  the Headline metrics section.
- **→ M07 (informational, unchanged from cycle 1):** `min_psr: 0.95` binds only below an
  annualised Sharpe of about 0.47 on a 12-year monthly book, and
  `mc_max_prob_drawdown_worse_than_observed: 0.5` sits at the approximate centre of its own
  statistic's null. Both are soft gates; neither is evidence of quality.

### M06 gate cycle 3 — ACCEPT (plans/state/M06/VERDICT.3.md)

M06 is **ACCEPTED**. Dispositions below supersede the cycle-2 block where they conflict.
Verified by re-running the cycle-2 reproductions unchanged against the iteration-4 tree,
not by re-reading the handoff. Suite 533 tests green, ~25 s, ruff clean; the gate mutated
no source, test or config file.

- **Cycle-2 blocker A (headline excluded from its own Reality Check) — CLOSED, and the
  guard is load-bearing rather than assert-only.** The planted case — three strong aligned
  trials on 2014-2023 plus a worthless headline on an offset 2019-2028 window, which at
  cycle 2 gave a PASSING RC hard gate at p=0.0050 for a strategy absent from its own matrix
  — now yields `rc=None`, the RC gate FAILING by name ("headline trial excluded by overlap
  floor (retained_fraction=50%) … refuse to run on its sibling trials alone"), SPA failing,
  `headline_retained_fraction=0.5`, the headline-cause caveat present, verdict REJECTED.
  Brute-forced the invariant over 200 layouts (headline offsets {0,24,60,96,120} months ×
  headline lengths {24,60,120,180} × five sibling configurations × both benchmark modes):
  16 layouts ran the Reality Check, 184 refused, **0 violations** — every non-None `rc` had
  the headline as a matrix column, checked by independently rebuilding the matrix with the
  protection disabled. The headline-has-the-shortest-window case (24 months inside three
  120-month siblings) correctly removes the siblings, never the headline, and refuses with
  "found 1 after alignment/exclusion". Re-ran the planted case under `python -O`, where
  `report_card.py:512`'s assert is stripped: still `rc=None` and a failing gate, because
  `reality_check.py:309` raises a real `TrialMatrixError`. Two layers, the outer one
  load-bearing.
- **Cycle-2 blocker A item 3 (exclusions lost on raise; one generic reason) — CLOSED.**
  `TrialMatrixError` carries `reason_kind`, `excluded` and `retained_fractions` from every
  raise site. All three causes are distinguishable in the RENDERED `report_card.md` gate
  table, checked there rather than on the exception object: "fewer than 2 registered trials
  in this family have a stored return series" / "headline trial excluded by overlap floor
  (retained_fraction=50%) …" / "no common dates across trials in family 'momentum'". The
  fourth shape (exclusions left fewer than 2 survivors) renders as "found 1 after
  alignment/exclusion (registry held 4 records with a series)", also distinguishable. The
  cycle-2 case that reported the false "fewer than 2 registered trials" when four trials
  each had a series now names the headline cause and preserves all four exclusion
  sentences in `known_caveats`.
- **Cycle-2 item B (DSR non-monotonicity undisclosed) — CLOSED as disclosure.** The DSR
  gate reason carries "DSR is not monotone in N above the variance floor; near-duplicate
  reruns of one grid point can move it", confirmed in the rendered markdown of the shipped
  ELIGIBLE_FOR_PAPER CLI path, and appended only when DSR is actually computed. The new
  regression pins both halves (movement up, then bounded and turning back down where the
  `1/(n_periods-1)` floor binds) on a small fast fixture rather than the gate's literal
  144-period numbers — the right trade for suite time, same two properties pinned.
- **Cycle-2 item C (capacity trivial-pass sentence) — CLOSED.** Emitted above 10x the bar
  and present in the rendered report: "NOTE: the capacity gate is trivially passable at
  this stake (75000x against a 100x bar) - this is not evidence of edge, only that the
  resolved intended capital is small relative to the instrument's liquidity." This
  discharges the outstanding half of orchestrator decision (d).
- **Cycle-2 item D (calibration test power) — PARTIALLY CLOSED, residual carried below.**
  `test_white_rc_size_at_shipped_block_length_is_bounded` measures actual size at the gate's
  own 0.10 bar at the shipped `block_len=6.0` over 300 sims, and the pre-existing uniformity
  test now documents inline that it runs at `block_len=3.0` and is a construction sanity
  check, not a calibration measurement. Honest framing, accepted as scoped.

### Carried items from M06 cycle 3

- **→ M07 (reporting):** `reality_check.py`'s own module docstring says "the gate REASON
  should state the measured over-sizing rather than imply nominal calibration", and it does
  not. Grepping `report_card.py` for any mention of the measured size finds nothing: the RC
  gate reason still reads "White Reality Check p=… against the 0.10 bar" with no hint that
  the 0.10 bar is nominal rather than achieved (measured ~0.117 at the shipped
  `block_len=6.0` over 600 sims; the `block_len=1.0` control reads 0.085 with KS p=0.40,
  confirming the statistic is sound and the block length is the whole story). Put the
  measured size in the RC and SPA gate reasons.
- **→ M07 (testing, low priority):** the new size-bound test's band is 0.04-0.28 around a
  measured ~0.12. At 300 sims the standard error is about 0.019, so the band sits ~4 SE
  below and ~8 SE above: it will not flake and it catches a gross regression, but it cannot
  distinguish 0.12 from 0.25 nor notice the over-sizing disappearing. Tighten it if M07 ever
  needs the Reality Check's size to be a reported number rather than a documented one.
- **→ M07 (cosmetic, deliberately out of cycle-3 scope):** `_report_card_markdown` uses
  `{gate.value!r}`, so the rendered gate table shows `np.float64(1.0)` in the
  `no_cliff_score` row and bare `nan` for Calmar and Sortino in the Headline metrics
  section. M07 replaces this renderer anyway.
- **→ M09 (operational, low severity):** `build_trial_matrix` calls
  `registry.load_series` on every trial with a `series_path`. A missing or corrupt parquet
  sidecar raises `OSError`, not `ValueError`, so it escapes `report_card.py`'s
  `except ValueError` and crashes `validate --full` rather than degrading to a failed RC
  gate. Unreachable while the registry and its sidecars stay co-located; worth a guard when
  M09 starts moving `reports_dir` around.
- **→ M07 / M09 (informational, unchanged and still true):** `min_psr: 0.95` binds only
  below an annualised Sharpe of about 0.47 on a 12-year monthly book, and
  `mc_max_prob_drawdown_worse_than_observed: 0.5` sits at the approximate centre of its own
  statistic's null. Both are soft gates. Neither is evidence of quality and neither should
  be quoted as such.
- **→ M09 (thresholds, for Alex):** `intended_capital_usd: 1000` makes the capacity gate
  vacuous by roughly three orders of magnitude, which the report now says out loud. That is
  the correct disclosure, not a substitute for a decision: before any real-data run, set the
  figure to what will actually be traded, or drop the capacity gate to informational and say
  so in the config.
## From M04b verdict (plans/state/M04b/VERDICT.md) — REJECT

Gate cycle 1 on M04b. Closures and new items below; findings 1–3 are blocking and are
stated in full in the verdict.

### Carried items this milestone DISCHARGES

- **→ M06 dirty-tree sha (from the M04 verdict) — CLOSED.** `provenance.dirty` is present
  and reads `True` on the real run, alongside `quantlab_git_sha`. The M06 trials registry
  can now tell a clean-commit run from a working-tree run.
- **M04b packet item 6 — CLOSED.** `provenance.run_seconds` present (557.19 s on the real
  2012–2026 momentum run).
- **M00 → M04 calendar item — CLOSED and extended.** `core/calendar.py` now pins
  `get_calendar("XNYS", start="1990-01-01", end="2040-12-31")`, so a backtest's calendar no
  longer changes bounds day by day, and `data/pit.py` clamps its window to
  `calendar_first_session()` rather than raising `DateOutOfBounds`. Gate-verified: the
  bounds are literals with no wall-clock input, and the clamp never binds for a 2012–2026
  run (the widest lookback lands in 2010).
- **M02b actions-cache staleness — PRESERVED under the new read-memo, gate-verified.** The
  per-instance memo caches only the disk read; the staleness check still re-evaluates
  `end > fetched_at` on every call with that call's own `end`. Probed directly: warming the
  memo then asking beyond `fetched_at` still raises `StaleActionsCacheError`, and an
  out-of-band sidecar refresh is picked up by the self-heal re-read. The memo can only err
  toward raising an error a re-read would clear — the conservative direction.

### Carried items this milestone does NOT discharge

- **M00/M01 ingestion-quality item — STILL OPEN, and now demonstrably biting.**
  `data/quality.py`'s `QualityGate` has no caller anywhere in `src/` (gate-verified: every
  `quality` hit in `src/` is `quality_flags` or a docstring; only `tests/test_quality.py`
  exercises it). See verdict finding 2 — the first real run ingested price series that are
  merges of unrelated instruments under a reused ticker symbol, and two of them (TIE, BMC)
  entered the portfolio. This is no longer a latent hazard.
- **M01 frozen-transient-failure item — NOT closed; restated in a new form.** The negative
  price cache removes the *permanent* freeze (a TTL, default 30 days) but introduces a
  30-day *masking* path: a single transient empty download overwrites a healthy ticker's
  sidecar, and `has_sufficient_price_cache` checks the `no_data` branch before it looks at
  the parquet, so 14 years of real cached data are served as empty while
  `price_availability_from_cache` reports `has_data=True, masked_end=None`. Gate-reproduced.
  Currently latent: 162 `no_data` sidecars exist in the shared cache and zero sit on a
  non-empty parquet.
- **M09 `refresh_actions_cache()` operational caller — unchanged, still open**, now joined
  by the negative-cache force-clear below.

### New items

- **→ M09 (data refresh), must-fix before any headline number is quoted:** wire
  `data/quality.py`'s `QualityGate` into the price ingestion boundary and extend it with two
  checks it does not have — a zero-volume bar on a date the calendar calls a session (a
  listed US equity essentially never has one), and an adjacent-session close ratio beyond a
  threshold that no split in the gated actions history explains. Then re-scan the shared
  cache and quarantine the affected tickers. Gate-measured contamination: PTV spans 0.01 to
  1,330,000 with 47.7% zero-volume bars against a real ~$33; BMC has a median close of
  13,300 against a real ~$45 and rows running to 2022 for a company taken private in 2013;
  TIE interleaves real ~$16 bars at ~1.7M volume with ~$8,000 bars at ~11,000 volume.
  Controls NVR and AZO, both genuinely high-priced, are clean and continuous with 0%
  zero-volume bars, so this is not a threshold artefact. Root cause is vendor reuse of
  delisted ticker symbols, which concentrates the damage in exactly the delisted names the
  platform's survivorship and delisting machinery exists for.
- **→ M09 (data refresh):** a force-clear for the negative-cache sidecar, alongside the
  `refresh_actions_cache()` wiring. `data/cache.py` documents the need; it is the only way
  a human who knows a `no_data` verdict is wrong can override it before the TTL lapses.
- **→ M06 (trials registry) / M09:** the negative-cache TTL makes a run's data visibility
  wall-clock dependent — the same config run today and in 31 days can see a different set of
  tickers. Neither `retry_after_days` nor any count of tickers suppressed by a live
  `no_data` sidecar appears in provenance. Record both, or two runs of the same YAML are not
  distinguishable after the fact. Note the irony worth preserving: this milestone pinned the
  calendar for exactly this reproducibility reason and then introduced a new today-dependence
  one layer down.
- **→ M05 / M07 (reporting), reinforcing the M04 note:** `quality_flags.unscored_by_date` is
  not usable as a data-quality signal for a selective strategy. Gate-measured on the real
  run: 173 rebalance dates carrying 467–476 names each (median 473) against 30 holdings —
  it is recording "not selected", not "could not be scored", roughly 82,000 entries. The
  M03-verdict guard it implements (surface the value leg's silently dropped unpriceable
  names) is undetectable in that. Either have the strategy declare its unscored names (the
  additive `TargetWeights.unscored` field the M03 verdict contemplated) or rename the flag so
  nothing downstream reads it as a quality measure.
- **→ M09 (reconciliation), scope note:** the 17.84% vs 15.7% reconciliation is M09's. Of
  the mechanisms introduced by M04b, the window clamp cannot have moved net CAGR (it never
  binds for this window) and the benchmark-from-store cannot (it touches only the benchmark
  series, and a full-engine A/B reproduced every series bit-identically). The negative cache
  could have but did not. The contamination in the item above definitely did, by an amount
  nobody can currently state. Separately, `coverage_report.overall_bound` of 22.3% needs no
  explaining: the per-year series declines monotonically from 22.33% (2012) to 0.99% (2026),
  its mean is 11.73% against the old repo's 12.6% no-price gap, and 22.3% is the worst single
  year, which is exactly what the M04 verdict defined the bound to be.

## M04b gate cycle 2 — ACCEPT (plans/state/M04b/VERDICT.2.md)

M04b is **ACCEPTED**. Dispositions below supersede the cycle-1 block above where they
conflict. Each closure was verified by re-running the cycle-1 reproduction unchanged, not by
re-reading the handoff.

### Closures

- **M01 frozen-transient-failure item — NOW CLOSED**, reversing the cycle-1 "NOT closed".
  `has_sufficient_price_cache` consults a real, non-empty parquet before any `no_data`
  sidecar, and `yfinance_prices.py` no longer writes a `no_data` sidecar for a ticker that
  already has a parquet. Both layers gate-verified independently: the cycle-1 repro now
  serves all 3,781 real rows (was 0), and forcing an empty re-fetch on a ticker with a
  parquet leaves the `no_data` flag absent.
- **M00/M01 ingestion-quality item — NOW CLOSED.** `data/quality.py` is wired at the read
  boundary and enforcement is automatic, total and fails closed. Gate-probed offline with any
  download attempt raising: TIE (2,237 parquet rows), EA (6) and PTV (1,602) each serve zero
  rows, while IBM, AAPL and NVR serve 1,131 each. 47 tickers quarantined cache-wide, 42 in
  the run's tracked universe. The contaminated series identified at cycle 1 (TIE, BMC, PTV,
  CBE, MEE, CPWR, MHS, CCE, GR) are all among them.
- **M04b cycle-1 finding 3 (`unscored_by_date`) — CLOSED.** `TargetWeights.unscored` is
  additive and self-reported by the plugins; the engine reads it instead of inferring
  `universe − weights`. Gate-measured on the real run: 8–157 names per rebalance, median 87,
  against 467–476 (median 473) at cycle 1. The spread across dates is itself the evidence it
  now measures something.
- **Detection-vs-enforcement policy — RULED ACCEPTABLE.** The gate's "wire into the ingestion
  boundary" is satisfied by automatic enforcement; detection (`scan_price_cache`,
  `heal_or_flag_new_listings`) staying a disclosed manual pass is the better design, since a
  full-cache scan needs a membership provider and, on the healing path, live network — neither
  belongs inside an offline, deterministic backtest. See the residual item below.

### Gate-verified properties worth keeping on record

- **The membership-reuse detector holds in BOTH failure directions.** Eleven synthetic
  boundary cases all match expectation: a first bar sitting at the cache's own 2010-06-01
  floor is never flagged however old the membership (the IBM/MSFT/JNJ over-flagging fix), a
  genuine new member is never flagged whether its data starts before or shortly after
  joining, the tolerance boundary is exact (399 sessions clean, 400 flagged), and EA/EQR-like
  reuse is flagged. Against the real cache: IBM, MSFT, JNJ, AAPL, XOM, PG, KO, JPM, SPY and
  the genuinely high-priced NVR/AZO/FICO are all clean; the genuine recent listings SNDK and
  AMTM are clean despite late first bars; every confirmed reuse case is quarantined. TIE, BMC
  and PTV were caught by the price-arithmetic detectors rather than the membership one, which
  is the correct division of labour.
- **The round-2 sidecar repair is sound.** 664 parquets, 826 sidecars, zero parquets without
  a sidecar, zero sidecars missing `requested_start`. Only two distinct requested ranges exist
  across the cache and the difference is one day, from the healing re-fetches. This matters
  because a missing `requested_start` silently disables the reuse detector for that ticker.
- **What moved the number.** Nine quarantined names were held in the withdrawn 17.84% run
  across 22 name-rebalances of 5,190 (0.42% of position-periods): HAR 4, FOXA 4, COL 3, FOX 3,
  TIE 2, SCG 2, IR 2, CBE 1, BMC 1. A 0.18pp CAGR reduction is proportionate, and downward is
  the expected direction if contaminated series were manufacturing spurious momentum winners.
- **Coverage bound 28.4% is the honest number and is decomposable.** Per-year falls
  monotonically 28.37% (2012) → 2.2% (2026), mean 14.68%, up from 22.33%/11.73%. It rose
  because 42 genuinely-corrupt names now count as lacking coverage instead of reading as
  covered. Its meaning has WIDENED to cover three distinct causes, and the report keeps them
  separable: `quarantined_tickers` (30 in 2012), `masked_tickers` (0), `masked_start_tickers`,
  plus `provenance.quarantined_count=42` / `masked_start_count=0` and a plain-language
  `known_caveats` entry. `masked_start` affects zero tickers for this window since every gap
  it holds for predates 2012.

### Residual items

- **→ M09 (`quantlab data scan`), must-fix:** record scan COVERAGE, not just verdicts.
  `checked_at` is stamped only on the 47 quarantined tickers, so 779 clean ones carry no scan
  marker and a NEVER-SCANNED cache is indistinguishable from a scanned-and-clean one —
  `provenance.quarantined_count` reads 0 in both cases. Stamp `checked_at` on every ticker the
  scan visits, or write a cache-level scan manifest, and have the engine emit a
  `known_caveats` entry when a run's universe contains tickers no scan has ever covered. This
  is the third time in this project a guard has existed with no way to tell whether it ran.
- **→ M09 (data refresh), carried unchanged:** force-clear CLI for both sidecar kinds
  (`clear_quarantine_meta` exists, no caller), and the `refresh_actions_cache()` operational
  caller.
- **→ M06 / M09, carried unchanged from cycle 1:** `retry_after_days` and the count of
  tickers suppressed by a live `no_data` sidecar are still absent from provenance, so the
  negative-cache TTL's wall-clock dependence is still unrecorded.
- **→ M09, documented under-detection:** the membership heuristic cannot catch a reuse case
  where the new company's data start closely tracks its OWN recent index entry. Conservative
  in direction (under- not over-quarantining), noted in the detector's docstring, and not
  closable by date comparison alone — it needs a second signal, if it is ever worth doing.
- **→ M09 (reconciliation):** the 17.66% vs 15.7% reconciliation remains M09's. The cycle-1
  scope note stands, with the contamination channel now quantified above rather than open-ended.


## From M07 verdict (plans/state/M07/VERDICT.md) — REJECT, cycle 1

M07 was REJECTED at cycle 1. The autoescape design, the plot semantics and the
carried-note coverage in sections 3, 4 and 6 are sound and were verified adversarially
at the gate (hostile ticker through `price_panel_missing_tickers` into the real capacity
gate reason; hostile YAML param and hostile `known_caveats` entry through
`result.provenance`) — none of that is at issue and cycle 2 should not reopen it. The
three blockers are in section 5's walk-forward block plus one unimplemented half of a
carried item. Full text and reproductions in VERDICT.md.

### Closure status of the M07-addressed items

- **Coverage-bound definition, separate-selection-effects note, `known_caveats` verbatim,
  extreme-return direction statement, dirty-tree badge — CLOSED.** All present in section
  3 of all three rendered fixtures; the direction statement fires only on a nonzero count,
  which is correct.
- **Rolling first-return-blind convention (M05 carried) — CLOSED.** Printed beside every
  rolling table and beside the walk-forward comparison table in both templates.
- **`no_cliff_score` never described as quality, shown only beside `min_net_sharpe`, with
  `nan_points`/`neighbourhood_size`/`neighbourhood_truncated` (M05/M06 carried) — CLOSED.**
- **Sharpe (ddof=1) / Sortino (target 0, ddof=0) conventions stated where printed (M05
  item 8, M06 carried) — CLOSED.** In the headline table's Note column beside Sortino.
- **N as a number, N deduplicated vs raw vs dirty, K and common-period count on RC and
  SPA, the distinct DSR-NaN "registry too thin" reason, the untrusted-fraction line,
  capacity spread percentiles, DSR non-monotonicity beside the DSR badge, the two M06
  informational sentences on exactly `probabilistic_sharpe_ratio` and
  `monte_carlo_drawdown` (M06 carried items 1, 3, 7) — CLOSED.**
- **Measured RC/SPA over-sizing in the gate detail (M06 cycle-3 carried) — CLOSED, and
  well done.** Block-length-gated, so it is never misattached to a run at a `block_len`
  the measurement does not cover; the fallback sentence names both block lengths.
- **Number formatting: no numpy repr, no bare `nan`, fixed precision (M06 carried item 6)
  — CLOSED except for infinity** (see the new item below).
- **`missing_forward_prices` never quoted as a second corroborating number (M04/M05
  carried) — DISCHARGED.** Absent from the report entirely.
- **Execution conventions incl. which price the entry is measured at (M04 carried) —
  CLOSED in behaviour, NOT in coverage.** The `next_open` sentence is true of the shipped
  engine (`engine.py:140-153`, `:949-951`) and renders correctly when
  `backtest_config.execution` is present — gate-verified live. But every fixture leaves
  the key unset, so no rendered fixture and no test exercises it. See the new item below.
- **Walk-forward no-embargo explanation, per-step training Sharpes honestly "not
  retained", ranking agreement "not checked" (M05/M06 carried item 2) — the three
  SENTENCES are CLOSED; the chosen-weight sequence half REMAINS OPEN** (blocking finding
  2 below).
- **Capacity trivial-pass statement (M06 carried item 4) — CLOSED. The $95M–$335M
  context half REMAINS OPEN** (blocking finding 3 below).

### New carried items

- **→ M07 cycle 2 (BLOCKING):** the walk-forward comparison table reads
  `WalkForwardResult.to_json()`'s `comparison` with the axes transposed.
  `walk_forward.py:200-206` builds the DataFrame with METRICS as the index and GRID
  POINTS as columns; `to_json` (`walk_forward.py:103`) serialises `orient="index"`,
  yielding `{metric: {grid_point: value}}`; `context.py:466` iterates it as
  `{grid_point: {metric: value}}`. Gate-reproduced on a real 10-step, 2-child,
  5-grid-point `walk_forward_blend`: the rendered table has four rows labelled
  `Annualized Volatility` / `CAGR` / `Max Drawdown` / `Sharpe Ratio` and every cell reads
  `n/a (not available)`, while the real numbers sit in the JSON. Live on the
  `validate --full` blend path (`cli.py:177-187` builds and passes a real
  `WalkForwardResult`). Not caught because `test_report_context.py:338-353`'s
  hand-written `comparison` fixture is in the shape `context.py` assumes rather than the
  shape the producer emits — the test certifies the bug. Remedy: transpose at the
  boundary, rebuild that test fixture from a real `walk_forward_blend(...).to_json()`,
  and add a walk-forward-bearing rendered fixture.
- **→ M07 cycle 2 (BLOCKING):** `context.py:453-464` builds `chosen_rows` (the per-step
  chosen-weight sequence, asserted by `test_report_context.py:362`) and NEITHER template
  renders it — the sequence appears only inside `walk_forward_weights.png`, which in the
  markdown twin is an external sibling file, so it exists as text in neither format and
  is not diffable. M06 carried item 2 requires it printed. Same root cause hits
  `_sensitivity_section`'s `surface_rows`/`base_point`/`param_axes`
  (`context.py:433-443`), none of which any template renders: the surface's values, the
  base point's coordinates and which cells are NaN exist only inside the heatmap PNG.
- **→ M07 cycle 2 (BLOCKING):** M06 carried item 4's first half is unimplemented. The old
  repo's own $95M–$335M capacity range is in no template, no context builder and none of
  the three rendered fixtures (only `validation/capacity.py:6`'s docstring). Without it an
  AUM ceiling has no reference scale. Print it from a named constant beside the ceiling
  range, with the 50-name-book assumption stated.
- **→ M07 cycle 2 / M09 (reporting):** the trust panel prints "Rebalance dates with
  unscored names" as a bare count with no caveat, but the M06 cycle-3 verdict measured
  that this flag records "not selected", not "could not be scored" — 173 rebalance dates
  carrying 467–476 names each against 30 holdings on the real run. On a real report that
  row reads `173` and a referee reads it as 173 dates with unscoreable names. The
  upstream fix (a `TargetWeights.unscored` field, or renaming the flag) is not M07's, but
  the caveat beside the number is.
- **→ M07 cycle 2 (low severity):** `_num` (`context.py:122-124`) guards NaN but passes
  infinity through `f"{v:.2f}"`, so the REJECTED fixture prints "min track-record length
  inf" and "needs >= inf observations for significance". Render infinity as
  `n/a (<reason>)` the way NaN is rendered.
- **→ M07 cycle 2 (coverage, not behaviour):** acceptance criterion 3 does not cover
  section 6. Every `_report_fixtures.py` verdict leaves `backtest_config.execution` unset,
  so `test_render.py:100-106` asserts only the "not recorded" fallback and the M04 carried
  entry-price sentence appears in no fixture and no rendering test. Populate one fixture's
  `backtest_config` fully.
- **→ M07 cycle 2 / M09 (honesty, highest leverage of the non-blocking items):** the
  report has no legend for what a verdict or a soft gate means. A green
  `ELIGIBLE_FOR_PAPER` badge sits above "net CAGR 43.10%, Sharpe 5.15, max drawdown
  0.00%" with nothing saying the verdict means "cleared the platform's gates for paper
  trading", not "has an edge", and nothing saying a soft-gate failure caps the verdict
  rather than rejecting it. The capacity gate already models the right behaviour with its
  own "this is not evidence of edge" sentence; the verdict badge deserves the same.
- **→ M07 cycle 2 / M08 (reporting robustness):** `render.py:152-220` wraps every plot in
  a bare `except Exception` and silently omits the section, so a crashed plot and a
  legitimately absent one are indistinguishable to the reader. Print "plot unavailable:
  <reason>" instead of closing over the failure.
- **→ M07 cycle 2 (low severity):** `render.py:126`'s basic-only fallback sets
  `untrusted_fraction_line = flags[0] if flags else ""` — whatever flag happens to be
  first is printed under the untrusted-fraction slot in the trust panel. Select by content
  or leave it empty.
- **→ M07 cycle 2 / M09 (low severity):** `cli.report` never passes `config`
  (`cli.py:501`), so the Monte Carlo fan's seed is hardcoded to `1` in
  `render.py:78-85`. It matches `configs/validation.yaml:114` today, so the fan currently
  IS the same draw as the quoted percentiles — but changing that seed silently decouples
  the picture from the numbers above it with nothing on the page saying so. Pass the
  loaded validation config through, or caption the fan.
- **→ M07 cycle 2 (cosmetic):** the coverage-bound/selection-effects sentence prints twice
  (trust panel and again under Robustness → Flags); the markdown twin carries HTML
  entities (`&middot;`, 8 per report) rather than plain separators; `Sortino n/a (not
  available)` gives a generic reason where "no losing periods" is the real one; the
  rolling table dumps every window row (50 in the fixture, ~130 on a 12-year book) with no
  truncation.
- **→ M08/M09 (documentation, one sentence):** `render.py:70-75` correctly reasons that
  the markdown twin has no HTML-injection surface. Gate-confirmed: a hostile ticker
  survives into `report.md` raw and into `report.html` escaped. Worth stating in the
  module docstring that the markdown is safe only as TEXT — piped through a markdown
  renderer that passes inline HTML, the payload becomes live. The HTML twin is the safe
  artifact.


### M07 gate cycle 2 — ACCEPT (plans/state/M07/VERDICT.2.md)

M07 is **ACCEPTED**. Dispositions below supersede the cycle-1 block above wherever they
conflict. Verified by re-running the cycle-1 reproductions unchanged against the
iteration-3 tree and by building fresh hostile and degenerate cases at the gate, not by
re-reading the handoff. Suite 735 tests green, ~80 s, ruff clean; the gate mutated no
source, test, config or fixture file, and the four fixture checksums are unchanged.
`configs/validation.yaml` is not in the diff — production `b: 200`, `block_len: 6.0`,
`monte_carlo_n_paths: 500` are untouched, so the reduced suite-time figures come from the
test fixture's own small bootstrap, not a production change.

- **Cycle-1 blocker 1 (walk-forward comparison transposed) — CLOSED.** Re-ran the exact
  10-step / 2-child / 5-grid-point reproduction and checked every rendered cell against
  `WalkForwardResult.comparison` as a DataFrame rather than against the JSON, so a
  matching serialiser bug could not hide inside a matching consumer bug: six rows, six
  grid points, zero `n/a`, all four metrics matching to the printed precision in both
  formats. `_transpose_comparison_by_grid_point` re-keys at the consumer boundary, leaving
  the read-only `to_json()` alone. The root cause is properly fixed: the test fixture is
  now generated by a real `walk_forward_blend(...).to_json()`, so the consumer can no
  longer be certified against a shape the producer does not emit.
- **Cycle-1 blocker 2 (chosen-weight sequence / sensitivity surface PNG-only) — CLOSED.**
  All 10 chosen-weight steps render as distinct table rows in both formats, matching the
  DataFrame exactly. The sensitivity surface is a real table with the base point labelled;
  gate-tested on a case the shipped fixtures do not cover (a 2-D 3x2 grid with a planted
  NaN cell and `neighbourhood_truncated=True`) — all six points render and the NaN cell is
  annotated rather than blank. **Escaping survived the rewrite:** the new precomputed
  markdown lines interpolate config-sourced `child_labels` but are plain `str`, not
  `Markup`, and are referenced only by `report.md.j2` (the HTML template builds its own
  `<tr>` loops); the Markup allowlist grew by exactly one static literal
  (`VERDICT_LEGEND`). The cycle-1 hostile-ticker injection through the real
  `price_panel_missing_tickers` -> capacity-gate-reason route was re-run against the new
  tree and still escapes in HTML, still leaves the page well-formed, still raw in the twin.
- **Cycle-1 blocker 3 (old-repo $95M-$335M capacity range) — CLOSED.**
  `OLD_REPO_CAPACITY_RANGE_USD`/`_ASSUMPTION` are constants in `capacity.py`, printed
  beside this run's own ceiling with "For scale only, NOT the output of this run" and the
  50-name-book assumption stated.
- **Unscored-names caveat — CLOSED, better than asked.** It branches on the run's own
  `data_semantics_version` rather than asserting one static meaning, so it tracks the real
  M04b semantics boundary instead of hard-coding the pre-M04b reading.
- **Infinity formatting — CLOSED for everything M07 owns** ("unbounded (n/a)" in the badge
  line and the gate Value column). See the new carried item below for the upstream half.
- **Section-6 coverage gap — CLOSED.** The fourth fixture's fully populated
  `backtest_config` makes the test assert the real `next_open` sentence AND assert the
  "not recorded" fallback is absent — never both, never neither.
- **Silent plot failures — CLOSED.** Gate-verified by monkeypatching `plot_equity_curves`
  to raise: both formats render "plot unavailable: ValueError: ..." and the failure is
  logged.
- **`--config` seed passthrough, untrusted-fraction flag selected by content, verdict/gate
  legend, and all cosmetics (deduped coverage sentence, plain separators, rolling
  truncation, markdown-safety docstring) — CLOSED.** The legend states plainly that hard
  failures cap at REJECTED, soft failures cap at RESEARCH_ONLY, the two informational notes
  never affect the verdict, and "a verdict is not evidence of edge; it states which tests
  the result survived" — the highest-leverage sentence the cycle-1 report was missing, now
  directly under the badge.
- **Markdown twin safe only as plain text — DISCHARGED as documented** in
  `_markdown_environment`'s docstring. Gate-confirmed: a hostile ticker is escaped in HTML
  and raw in the twin, which is correct for a plain-text artifact.

### Items still open after M07 (re-addressed to M09)

- **→ M09 (cosmetic, upstream):** `report_card.py`'s `min_track_record_length` reason prose
  still reads "needs >= inf observations for significance" while the Value column beside it
  now reads "unbounded (n/a)". **Gate ruling: the developer's scoping is correct and this
  is NOT M07's to fix.** `ReportCard` is a read-only input under the packet's "Interfaces to
  honor"; M07 formats every number it owns, and `test_infinity_never_renders_bare`
  documents the boundary explicitly rather than quietly excluding the case. The row looks
  internally inconsistent but both halves convey the same true fact (no sample size attains
  significance at a zero Sharpe). Fix it in `report_card.py`, not by having the reporting
  layer rewrite prose it does not own.
- **→ M09 (cosmetic):** a NaN sensitivity cell renders
  `n/a (NaN (excluded)) (excluded from no_cliff_score)` — nested parentheses and "excluded"
  three times in one cell, because `_num`'s reason and the template's own suffix say the
  same thing. Gate-reproduced on a 2-D grid with a planted NaN point. One-line fix whenever
  `context.py` is next open.
- **→ whoever next touches `validation/walk_forward.py` (unchanged, still correctly
  disclosed):** per-step training Sharpes are not retained on `WalkForwardResult`, so a NaN
  training Sharpe on a CHOSEN step cannot be verified; and the blend-of-net versus
  netted-book Sharpe RANKING is still unchecked. The report prints honest "cannot be
  verified here" and "not checked" lines and fabricates nothing, which is the right
  behaviour until the object retains the figures.
- **→ M08/M09 (operational):** suite wall time has grown 53 s -> ~80 s against the 90 s
  budget as the M07 fixture set reached four rendered verdicts. M08 is about to add to this
  suite and the headroom is thin.
- **→ M09 (fixture realism, informational):** the `walk_forward` fixture's walk-forward
  covers 2008-2020 while its headline result covers 2015-2019, because the walk-forward
  series is synthetic and bolted onto the headline rather than derived from it. A real
  `validate --full` builds both from the same child results, and the report does disclose
  the walk-forward's own step dates, so the window is visible to a reader. No product
  defect — recorded so nobody reads that fixture as a realistic worked example.
## From M08 verdict (plans/state/M08/VERDICT.md) — REJECT, cycle 1

### Closure of the carried M02b/M04 runner items

- **M02b/M04, "the paper/live runner needs an explicit actions-cache refresh policy"
  (lines 109-112, restated as M04 closure item 7) — CLOSED.** `paper/runner.py`'s
  `_generate_targets_with_actions_refresh` catches `StaleActionsCacheError` on the first
  `generate_targets` attempt, force-refreshes every ticker in the strategy's declared
  universe via `refresh_actions_cache`, logs the refreshed list into the journal record
  (`refreshed_actions_tickers`), and retries exactly once. A second failure is journaled
  as a refusal and re-raised — no loop, no deciding on stale data. Verified by reading and
  by the developer's and reviewer's independent reproduction; the one gap code review
  flagged (no regression test for the second-failure path) was fixed before this gate.
- **M02b/M04/M09, "`refresh_actions_cache()` has no operational caller" — PARTIALLY
  CLOSED.** The paper runner is now a real caller, which is what that note asked for in
  the runner's own direction. The M09 half stands unchanged: there is still no
  `quantlab data refresh` command, and still no force-clear for the quarantine or
  negative-cache sidecars (`clear_quarantine_meta` still has no caller).
- **M06, promotion-gate keying on `strategy_id` + `DATA_SEMANTICS_VERSION` — CLOSED.**
  Probed directly at this gate: a `REJECTED` card, a `RESEARCH_ONLY` card, an
  `ELIGIBLE_FOR_PAPER` card carrying a stale semantics version, and a `REJECTED`-plus-stale
  -`ELIGIBLE` pair all raise `PromotionGateError`; only a current-semantics
  `ELIGIBLE_FOR_PAPER` card trades, and a semantics bump invalidates every old card.
  `--force-research` leaves `force_research: true`, a null `promoting_report_card`, and a
  `known_caveats` entry beginning `FORCE-RESEARCH:`.

### Blocking findings — must be fixed in M08 cycle 2, not carried

Full detail in `plans/state/M08/VERDICT.md`. Summarised here only so a later reader of
this file sees why M08 did not pass on cycle 1:

1. Reconciliation baselines on the last NON-refused journal record, so the first ordinary
   dividend or split refuses the run and every run after it, forever. The recovery
   `docs/paper-trading.md:123` prescribes is impossible.
2. The runner's decision context omits the engine's `_FilteringConstituentsProvider` and
   has no counterpart to `max_dropped_fraction` or `abort_on_unscoreable`. Targets are
   byte-identical to the engine's on healthy data and diverge on degraded data.
3. A delisted holding raises an unhandled `ValueError` out of `plan_orders` and writes
   zero journal records, against both the runner's own docstring and CLAUDE.md
   invariant #3.
4. A partial fill can never be topped up, and the replayed duplicate fill is journaled as
   this run's result; resting remainders are never cancelled.
5. Blend strategies lose the M04 per-child context guard — the runner never calls
   `set_context_factory`.

### → M09 items

- **→ M09 (drift check), must-fix before any forward-vs-backtest number is quoted:** the
  paper runner decides as of the previous completed session and submits market orders that
  fill at the next open, roughly one and a half sessions after the backtest's `close`
  execution convention books the same rebalance. Undocumented today. M09 must model this
  lag explicitly or it will report it as strategy drift. Either compare against a
  `next_open`-mode backtest or state the residual as a known, quantified offset.
- **→ M09 (drift check):** the journal has no per-ticker data-asof, and `resolve_asof`'s
  staleness ceiling watches only the benchmark ticker
  (`paper/runner.py:122-137`). A universe name whose overnight sync lagged is decided on a
  stale bar with nothing recorded, and the drift check cannot separate that from a signal
  change. Record, per run, the last bar date actually seen for each traded name.
- **→ M09 (drift dashboard):** `journal_to_frame` omits `promoting_report_card`,
  `known_caveats`, `refreshed_actions_tickers` and `targets`
  (`paper/journal.py:109-125`). They are in the raw JSONL and the docstring says so, so
  this is a convenience gap — but the drift check needs all four, so widen the frame
  rather than re-parsing the file in M09.
- **→ M09 (canaries):** canary (k) pins only `asof == prev_trading_day(today)`
  (`tests/canaries/test_lookahead.py:802-803`). Deleting `resolve_asof`'s data-cache
  ceiling clamp entirely leaves the canary green; only a unit test catches it. Extend the
  canary to the second half the M08 packet specified — `asof` never later than the data's
  last cached bar — so the guard survives a refactor of `runner.py`.
- **→ M09 (canaries), carried unchanged from M04/M05:** a strategy that deliberately does
  `object.__setattr__(ctx, "_accounting", True)` can still reach `prices_for_returns()`.
  Unchanged by M08.


## M08 gate cycle 2 — REJECT (plans/state/M08/VERDICT.2.md)

All five cycle-1 findings are fixed and independently re-verified (see below). The
rejection is for ONE new finding, a regression introduced by the cycle-2 fix itself.

### Cycle-1 items — CLOSED

- **Reconcile bricking — CLOSED.** `reconcile.roll_forward_expected` explains dividends
  and splits between two runs; `accept_broker_state` / `quantlab paper rebaseline` is a
  loud, journaled human escape hatch; a refused run still never becomes the baseline.
  Probed independently: a dividend on a name the prior run sold to zero is correctly not
  credited, and an unbacked cash credit still refuses. The fix explains the ordinary case
  rather than loosening the check.
- **Shared decision context — CLOSED.** `backtest/context.build_decision_context` is the
  only construction site for either `run_backtest` or `run_once`. The gate's own 40-name
  probe now agrees byte-identically in BOTH the healthy case (0.025 each) and the degraded
  case (0.025641 across 39). `tests/parity`, `tests/canaries` and `tests/test_engine.py`
  are 83/83 green after the extraction — the goldens are undisturbed.
- **Delisted holding — CLOSED.** Force-exited with no price needed, `forced_exits`
  journaled, the broker's rejection recorded honestly, exactly one record, no crash.
- **Partial fills — CLOSED.** Converges 247.5 → 433.125 → 572.34375 across three runs at a
  25% fill fraction, cancelling each prior attempt's resting remainder (journaled) and
  planning the residual under a distinct `-aN` client order id.
- **Blend per-child context — CLOSED.** `run_once` calls `set_context_factory` with the
  shared-context closure; an over-reaching child raises and is journaled at
  `stage='targets'`.
- **Canary (k) second half — CLOSED.** Now pins the data-cache ceiling as well; both halves
  were mutation-checked by the developer and the reviewer.
- **`journal_to_frame` width — CLOSED.** Carries `kind`, `promoting_report_card`,
  `known_caveats`, `refreshed_actions_tickers`, `dropped_tickers`, `dropped_fraction`,
  `unscored_tickers`, `forced_exits`, `targets`, `assumed_fill_session`.
- **Paper-vs-backtest fill timing — CLOSED as documented.** `assumed_fill_session` is
  journaled per run and the ~1.5-session lag is documented. The M09 drift check must still
  model it (carried below).

### M02b/M04 actions-cache refresh policy — RE-OPENED

Closed at cycle 1, re-opened here. The cycle-2 shared-filter fix makes the refresh policy
UNREACHABLE for every shipped strategy. `_FilteringConstituentsProvider` converts a
per-ticker `StaleActionsCacheError` into a drop, so staleness can no longer escape
`generate_targets`, which is the only thing that triggers
`_generate_targets_with_actions_refresh`. The filter is active for every shipped
declaration shape (`needs_universe` plus a price lookback or fundamental fields).

Probed at `fetched_at=2023-12-02`, `asof=2023-12-29`: with all 40 universe tickers stale
(the ordinary monthly state, since the cache is fetch-once-forever and paper `asof` always
advances past it) the run raises `BacktestAbortError` and `refresh_actions_cache` is called
zero times; with 1 of 40 stale the run trades but drops that ticker silently and
permanently, again refreshing nothing. The regression test passes because
`tests/test_runner.py`'s `_ActionsProbeStrategy` declares `price_lookback_days=0`, a shape
no shipped strategy uses.

**Remedy is the packet's own wording**, which specifies a PROACTIVE policy — "call
`refresh_actions_cache` for the universe when `fetched_at < asof`, log it"
(`plans/M08-paper-trading.md:46-47`). What shipped is a reactive catch-and-retry, which was
only equivalent while nothing intercepted the exception. Read the sidecar directly
(`backtest/engine.py`'s `_actions_fetched_at` already does this) for the declared universe
AND every held ticker, refresh what is stale, then build the context.

### → M09 items

- **→ M09 (data refresh), unchanged and now more urgent:** there is still no
  `quantlab data refresh` command and still no force-clear for the quarantine or
  negative-cache sidecars (`clear_quarantine_meta` has no caller). Until the re-opened item
  above is fixed, that command is the ONLY way an operator could clear a stale actions
  cache, and it does not exist.
- **→ M09 (drift check), must-fix before any forward-vs-backtest number is quoted:** the
  paper runner decides at the prior completed session's close and fills at the next open,
  roughly 1.5 sessions after the backtest's `close` convention. `assumed_fill_session` is
  journaled; M09 must compare against a `next_open`-mode backtest or quantify the offset.
- **→ M09 (drift check):** `price_asof_by_ticker` is now in the raw JSONL but not in the
  frame. The drift check needs it to tell a lagging data sync from a signal change.
- **→ M09 (canaries), carried unchanged:** `object.__setattr__(ctx, "_accounting", True)`
  still reaches `prices_for_returns()`.

### Gate rulings recorded (no action wanted)

- **`KeyboardInterrupt` leaves zero journal records — ACCEPTED, deliberate.** `except
  Exception` does not catch `BaseException`. Catching it would delay an operator's Ctrl-C
  and would write a record from a partially unwound stack, possibly mid-`submit`, asserting
  an account state nobody verified. A killed Windows scheduled task raises nothing at all.
  One documentation clause should note the exclusion explicitly.
- **Roll-forward compares a ticker unadjusted when its actions fetch fails — ACCEPTED,
  conservative.** It can only cause a refusal, never a silently accepted wrong position.
  Caveat: it is currently the DEFAULT state rather than a rare edge, because nothing
  refreshes the actions cache; fixing the re-opened item above collapses it back to rare.


## M08 gate cycle 3 — ACCEPT (plans/state/M08/VERDICT.3.md)

Both cycle-2 blockers fixed and independently re-verified. M08 is accepted.

### Cycle-2 items — CLOSED

- **M02b/M04 actions-cache refresh policy — CLOSED (finally).** Re-opened at cycle 2 when
  the shared filter made the reactive policy unreachable; now implemented PROACTIVELY as
  the packet always specified. `_proactive_actions_refresh` reads the `fetched_at` sidecar
  via `backtest.context.actions_fetched_at` (the same helper the engine's provenance uses —
  still one implementation) for the declared universe AND every held ticker, refreshes what
  is stale, and only then builds the context; the reactive catch-and-retry is kept as a
  second line. Re-ran the gate's own cycle-2 probes on the SHIPPED declaration shape with
  real sidecar files: all-40-stale now trades with 40 refreshes and nothing dropped;
  1-of-40-stale refreshes exactly that one and includes it; a refresh that itself fails
  drops that ticker, journals it, and the run proceeds on 39.
- **Held-but-no-longer-in-universe tickers — CLOSED.** Refreshed too, which is what
  collapses the roll-forward residual.
- **`_refuse`'s own `broker.account()` call — CLOSED.** Guarded; a broker outage now leaves
  exactly one record with `account_before={"unavailable": "<Class>: <msg>"}` and both
  causes in the reason. The exactly-one-record guarantee holds for every `Exception` the
  gate could construct.
- **Non-blocking cycle-2 notes — ALL DONE.** `planned_orders` preserved on a submit-stage
  refusal; `_next_attempt_number` ignores refusals; `cancel_open_before_plan=False`
  documented as able to stack a live order; `KeyboardInterrupt` exclusion documented.

### Gate rulings recorded

- **The proactive refresh introduces NO look-ahead — verified, not assumed.** A refresh at
  `asof` legitimately pulls actions dated after `asof` into the cache. Planted a 10:1 split
  five days after `asof`: `ctx.prices` last close stayed at the raw 100.0, its max index was
  exactly `asof`, and the sized order was unchanged at 990 shares (a leak would have moved
  it ~10x). Canaries 24/24, including (f) and both halves of (k).
- **Roll-forward residual — CLOSED as a rare edge.** A dividend on a held name that left the
  index is now explained rather than refusing. The unadjusted-comparison fallback remains,
  still conservative (refusal only, never a silently accepted wrong position).
- **Autouse `_no_real_actions_refresh` fixture — ACCEPTED.** Required by CLAUDE.md invariant
  #5 and scoped to one file. Verified it hides nothing: the FULL suite passes with
  `socket.connect` replaced by a hard failure, so no test reaches the network, guarded or
  not; and the three refresh tests override it locally. Recommendation for the next time
  that file is touched: have the shared fixtures write fresh sidecars so the proactive pass
  honestly concludes "nothing to refresh", leaving the autouse no-op as a safety net rather
  than the thing that quiets the default path.

### → M09 items

- **→ M09 (or a fast follow), MUST FIX before `--dry-run` is trusted:** `cli.py:552-585`'s
  dry-run branch is a hand-rolled second decide-and-plan path. It wires none of
  `set_context_factory`, `_proactive_actions_refresh`, forced exits, `attempt`, cancellation,
  or `PaperRunConfig`. Measured on one stale-cache fixture: `--dry-run` raises
  `BacktestAbortError` where the real run refreshes 41 tickers and trades. Worst of it is
  that the blend per-child context guard (cycle-1 finding 5) is still OFF there, and
  `blend_50_50.yaml` ships, so a previewed blend book can differ from the real one. Remedy:
  give `run_once` a `dry_run` flag that stops after planning and have the CLI call it. The
  gate would have made this blocking had it been raised in cycle 1 or 2; it was left out of
  cycle 3's scope, cannot cause a trade, and fails loudly in its two likeliest forms.
- **→ M09 (data refresh), narrowed but still open:** the paper runner is now a real
  operational caller of `refresh_actions_cache`, so the actions half of this item is served
  for the paper path. Still missing: a `quantlab data refresh` command for the backtest
  path, and a force-clear for the quarantine and negative-cache sidecars
  (`clear_quarantine_meta` still has no caller).
- **→ M09 (drift check), must-fix before any forward-vs-backtest number is quoted:** the
  paper runner decides at the prior completed session's close and fills at the next open,
  roughly 1.5 sessions after the backtest's `close` convention. `assumed_fill_session` is
  journaled per run; compare against a `next_open`-mode backtest or quantify the offset.
- **→ M09 (drift check):** `price_asof_by_ticker` is in the raw JSONL but not in
  `journal_to_frame`; the drift check needs it to separate a lagging data sync from a real
  signal change.
- **→ M09 (canaries), carried unchanged:** `object.__setattr__(ctx, "_accounting", True)`
  still reaches `prices_for_returns()`.
- **Operational note for Alex:** a paper run now force-refreshes the actions cache for the
  whole declared universe whenever the sidecar is stale — roughly 500 vendor downloads on
  the first run after a gap, writing into the shared `data/cache`. Expected and correct for
  a live runner, but it is the first routine writer to that cache, so the first scheduled
  run will be slow and should not be interrupted.
