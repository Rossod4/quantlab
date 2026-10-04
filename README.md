# QuantLab

A point-in-time, bias-audited research platform for systematic EOD equity strategies,
built to answer one question honestly: **once look-ahead, survivorship and cost realism are
enforced structurally rather than promised, do textbook momentum and value tilts still clear a
platform's own bar for paper trading?**

Built by [Alex Gard](mailto:arwgard@icloud.com), Mathematics undergraduate at the University of
Bristol, trading a retail account on Trading212. QuantLab is the successor to
[MomentumValueStrategy](../MomentumValueStrategy), a from-scratch backtester built as a study; this
platform ports its strategies onto a data layer where look-ahead is structurally impossible and
adds a multi-stage validation gate (deflated Sharpe, purged/embargoed cross-validation, White's
Reality Check / Hansen SPA, block-bootstrap Monte Carlo, capacity) that a strategy must clear
before it is ever paper traded with real (if small) money.

## The headline result

Three long-only strategies, 2012-01-01 to 2026-06-30, real S&P 500 point-in-time membership, real
SEC EDGAR filings, real cached Yahoo Finance prices, `month_end` rebalance, 10 bps one-way cost:

| | Momentum (12-1) | Value composite | 50/50 blend |
|---|---|---|---|
| Net CAGR | 17.66% | 17.19% | 17.67% |
| Net Sharpe | 0.98 | 0.95 | 1.03 |
| Max drawdown | -23.25% | -34.75% | -28.36% |
| **Verdict** | **REJECTED** | **REJECTED** | **REJECTED** |

SPY over the same window: CAGR 14.81%, Sharpe 1.06 (`reports/momentum_12_1/report_card.md`).

