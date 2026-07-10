# M00 — Core scaffold: quant-gate VERDICT

VERDICT: ACCEPT

## Scope of this gate
Methodology only (bias, statistical validity, backtest realism); style/correctness
already vetted by code review (REVIEW.2.md: APPROVE). Focus per task: do the calendar
semantics and core types seed a look-ahead / survivorship / realism hazard for the
milestones that build on them (signal-at-close → trade-next-open timing, month-end
rebalancing, delisting exits)?

## Verification (gate-executed)
- `.venv/…/python -m pytest tests/ -q` → 31 passed, 0 skipped/error.
- Adversarial probes I ran directly:
  - `next_trading_day(Fri 2024-07-05)` → 2024-07-08 — **strictly** after for session
    inputs. This is the critical path: signal computed at the close of session D,
    executed at the next open via `next_trading_day(D)`, cannot see D+0's open. The
    trade-next-open contract is non-look-ahead **by construction** at the calendar
    layer. Confirmed.
  - `month_end` selection returns the true last session of each month
    (…2023-06-30, 2023-12-29…) — correct; `weekly` keys on ISO (year, week), so the
    year-boundary ISO-week aliasing is handled correctly.
  - `DelistingEvent` carries `reason ∈ {ACQUISITION, BANKRUPTCY, UNKNOWN}` — exactly the
    discriminator a forced-exit engine needs to apply reason-specific haircuts
    (CLAUDE.md #3). Good enabling design.

## Conclusion
The M00 calendar timing semantics and core contracts do **not** introduce look-ahead,
survivorship, or return-flattering bias by construction. The one bias-critical path
(next-open execution) is strict and correct. Types are neutral carriers with the right
PIT anchors (`Bar.date`, `TargetWeights.asof`, `DelistingEvent.last_trade_date`) and
the right delisting discriminator. Accept.

The following are **latent hazards that belong to downstream packets**, not defects in
M00. None weakens an existing bias guard, so none is a REJECT — but they must be
carried forward so the later milestone that owns each one does not inherit the trap
silently.

## Forward-carried notes (non-blocking; assign to the owning milestone)

1. **`Bar.adj_close` is look-ahead-contaminated by nature — the PIT/data milestone must
   not feed it to decisions.** A back-adjusted close bakes post-bar splits/dividends
   into historical bars; the adjustment factor for bar T depends on corporate actions
   after T. Confirmed the type carries it with no warning. This is fine for total-return
   accounting but is a classic subtle look-ahead if used at signal time.
   *Remedy (data/pit.py milestone):* `PITDataContext` must adjust as-of the asof date
   (or expose raw `close` for decisions and reserve `adj_close` for post-hoc return
   computation), and a bias canary should assert a strategy cannot read a future-dated
   adjustment. Flag so this isn't overlooked.

2. **`month_end`/`weekly` force a spurious rebalance on a range-terminal non-boundary
   day.** Reproduced: `rebalance_dates("2023-01-01","2023-06-15","month_end")` →
   [...,2023-05-31, **2023-06-15**]; the final group's last day is always emitted even
   though 2023-06-15 is not a month end (same for a mid-week `weekly` end). Not
   look-ahead and not directionally return-flattering, but a backtest whose window ends
   mid-period will book an unintended rebalance/turnover on the last day.
   *Remedy (backtest engine milestone):* either document that the terminal day is an
   intentional final rebalance, or have the engine drop a terminal date that is not a
   true period boundary. Decide explicitly rather than inherit by accident.

3. **`prev_trading_day` is strict for session inputs — a foot-gun for as-of alignment.**
   Confirmed `prev_trading_day(Mon 2024-07-08)` → 2024-07-05, i.e. it does **not**
   return X when X is itself a session. Downstream code reaching for "most recent
   trading day on or before X" (a natural PIT alignment) would land one session too
   early. The strict semantics are correct and documented; the risk is misuse.
   *Remedy (data/pit milestone):* provide/use an explicit "as-of session (inclusive)"
   helper for PIT snapshotting rather than repurposing `prev_trading_day`. Note the
   error direction here is conservative (too-early, not future-peeking), so it is a
   correctness/robustness risk, not a bias risk.

4. **Frozen models are shallow — `TargetWeights.weights` and
   `PortfolioSnapshot.positions` dicts remain mutable in place** (flagged in HANDOFF.md).
   `frozen=True` blocks attribute reassignment but not `tw.weights["X"]=…`. For a PIT
   snapshot contract this is an integrity hazard: a cached "past" target could be
   silently rewritten, a soft form of look-ahead.
   *Remedy (whichever milestone first caches these across time):* store weights/positions
   as an immutable mapping (e.g. defensive-copy + `MappingProxyType`, or a
   `frozendict`), or add a canary asserting a retained snapshot is unaltered after
   downstream processing.

5. **`Bar` performs no OHLC finiteness/ordering/non-negativity validation** (only
   `TargetWeights`/`Order`/`Fill` validate finiteness, per packet). A NaN/negative price
   entering a backtest is a data-quality hazard.
   *Remedy (data ingestion milestone):* enforce Bar quality at the ingestion boundary
   and raise `DataQualityError` (the base type already exists in `core/errors.py`);
   extend `tests/canaries/` accordingly.

## Not reviewed
- CLI stub, config loader internals, errors — outside the methodology mandate; code
  review covered them.
