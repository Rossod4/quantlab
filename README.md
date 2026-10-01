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
| Net CAGR | 17.66% | _see [reports/value_composite/report.md](reports/value_composite/report.md)_ | _see [reports/blend_50_50/report.md](reports/blend_50_50/report.md)_ |
| Net Sharpe | 0.98 | | |
| Max drawdown | -23.25% | | |
| **Verdict** | **REJECTED** | | |

**The honest reading.** Momentum beats SPY on raw return (17.66% vs 14.81% CAGR) but not
risk-adjusted (Sharpe 0.98 vs SPY's 1.06) over this window, and its own measured 28.4%
worst-year coverage gap alone exceeds the platform's 15% ceiling - two independent, correct
reasons to reject it, on top of a trials registry too thin (this session) for a Reality Check to
run at all. The platform's own gates are designed to say REJECTED or RESEARCH_ONLY more often
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

Run on the shared, prefetched `data/cache` (842 tickers under active tracking, 664 with a live
price series, 47 quarantined by `quantlab data scan` before these runs - see below), 2012-01-01 to
2026-06-30, `month_end` rebalance, `close` execution (parity mode), flat 10 bps one-way cost.

| | Momentum 12-1 | Value composite | Blend 50/50 |
|---|---|---|---|
| Config | [`momentum_12_1_2012_2026.yaml`](configs/backtests/momentum_12_1_2012_2026.yaml) | [`value_composite_2012_2026.yaml`](configs/backtests/value_composite_2012_2026.yaml) | [`blend_50_50_2012_2026.yaml`](configs/backtests/blend_50_50_2012_2026.yaml) |
| Net CAGR | 17.66% | _TBD_ | _TBD_ |
| Net Sharpe | 0.98 | _TBD_ | _TBD_ |
| Max drawdown | -23.25% | _TBD_ | _TBD_ |
| Verdict | REJECTED | _TBD_ | _TBD_ |
| Backtest wall time | 749.8s (12.5 min) | _TBD_ | _TBD_ |
| Report | [reports/momentum_12_1/report.md](reports/momentum_12_1/report.md) | [reports/value_composite/report.md](reports/value_composite/report.md) | [reports/blend_50_50/report.md](reports/blend_50_50/report.md) |

Every number above is traceable to the committed `report_card.json`/`validation_basic.json` in
each strategy's own `reports/<name>/` directory - nothing here is hand-typed without a source file
backing it. "Backtest wall time" is the single-backtest figure only (`provenance.run_seconds`); the
full `quantlab run` (backtest + the sensitivity grid `validate --full` runs through the real engine
+ report) takes substantially longer - see plans/state/M09/HANDOFF.md for the honest wall-clock
accounting, including why this session's own timer reads far higher than the CPU time actually
spent (a sandboxed-session artifact, not a platform cost).

Momentum's own verdict: **REJECTED**. It clears the deflated Sharpe ratio (0.98 vs a 0.95 bar),
the probabilistic Sharpe ratio (0.9998), and every soft gate except the Monte Carlo drawdown check
(0.512 vs a 0.5 bar - essentially a coin flip, see the Known limitations section) - but it fails
THREE hard gates: net Sharpe (0.98) is below SPY's own Sharpe (1.06) over the same window, the
coverage bound (28.4%, driven by the 42 quarantined + 162 never-fetchable historical constituents)
exceeds the 15% ceiling, and White's Reality Check cannot run at all (this run's trials registry
starts fresh, so only momentum's own headline trial has a stored return series - fewer than the 2
a Reality Check needs, correctly treated as a failure rather than a vacuous pass). This is the
platform working as designed: a real, honestly-measured coverage gap and an as-yet-thin trial
history are exactly the kind of thing a rejection should turn on.

### Reconciliation against the predecessor repo's momentum result

The predecessor [MomentumValueStrategy](../MomentumValueStrategy) repo measured the SAME 12-1
long-only momentum strategy at **net CAGR 15.7%, Sharpe 0.96, max drawdown -19.7%** on an earlier,
narrower, less-audited data layer. QuantLab measures **17.66% / 0.98 / -23.25%** on the same
strategy, same window, same 10 bps cost. Every mechanism that could have moved the number is
accounted for below, mechanism by mechanism - see `plans/state/M09/HANDOFF.md` for the full
reconciliation and `plans/QUANT-NOTES.md`'s M04b entries for the original measurement this number
reproduces exactly.

- **This is not a new number.** 17.66% is EXACTLY M04b's own previously gate-verified real-run
  figure (`plans/QUANT-NOTES.md`, M04b gate cycle 2) - M09 changed nothing that touches momentum's
  own computation (the per-component TTM EPS fix only affects `ttm_eps`, which momentum never
  reads; the capacity-gate reclassification changes only how the verdict AGGREGATES gates, not any
  input number). Reproducing it exactly, on a freshly re-scanned cache, is itself a form of
  regression test.
- **Coverage/quarantine (moved it, old repo could not see this gap at all):** the old repo had no
  quality-scan layer, so its own universe could have silently included price series later found to
  be a splice of two unrelated companies under one reused ticker symbol (TIE, BMC, PTV and 44
  others). QuantLab's 42-quarantined-name universe is measurably cleaner; the M04b gate quantified
  the effect of quarantining these names at a 0.18pp CAGR reduction (from 17.84% to 17.66%) on
  0.42% of position-periods - small, and in the conservative (return-lowering) direction, since
  contaminated series more often manufacture spurious momentum winners than losers.
- **Forced exits:** 1 across the whole 14.5-year, ~170-rebalance run - immaterial to the CAGR gap.
- **The as-of adjustment replay (M02b):** QuantLab replays every corporate action into a
  cumulative price-adjustment factor before ranking, closing the exact "10:1 split reads as -90%"
  hazard the M02 gate found; whether or to what degree the old repo's own split handling diverges
  from this is not independently re-measurable from this run alone, and is not assumed to be zero.
- **Filing lag, netted-book blend costs:** not applicable - momentum uses no fundamentals and is
  not a blend.
- **Extreme-return guard:** 0 long-book exclusions triggered (long-only book, so the guard's
  short-book asymmetry - see Known limitations - never applies here either).
- **What is left unexplained:** the residual gap between quantlab's 17.66%/0.98/-23.25% and the old
  repo's 15.7%/0.96/-19.7% is NOT further decomposable from the outputs of this run alone. The
  M04b gate's own finding stands: the window clamp and the benchmark-from-store change cannot have
  moved it (verified bit-identical A/B at that gate); the symbol-reuse contamination channel
  definitely could, "by an amount nobody can currently state" since the old repo's own affected
  trades were never isolated. This is reported as an open item, not papered over.

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