**The honest reading.** All three strategies beat SPY on raw return (17.66%, 17.19% and 17.67% vs
14.81% CAGR) but none beats it risk-adjusted (Sharpe 0.98, 0.95 and 1.03 vs SPY's 1.06) over this
window, and the measured 28.4% worst-year coverage gap alone exceeds the platform's 15% ceiling -
independent, correct reasons to reject each. Momentum additionally fails White's Reality Check
(p=0.144 against a 0.10 bar, over 10 realised trials) and the blend narrowly fails it too
(p=0.1045, over 3 realised trials). The platform's own gates are designed to say REJECTED or RESEARCH_ONLY more often
than they say ELIGIBLE_FOR_PAPER, on purpose - a verdict states which tests a result survived, not
that it has edge. See each strategy's linked report for the full gate table, and
[plans/QUANT-NOTES.md](plans/QUANT-NOTES.md) for the complete, unredacted history of every bug the
loop below caught before these numbers were trustworthy enough to publish.

## The loop that built this, and what the gate caught

QuantLab was built milestone-by-milestone through a three-role agent loop (developer implements,
code-reviewer checks correctness and reuse, quant-gate runs its own adversarial statistical
probes) rather than by one pass of "write it and ship it" - see
[plans/PROTOCOL.md](plans/PROTOCOL.md) for the mechanics and
[plans/ORCHESTRATOR-HANDOFF.md](plans/ORCHESTRATOR-HANDOFF.md) for the milestone-by-milestone
state. Every gate verdict is committed, not summarised after the fact:

| Milestone | Gate outcome | What it caught |
|---|---|---|
| [M00 core scaffold](plans/state/M00/VERDICT.md) | ACCEPT | - |
| [M01 data providers](plans/state/M01/VERDICT.md) | ACCEPT | `.gitignore` silently masking the whole data package; a yfinance 1.x MultiIndex break |
| [M02 PIT core](plans/state/M02/VERDICT.md) | ACCEPT, escalated | raw-price momentum reading a 10:1 split as a -90% return |
| [M02b adjustment replay](plans/state/M02b/VERDICT.2.md) | REJECT -> ACCEPT | as-of adjustment replay shipped to close the split-distortion hazard |
| [M03 strategy framework](plans/state/M03/VERDICT.md) | ACCEPT | stale per-share fundamentals across a split, biasing the value book toward recent winners |
| [M03b share terms](plans/state/M03b/VERDICT.md) | ACCEPT | TTM EPS mixed-share-terms residual (closed for real in M09, below) |
| [M04 backtest engine](plans/state/M04/VERDICT.2.md) | REJECT -> ACCEPT | 5 accounting bugs (forced-exit return basis, haircut not reaching the reported series, coverage bound measuring the wrong universe) |
| [M04b engine perf + real-data quality](plans/state/M04b/VERDICT.2.md) | REJECT -> ACCEPT | Yahoo symbol reuse splicing unrelated companies' price histories under one ticker (TIE, BMC, PTV and 44 others) |
| [M05 validation I](plans/state/M05/VERDICT.2.md) | REJECT -> ACCEPT | a sub-period table silently blind to its own first return |
| [M06 validation II](plans/state/M06/VERDICT.3.md) | REJECT (x2) -> ACCEPT, escalated | recording MORE trials could RAISE the deflated Sharpe ratio; a headline strategy excludable from its own Reality Check |
| [M07 reporting](plans/state/M07/VERDICT.2.md) | REJECT -> ACCEPT | a walk-forward comparison table silently transposed, showing `n/a` everywhere |
| M09 end-to-end (this milestone) | see [plans/state/M09/HANDOFF.md](plans/state/M09/HANDOFF.md) | per-component TTM EPS restatement across a split; see the reconciliation below |

`plans/QUANT-NOTES.md` carries every non-blocking hazard forward between milestones so nothing
found once is ever silently dropped - it currently runs to well over a thousand lines, and that is
the point, not a defect.

## Bias controls by construction, not by policy

- **No look-ahead, structurally.** A strategy never receives a raw data provider - only a
  `PITDataContext` hard-bound to one `asof` date (`src/quantlab/data/pit.py`). Every accessor
  hard-slices to `<= asof` and then asserts nothing slipped through; a canary suite
  (`tests/canaries/`) plants adversarial future-dated rows and future-dated corporate actions and
  asserts they never reach a strategy, mutation-tested at every gate.
- **Prices are as-of adjusted, not raw.** `prices()` replays every corporate action with
  ex-date `<= asof` into a cumulative adjustment factor, so a stock split during the backtest
  window never reads as a spurious return collapse - the exact bug the M02 gate caught and M02b
  closed. The untouched raw price stays available under `raw_close` for level metrics (P/E, P/B),
  which must never be computed on the adjusted series.
- **Fundamentals gate on SEC `filed` date, never fiscal period end**, with a configurable
  same-day filing lag (default 1 session) so an after-hours filing is never visible to a
  same-day close decision.
- **Corporate-action share terms are restated per-component.** A per-share figure (EPS,
  shares outstanding) is only comparable to an as-of price once it is expressed in the SAME share
  terms - M03 closed this for shares outstanding and the simple case; M09 closes the residual
  where a TTM EPS sum straddles a split between two of its own component filings (see
  `data/providers/edgar_fundamentals.py`'s `_ttm_duration_components` and
  `data/pit.py`'s per-component restatement).
- **Survivorship is measured, not footnoted.** Every `BacktestResult` embeds a coverage-gap
  bound (`data/survivorship.py`): the worst single sampled year's percentage of point-in-time
  index members with no cached price history, or masked by a metadata-truncated cache, or
  quarantined as a corrupted/reused ticker symbol.
- **Delistings book a forced exit**, never a silent drop, at the last available price
  (haircut configurable), on the same total-return basis every other name uses.
- **Data quality is enforced, not merely detectable.** `data/quality.py`'s cache-level scan
  (`quantlab data scan`) quarantines a ticker whose cached history shows the fingerprint of Yahoo
  reassigning a delisted ticker's symbol to an unrelated company - a real hazard this project hit
  on its first real-data run (see the reconciliation below), not a hypothetical one.
- **Ported numerical logic is frozen.** Anything ported from the predecessor
  [MomentumValueStrategy](../MomentumValueStrategy) repo must pass parity tests to 1e-10
  (signals) or a documented tolerance (equity curves) - `tests/parity/`. It is never
  "improved" without a new, explicit parity decision.
- **No chart-pattern or technical-pattern analysis, ever.**

## The validation gate

`quantlab validate --full` composes point-in-time metrics with a multiple-testing-aware
statistical gate and produces exactly one of three verdicts:

- **REJECTED** - at least one HARD gate failed (deflated Sharpe ratio, White's Reality Check,
  net Sharpe vs. benchmark, the coverage bound, minimum track-record length).
- **RESEARCH_ONLY** - every hard gate passed but at least one SOFT gate failed (PSR, no-cliff
  sensitivity score alongside a minimum net Sharpe, Monte Carlo drawdown, Hansen SPA, walk-forward
  weight stability, max drawdown floor, rolling-window negative-CAGR fraction).
- **ELIGIBLE_FOR_PAPER** - every hard and soft gate passed.

A third gate class, **`informational`**, is always computed and reported (currently just
capacity: the AUM ceiling implied by spread and daily volume) but never affects the verdict - at
Alex's real retail stake (order GBP100-500), the capacity gate is essentially unfalsifiable, and a
green badge there would misleadingly imply an edge the result does not evidence (orchestrator
decision, `plans/QUANT-NOTES.md`).

**A verdict is not evidence of edge; it states which tests the result survived.** REJECTED or
RESEARCH_ONLY versus SPY is a correct output of an honest platform, not a bug in it - the
opposite (everything backtested clears every gate) would be the thing to distrust.

## How to run it

```
uv sync                                  # Python 3.12+
uv run pytest                            # offline, all green (see plans/state/M09/HANDOFF.md)
uv run ruff check && uv run ruff format --check

uv run quantlab data status              # cache coverage, negative-cache/quarantine counts
uv run quantlab data scan                # quarantine corrupted/reused-symbol tickers (offline)
uv run quantlab data prefetch --start 2012-01-01 --end 2026-06-30   # warm the cache (network)

uv run quantlab run \
  --backtest configs/backtests/momentum_12_1_2012_2026.yaml \
  --out reports/momentum_12_1
```

Run `quantlab data scan` after ANY cache rebuild or `prefetch`, and before every real run: the
quarantine verdict lives in each ticker's own price sidecar plus a cache-level scan manifest, so a
rebuilt cache starts with neither. A run on a never-scanned cache is **caveated, not refused** -
the report's known-caveats list names the unvisited tickers - which is exactly why the scan has to
be a deliberate step.

For a blend, the walk-forward weight check and its ranking-agreement check under both cost
conventions need the standalone sleeve runs (`reports/momentum_12_1`, `reports/value_composite`,
produced above) plus one dedicated blend backtest per INTERIOR grid weight (the endpoints of the
grid ARE the standalone sleeves). The two interior runs are NOT committed (about seven hours
each); regenerate them from the committed configs, then validate and render the blend with the
sleeve results attached (`quantlab run --child-result ... --netted-grid-result ...` takes the same
flags but re-runs the blend backtest first):

```
uv run quantlab backtest --config configs/backtests/blend_50_50_2012_2026.yaml --out reports/blend_50_50
uv run quantlab backtest --config configs/backtests/blend_75_25_2012_2026.yaml --out reports/netted_grid/blend_75_25
uv run quantlab backtest --config configs/backtests/blend_25_75_2012_2026.yaml --out reports/netted_grid/blend_25_75

uv run quantlab validate --full --result reports/blend_50_50 --out reports/blend_50_50 \
  --child-result reports/momentum_12_1 --child-result reports/value_composite \
  --netted-grid-result 0.75,0.25=reports/netted_grid/blend_75_25 \
  --netted-grid-result 0.5,0.5=reports/blend_50_50 \
  --netted-grid-result 0.25,0.75=reports/netted_grid/blend_25_75 \
  --record-trial reports/netted_grid/blend_75_25 --record-trial reports/netted_grid/blend_25_75
uv run quantlab report --result reports/blend_50_50 --out reports/blend_50_50
```

`--record-trial` records the two interior blends as blend-family trials (with their return series)
so the multiple-testing correction counts them; the endpoints are the momentum and value
strategies, counted in their own families (and in the blend family only through the five
historical rows).

Both conventions are measured on the walk-forward's out-of-sample window; each grid point's source
run and strategy id is recorded in the card's `ranking_agreement` block, and any missing or
mismatched input shows up as "not checked: <reason>" rather than a number
(`src/quantlab/validation/netted_grid.py`).

`quantlab run` chains backtest -> `validate --full` -> `report` into one directory and exits
0 (ELIGIBLE_FOR_PAPER), 2 (RESEARCH_ONLY) or 3 (REJECTED) so a scheduler can branch on the
verdict. Each of `backtest`, `validate` and `report` also works standalone - see
`quantlab <command> --help`.

### `quantlab data`

| Command | What it does |
|---|---|
| `prefetch --start --end [--universe sp500_history]` | Warm the cache for every point-in-time constituent over the window plus the benchmark (prices, corporate actions, EDGAR facts). Idempotent; writes a per-ticker failure summary to `<cache_dir>/prefetch_report.json`. |
| `refresh [--tickers t1,t2 \| --all] [--actions] [--prices] [--fundamentals] [--clear-negative-cache] [--unquarantine TICKER] [--as-of DATE]` | Force a fresh corporate-actions download (the only way to clear a `StaleActionsCacheError`), re-fetch prices past their cached `requested_end`, force an EDGAR refetch, force-clear a `no_data` negative-cache sidecar, or clear + re-fetch + re-scan one quarantined ticker. |
| `scan [--with-membership/--no-membership]` | Offline. Quarantines a ticker whose cached price history is corrupted (a zero-volume dead series, an unexplained repeated price jump, a Yahoo symbol reused for a different company after the original delisted). Writes a cache-level scan-coverage manifest so a never-scanned cache is never mistaken for a scanned-and-clean one. |
| `status` | Per-kind ticker counts, the actions cache's `fetched_at` range (the negative-cache/staleness TTL makes a run's own data visibility wall-clock dependent - this is how you can tell), negative-cache count, quarantined tickers and reasons, masked-truncation count, and how many cached tickers have never been scanned. |

## The three real results

Run on the shared, prefetched `data/cache` after a fresh `quantlab data scan` (36 tickers
quarantined; 168 more have no cached price series at all and sit behind the 30-day negative cache),
2012-01-01 to 2026-06-30, `month_end` rebalance, `close` execution (parity mode), flat 10 bps
one-way cost. The three backtests ran from clean commit `dc5356d`; the cards were validated by
the code recorded in each card's `provenance.validated_by_git_sha` where present (the momentum and
blend cards, re-validated after the review fixes) and otherwise by `dc5356d` too.

