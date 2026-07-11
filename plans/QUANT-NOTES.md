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
- **→ HARD CONDITION, own packet BEFORE any M03 cross-time price signal:** as-of
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
