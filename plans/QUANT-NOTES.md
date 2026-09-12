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
