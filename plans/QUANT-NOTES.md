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
- **→ M03/M04:** EDGAR gate is day-granular (`filed <= asof`): a same-day, often
  after-hours filing is visible to a same-day close decision. Adopt a one-session
  filing lag (or evaluate fundamentals at the prior session), or document and defend
  the convention in the backtest spec.
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
