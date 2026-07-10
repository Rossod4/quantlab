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