| | Momentum 12-1 | Value composite | Blend 50/50 |
|---|---|---|---|
| Config | [`momentum_12_1_2012_2026.yaml`](configs/backtests/momentum_12_1_2012_2026.yaml) | [`value_composite_2012_2026.yaml`](configs/backtests/value_composite_2012_2026.yaml) | [`blend_50_50_2012_2026.yaml`](configs/backtests/blend_50_50_2012_2026.yaml) |
| Net CAGR | 17.66% | 17.19% | 17.67% |
| Net Sharpe | 0.98 | 0.95 | 1.03 |
| Max drawdown | -23.25% | -34.75% | -28.36% |
| Verdict | REJECTED | REJECTED | REJECTED |
| Backtest wall time | 1,329 s | 23,373 s | 25,352 s |
| Report | [reports/momentum_12_1/report.md](reports/momentum_12_1/report.md) | [reports/value_composite/report.md](reports/value_composite/report.md) | [reports/blend_50_50/report.md](reports/blend_50_50/report.md) |

Every number above is in the committed `report_card.md` / `report_card.json` / `report.md` in
each strategy's own `reports/<name>/` directory (the run-seconds figure is the provenance table's
"Run seconds" row); the run-level call counts quoted below are in `plans/state/M09/EVIDENCE.md`. **The wall-clock figures are not benchmarks.**
"Backtest wall time" is the backtest alone, and the runs shared one
laptop that went into standby overnight while five jobs ran concurrently (momentum alone first,
about 22 minutes; value and the three blend backtests together afterwards, 6.5-7 hours each). The
only supportable statement is the ordering: value and blend are far slower than momentum because
they read EDGAR fundamentals for every ticker at every rebalance (86,964 fundamentals calls each,
against none for momentum), and the blend does that work for its value sleeve in addition to
momentum's. The full `quantlab run` (backtest plus the sensitivity grid, which re-runs the real
engine for every grid point) took 10.1 hours for momentum on that shared, sleeping machine.

