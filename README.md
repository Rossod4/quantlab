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
| Net CAGR | 17.66% | _TBD (value run pending)_ | 17.67% |
| Net Sharpe | 0.98 | _TBD_ | 1.03 |
| Max drawdown | -23.25% | _TBD_ | -28.36% |
| **Verdict** | **REJECTED** | _TBD_ | **REJECTED** |

SPY over the same window: CAGR 14.81%, Sharpe 1.06 (`reports/momentum_12_1/report_card.md`).

**The honest reading.** Both finished strategies beat SPY on raw return (17.66% and 17.67% vs
14.81% CAGR) but neither beats it risk-adjusted (Sharpe 0.98 and 1.03 vs SPY's 1.06) over this
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
conventions need the standalone sleeve runs and one dedicated blend backtest per INTERIOR grid
weight (the endpoints of the grid ARE the standalone sleeves). Run the blend's own backtest with
`quantlab backtest`, then validate and render it (`quantlab report`) with the sleeve results
attached; `quantlab run --child-result ... --netted-grid-result ...` takes the same flags but
re-runs the blend backtest first:

```
uv run quantlab validate --full --result reports/blend_50_50 --out reports/blend_50_50 \
  --child-result reports/momentum_12_1 --child-result reports/value_composite \
  --netted-grid-result 0.75,0.25=reports/netted_grid/blend_75_25 \
  --netted-grid-result 0.5,0.5=reports/blend_50_50 \
  --netted-grid-result 0.25,0.75=reports/netted_grid/blend_25_75
```

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
one-way cost, from clean commit `dc5356d`.

| | Momentum 12-1 | Value composite | Blend 50/50 |
|---|---|---|---|
| Config | [`momentum_12_1_2012_2026.yaml`](configs/backtests/momentum_12_1_2012_2026.yaml) | [`value_composite_2012_2026.yaml`](configs/backtests/value_composite_2012_2026.yaml) | [`blend_50_50_2012_2026.yaml`](configs/backtests/blend_50_50_2012_2026.yaml) |
| Net CAGR | 17.66% | _TBD_ | 17.67% |
| Net Sharpe | 0.98 | _TBD_ | 1.03 |
| Max drawdown | -23.25% | _TBD_ | -28.36% |
| Verdict | REJECTED | _TBD_ | REJECTED |
| Backtest wall time | 1,329 s | _TBD_ | 25,352 s |
| Report | [reports/momentum_12_1/report.md](reports/momentum_12_1/report.md) | [reports/value_composite/report.md](reports/value_composite/report.md) | [reports/blend_50_50/report.md](reports/blend_50_50/report.md) |

Every number above is in the committed `report_card.md` / `report_card.json` / `provenance.json` in
each strategy's own `reports/<name>/` directory. "Backtest wall time" is `provenance.run_seconds`
for the backtest alone; the blend and value figures include an overnight machine sleep and several
runs sharing one machine, so they are upper bounds, not benchmarks. The full `quantlab run`
(backtest plus the sensitivity grid, which re-runs the real engine nine times for momentum) took
about ten hours for momentum on that shared machine.

**Momentum - REJECTED.** Hard-gate failures: net Sharpe 0.98 vs SPY's 1.06; coverage bound 28.4%
vs the 15% ceiling; White's Reality Check p=0.1443 vs 0.10 (K=10 trials); minimum track-record
length unbounded. It passes the deflated Sharpe ratio (DSR 0.9823 vs 0.95, N=9 distinct trials), the
probabilistic Sharpe ratio (0.9998) and the no-cliff sensitivity gate. Soft failures: Hansen SPA
p=0.1990 and the Monte Carlo drawdown check (0.50 against a 0.50 bar - a coin flip).

**Blend 50/50 - REJECTED.** Hard-gate failures: net Sharpe 1.03 vs SPY's 1.06; coverage 28.4%;
White's Reality Check p=0.1045 vs 0.10 (K=3 trials - a near miss, not a clear one); minimum
track-record length unbounded. It passes the deflated Sharpe ratio (DSR 0.9849, N=8 distinct trials)
and the probabilistic Sharpe ratio (0.9997), and Hansen SPA (p=0.0796). Soft failure: no-cliff, only
because no sensitivity grid is configured for the blend (its weight grid is its only explored axis);
that is a "not evaluated" failure, not evidence of a cliff.

The blend family's N=8 is the five historical rows from the predecessor repo's sweep, the 50/50
headline, and the two interior-weight backtests (75/25 and 25/75) that were really run through the
engine as live alternatives to the headline and are recorded as trials with their return series.
The grid endpoints (100% momentum, 100% value) are not blend trials: they are the momentum and
value strategies and count in their own families. The 0.50 hypothesis is counted twice (once as the
historical row, once as the headline), which can only make the correction more conservative.

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
costing does not change which weight the walk-forward would prefer. The endpoints are the standalone
sleeve runs; `tests/test_blend_endpoint_equivalence.py` pins that a weight-1.0 blend reproduces its
child's returns exactly, costs included. All five inputs, with run directory and strategy id, are in
`reports/blend_50_50/report_card.json` (`ranking_agreement`).

### Reconciliation against the predecessor repo's momentum result

The predecessor [MomentumValueStrategy](../MomentumValueStrategy) repo measured the SAME 12-1
long-only momentum strategy at **net CAGR 15.7%, Sharpe 0.96, max drawdown -19.7%**. QuantLab
measures **17.66% / 0.98 / -23.25%** (`reports/momentum_12_1/report_card.md`): +1.96 pp CAGR, +0.02
Sharpe, and a 3.55 pp deeper drawdown. Mechanism by mechanism:

- **Engine and merge history (cannot have moved it).** The same configuration run on the engine
  from before M08 was merged (commit `7e904cd`) and on the final engine (`dc5356d`), against one
  cache, gives identical net returns (maximum absolute difference 0.0 over 173 periods). The only
  difference from the 12 September run of the same code is 1.6e-7 per period (all 173 periods),
  which is data vintage (the price cache was rebuilt and the corporate-actions cache refreshed
  between the two runs), not code; headline metrics agree to seven digits. The A/B is recorded in
  `plans/state/M09/HANDOFF.md`.
- **M04b mechanisms that could NOT have moved it:** the backtest window clamp and the
  benchmark-from-store change (the M04b gate verified a bit-identical A/B, `plans/QUANT-NOTES.md`).
- **Mechanism that DID move it - symbol-reuse quarantine.** The predecessor had no quality-scan
  layer, so its universe could include price series spliced from two unrelated companies under one
  reused ticker. QuantLab quarantines 36 such names today (42 at the 12 September run; six of those
  now have no cached series at all and are suppressed by the negative cache instead). The M04b gate
  measured the effect of quarantining at -0.18 pp CAGR (17.84% to 17.66%) on 0.42% of
  position-periods - small, and in the return-lowering direction.
- **Forced exits:** 1 across the run (`report_card.md` trust panel) - immaterial.
- **Extreme-return guard:** 0 long-book and 0 short-book exclusions (`report_card.md`), so the
  guard's policy cannot explain any of the gap.
- **Adjustment replay (M02b):** QuantLab replays every corporate action into the as-of price
  adjustment; whether the predecessor's own split handling diverges is not independently
  re-measurable from this run and is not assumed to be zero.
- **Filing lag, netted-book blend costs:** not applicable to momentum (no fundamentals, not a
  blend).
- **What is left unexplained.** After the above, the residual ~2 pp CAGR and the 3.5 pp deeper
  drawdown against the predecessor are NOT decomposable from this run's outputs: the predecessor's
  data layer, universe construction and adjustment handling differ in ways nobody isolated, and
  the symbol-reuse contamination channel could account for "an amount nobody can currently state".
  This is reported as an open finding, not papered over.

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