**Momentum - REJECTED.** Hard-gate failures: net Sharpe 0.98 vs SPY's 1.06; coverage bound 28.4%
vs the 15% ceiling; White's Reality Check p=0.1443 vs 0.10 (K=10 trials); minimum track-record
length unbounded. It passes the deflated Sharpe ratio (DSR 0.9823 vs 0.95, N=9 distinct trials), the
probabilistic Sharpe ratio (0.9998) and the no-cliff sensitivity gate (0.9720, but over a truncated
neighbourhood: the headline `n_long=30` sits at the edge of the `[30,50,70]` grid, so only 6 grid
points are compared and the score is mechanically flattered; the card shows `neighbourhood_size=6,
neighbourhood_truncated=True`). Soft failures: Hansen SPA
p=0.1990 and the Monte Carlo drawdown check (0.50 against a 0.50 bar - a coin flip).

**Value composite - REJECTED.** Hard-gate failures: net Sharpe 0.95 vs SPY's 1.06; coverage bound
28.4% vs the 15% ceiling; minimum track-record length unbounded. It passes the deflated Sharpe
ratio (DSR 0.9917, N=3 distinct trials), White's Reality Check (p=0.0149, K=4) and Hansen SPA
(p=0.0199), PSR (0.9992), no-cliff (0.9322 over a 3-point grid), and every other soft gate
(Monte Carlo drawdown 0.33). The statistical machinery is saying that the value book is not
noise. The verdict is REJECTED because three HARD gates fail (net Sharpe vs SPY, the coverage
bound, and minimum track-record length), not because of the drawdown: the 34.75% maximum
drawdown (the covid 2020 window, the deepest of the three strategies) is within the -50% floor
and that gate passes; it is context, not a rejection reason. Value has no
walk-forward result of its own, so that gate is vacuous.

**Blend 50/50 - REJECTED.** Hard-gate failures: net Sharpe 1.03 vs SPY's 1.06; coverage 28.4%;
White's Reality Check p=0.1045 vs 0.10 (K=3 trials - a near miss, not a clear one); minimum
track-record length unbounded. It passes the deflated Sharpe ratio (DSR 0.9849, N=8 distinct trials)
and the probabilistic Sharpe ratio (0.9997), and Hansen SPA (p=0.0796). Soft failure: no-cliff, only
because no sensitivity grid is configured for the blend (its weight grid is its only explored axis);
that is a "not evaluated" failure, not evidence of a cliff.

The blend family's N=8 is the five historical rows from the predecessor repo's weight sweep
(momentum weight 1.00 / 0.75 / 0.50 / 0.25 / 0.00: seeded with no return series and no Sharpe),
the 50/50 headline, and the two interior-weight backtests (75/25 and 25/75) that were really run
through the engine as live alternatives and are recorded as trials with their return series. So
the 0.75, 0.50 and 0.25 hypotheses are each counted twice (historical row plus a real backtest),
and the two endpoints enter the blend family only through their historical rows (the standalone
momentum and value runs are additionally counted in their own families). The series-less
historical rows raise N but stay out of the trial-variance estimate (only the three finite-Sharpe
trials enter it, floored at 1/(n-1)), which can only lower the deflated Sharpe ratio: the count is
conservative.

Its walk-forward weight check passes (the modal weight tuple was chosen in 70% of steps against a
50% bar), but the walk-forward chose 0% momentum / 100% value in seven of its ten steps and
`[0.75, 0.25]` or `[1.0, 0.0]` in the last three: the weight choice is not stable in the sense that
matters, and a pass on that gate should not be read as stability.

**Ranking agreement under both cost conventions (the blend's walk-forward grid).** The engine costs
the netted book; the walk-forward blends each sleeve's net returns. Over the walk-forward
out-of-sample window (2017-02-28 to 2026-06-30, 113 months) the five fixed-weight Sharpes are, for
momentum weight 1.00 / 0.75 / 0.50 / 0.25 / 0.00: netted book 0.957 / 0.967 / 0.943 / 0.884 / 0.801,
blend-of-nets 0.957 / 0.967 / 0.943 / 0.884 / 0.801 (every point agrees to within 0.0002). Kendall
tau = 1.0 over five points and the top choice (75/25) agrees, so on this data the netted-book
costing does not change which weight the walk-forward would prefer. This is weak evidence: two of
the five points are the same runs by construction, and on long-only sleeves netting barely matters. The endpoints are the standalone
sleeve runs; `tests/test_blend_endpoint_equivalence.py` pins that a weight-1.0 blend reproduces its
child's returns exactly, costs included. All five inputs, with run directory and strategy id, are in
`reports/blend_50_50/report_card.json` (`ranking_agreement`).

### Reconciliation against the predecessor repo's momentum result

The predecessor [MomentumValueStrategy](../MomentumValueStrategy) repo reports net CAGR 15.7%,
Sharpe 0.96, max drawdown -19.7% for 12-1 long-only momentum. **It is not the same strategy as
QuantLab's headline:** the predecessor holds the top 50 names (`src/config.py`, `top_n=50`;
"equal-weight top-50 portfolios"), QuantLab's headline holds 30 (`n_long: 30` in
`configs/strategies/momentum_12_1.yaml`, unchanged since M03 and not chosen after seeing results).
QuantLab's own committed sensitivity grid contains the predecessor's exact parameterisation,
lookback 12 / skip 1 / 50 names, so the comparison can be made like for like:

| | net CAGR | Sharpe | max drawdown |
|---|---|---|---|
| predecessor (top 50, its own data layer) | 15.7% | 0.96 | -19.7% |
| QuantLab, same parameters (grid point lookback 12, n_long 50) | 16.29% | 0.991 | -20.09% |
| QuantLab headline (lookback 12, n_long 30) | 17.65% | 0.978 | -23.25% |

(QuantLab rows recomputed from the trials-registry series, `momentum_12_1-c993bc68ed` and
`momentum-2b2c9fd50a`; `plans/state/M09/EVIDENCE.md` gives the exact command, series hashes and
conventions. The headline's card says 17.66% under the card's CAGR convention.)

- **Portfolio size is the dominant mechanism.** Holding 30 instead of 50 names moves QuantLab's
  own number by +1.36 pp CAGR and -3.16 pp drawdown. That is about 1.4 of the 1.96 pp CAGR gap and
  about 3.2 of the 3.55 pp drawdown gap between the predecessor and QuantLab's headline. The
  Sharpe barely moves (0.991 vs 0.978), consistent with a more concentrated book taking more risk
  for more return. Of the nine grid points the headline has the second-lowest Sharpe, so it was
  not selected from the grid for looking good.
- **What is left after matching portfolio size:** about +0.6 pp CAGR, +0.03 Sharpe and -0.4 pp
  drawdown against the predecessor. For scale, SPY over the same window differs by about +0.3 pp
  between the two code bases (the quant gate's comparison: 14.5% in the predecessor, 14.81% here),
  which is the size of the price-vintage and price-basis noise between them, before quarantine
  (below) is counted. This residual is not decomposable further from the outputs of this run.
- **Engine and merge history (cannot have moved it).** The same configuration on the engine from
  before M08 was merged (commit `7e904cd`) and on the final engine (`dc5356d`), against one cache,
  gives identical net returns (maximum absolute difference 0.0 over 173 periods). The only
  difference from the 12 September run of the same code is 1.6e-7 per period (all 173 periods):
  data vintage, not code. Commands, shas and series hashes are in `plans/state/M09/EVIDENCE.md`.
- **M04b mechanisms that could NOT have moved it:** the backtest window clamp and the
  benchmark-from-store change (the M04b gate verified a bit-identical A/B, `plans/QUANT-NOTES.md`).
- **Symbol-reuse quarantine DID move it**, by -0.18 pp CAGR at the M04b gate (17.84% to 17.66%, on
  0.42% of position-periods). The predecessor had no quality-scan layer. QuantLab quarantines 36
  such names today (42 at the 12 September run; six of those now have no cached series and sit in
  the negative cache instead).
- **Forced exits:** 1 across the run, **extreme-return guard:** 0 long-book and 0 short-book
  exclusions (`report_card.md` trust panel) - neither can explain any of the gap.
- **Adjustment replay (M02b):** QuantLab replays every corporate action into the as-of price
  adjustment; whether the predecessor's own split handling diverges is not independently
  re-measurable here and is not assumed to be zero.
- **Filing lag, netted-book blend costs:** not applicable to momentum.

### Value composite: the September run against the final run

The 13 September value run (committed at `dc5356d`) read net CAGR 17.63%, Sharpe 0.9747, maximum
drawdown -34.76%; the final run reads 17.19%, 0.9493, -34.75%. The repository also holds a second
September run of the SAME strategy at the SAME parameters: the 25 September sensitivity grid
contains the headline's own point (`value_composite-b67309d696`, n_holdings=30). Both September
runs ran on the same rebuilt, unscanned cache (0 quarantined, 805 tickers never scanned); the
final run ran after the 1 October scan (36 quarantined). The three series, recomputed from the
registry backups (`plans/state/M09/EVIDENCE.md`, `plans/state/M09/recon_tables.py`):

| run | net CAGR | Sharpe | 2012-19 | 2020 | 2021-22 | 2023+ |
|---|---|---|---|---|---|---|
| 13 Sept (unscanned) | 17.62% | 0.9747 | 19.60% | 4.31% | 8.88% | 22.51% |
| 25 Sept (unscanned, same params) | 17.49% | 0.9701 | 19.63% | 3.71% | 6.52% | 23.65% |
| final, 1 Oct (36 quarantined) | 17.19% | 0.9493 | 19.63% | 3.71% | 6.20% | 22.52% |

- **13 -> 25 September (-0.13 pp CAGR, -0.005 Sharpe) is NOT quarantine:** the quarantine count
  was 0 on both, yet 172 of 173 periods differ, the whole 2020 move (4.31% to 3.71%) and most of
  the 2021-22 move (8.88% to 6.52%) happen here. **This part is UNRESOLVED.** Candidate causes:
  (a) the 13 September run came from a dirty tree (`395bd98`, M09 iteration 1 in progress) and the
  25 September run from a different dirty tree, so the code itself differed (the 7e904cd/dc5356d
  A/B covers momentum only and says nothing about the fundamentals path); (b) fundamentals cache
  vintage: the EDGAR facts for 66 tickers were first written on 23-24 September, after the 13
  September run had finished (the run took 2h51m, so it ended well before 23 September): LVS, SNDK, SO, SPG, SPGI, SRE, STI, STT,
  STZ, SUN, SWK, SYK, SYY, T, TAP, TDC, TE, TEL, TER, TGT, THC, TJX, TMO, TMUS, TPR, TRIP, TROW,
  TRV, TSN, TXN, TXT, UNH, UNM, UNP, UPS, URBN, USB, V, VFC, VIAV, VLO, VMC, VNO, VRSN, VTR, VZ,
  WAT, WDC, WEC, WELL, WFC, WHR, WM, WMB, WMT, WU, WY, WYNN, XEL, XOM, XRAY, XRX, XYL, YUM, ZBH,
  ZION. Neither is established.
- **25 September -> final (-0.30 pp CAGR, -0.021 Sharpe) is the only part consistent with
  quarantine**: only 39 periods differ, the first on 2021-09-30, and that is the only window in
  which the 36 contaminated series could matter. Even here it is "consistent with", not proven: the
  code also moved between those two dirty trees.
- **What cannot be established.** The September holdings were overwritten, so there is no
  ticker-level attribution, and no re-run was done. The unresolved 13 -> 25 September movement is
  a finding for the gate, not an explained difference. Neither number changes the verdict: all of
  them are REJECTED on the same three hard gates.

## Known limitations

- **Free data, not a paid vendor feed.** Prices are Yahoo Finance via `yfinance`; index membership
  is a free, community-maintained reconstruction
  ([fja05680/sp500](https://github.com/fja05680/sp500)), not an official index vendor's
  point-in-time feed - membership dates can be imprecise by weeks. Fundamentals are SEC EDGAR's
  XBRL company-facts API, which is authoritative on `filed` date but only covers companies still
  SEC-registered today, reintroducing a fundamentals-specific coverage gap the price side does not
  have.
- **A real, measured fraction of the historical universe is invisible in the worst sampled year**
  (the coverage-gap bound - see each report's Trust panel and the reconciliation above for the
  exact figure) - long-delisted names Yahoo no longer serves at all, plus a cache-metadata-masked
  truncation for a handful of tickers, plus the tickers `quantlab data scan` quarantined before
  these runs (the exact count is in each report's provenance) for a corrupted or Yahoo-symbol-reused price history. This is a ceiling on
  invisibility, not a return impact, and SPY does not suffer it, which slightly flatters every
  strategy-vs-SPY comparison here.
- **TTM EPS can still be off by more than a per-component restatement fixes** when a filer's
  comparatives have not yet been restated by a later filing and the company's own reporting
  convention does not follow the modelled quarter/annual duration windows - a narrower, documented
  residual (see `strategies/value.py`'s and `data/pit.py`'s own module docstrings).
- **The extreme-return guard is upside-only, inherited unmodified from the predecessor repo.** It
  is conservative on a long book and anti-conservative on a short book (it can discard a genuine
  short-squeeze loss) - not a live hazard for the three long-only results here, but binding on any
  future long-short or 130/30 promotion.
- **The capacity gate is demoted to informational at this stake.** At `intended_capital_usd:
  1000`, the 100x-multiple bar is trivially clearable against any liquid large-cap book; see "The
  validation gate" above. The predecessor repo's own real-data capacity estimate on 2012-2026 S&P
  500 data was $95M-$335M AUM under a 50-name-book assumption - for scale only, never this run's
  own output.
- **The negative-cache/actions-staleness TTL makes a run's own data visibility wall-clock
  dependent** - the same config run today and in 31 days can see a different set of tickers
  (`quantlab data status`'s `fetched_at` range and negative-cache count are how this is surfaced,
  not hidden).
- **Quarantine and scan state is not self-healing.** It is stored per ticker in the price sidecar
  (`quarantined: true`) and in a cache-level scan manifest (`prices/_scan_manifest.json`). No
  ordinary read or refresh drops it (a quarantined ticker is served as empty, never re-fetched),
  but rebuilding the price cache from scratch does, silently - this project's own 2026-09-12 cache
  rebuild did exactly that. Re-run `quantlab data scan` after any rebuild.
- **A strategy that deliberately does `object.__setattr__(ctx, "_accounting", True)`** can still
  reach the accounting-only price accessor from its own decision path - no Python guard can
  prevent this, and it requires obviously-subversive code; documented, not fixed.
- **Research and paper trading only. No live money moves through this platform.**
- Post-v1 backlog, not started: a Trading212 practice-account adapter, a Norgate Data provider,
  a forward-vs-backtest drift dashboard (the underlying `quantlab paper drift` check already exists -
  see `plans/state/M09/HANDOFF.md`), and new (never chart-pattern)
  strategy families.

## Repository layout

```
src/quantlab/
  core/            calendar, config, error types, cross-milestone data-semantics version
  data/            providers (yfinance prices, SEC EDGAR fundamentals, community S&P 500
                   membership), the point-in-time context, cache, quality/quarantine, operational
                   commands (ops.py)
  strategies/      momentum, value composite, blend - the Strategy ABC and DataRequirements
  backtest/        the generic EOD engine, accounting ledger, costs, panel store
  validation/      metrics, walk-forward, sensitivity, PSR/DSR, purged CV, Reality Check/SPA,
                   Monte Carlo, capacity, the trials registry, the report card
  reporting/       Jinja2 HTML + markdown twin, plots
  cli.py           `quantlab data|run|backtest|validate|report|paper`
tests/             offline, deterministic (tests/canaries/ for bias guards, tests/parity/ against
                   the predecessor repo's frozen numerics)
plans/             work packets, milestone loop artifacts (HANDOFF/REVIEW/VERDICT), QUANT-NOTES.md
configs/           platform.yaml, strategy YAMLs, backtest YAMLs, validation.yaml
reports/           the three real strategies' committed report cards, markdown reports and plots
```

## Design principles

- **Swappable data layer.** Strategy code never talks to a vendor directly, and never sees
  anything but a `PITDataContext` - the provider behind it is a one-line config change
  (`configs/platform.yaml`).
- **Config-driven thresholds.** Every gate bar lives in `configs/validation.yaml`, never hardcoded
  - changing the coverage-bound ceiling or the capacity multiple is a YAML edit, not a code change.
- **Honest numbers over flattering ones.** No result is rescued to clear a gate; a REJECTED
  verdict is reported with the same care as an ELIGIBLE_FOR_PAPER one, and every disclosed caveat
  stays in the rendered report verbatim.

## Development history

Built through the milestone loop described above with Claude Code assistance - every milestone's
`HANDOFF.md`/`REVIEW.md`/`VERDICT.md` is committed alongside the code it describes, so the
project's evolution (including every rejected iteration) is recoverable, not summarised away.
