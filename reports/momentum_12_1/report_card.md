# QuantLab report - momentum-2b2c9fd50a

**Verdict: REJECTED** **DIRTY TREE**
`momentum-2b2c9fd50a` · data semantics `m09` · run 2026-09-12T17:18:52.240152+00:00 · git `395bd9894b720d2408df854290106e345bf33983` · quantlab 0.1.0

net CAGR 17.66%, Sharpe 0.98, max drawdown -23.25% - verdict REJECTED.

_REJECTED: at least one HARD gate failed. RESEARCH_ONLY: every hard gate passed but at least one SOFT gate failed. ELIGIBLE_FOR_PAPER: every hard and soft gate passed. Hard-gate failures cap the verdict at REJECTED; soft-gate failures cap it at RESEARCH_ONLY; gates of kind INFORMATIONAL (capacity, at Alex's retail stake - orchestrator decision, plans/QUANT-NOTES.md) and the informational notes beside min_psr and the Monte Carlo drawdown gate are always reported but never affect the verdict at all. A verdict is not evidence of edge; it states which tests the result survived._

## Headline vs. benchmark
| Metric | Net | Gross | Note |
|---|---|---|---|
| CAGR | 17.66% | 18.42% |  |
| Annualized volatility (net) | 18.45% |  |  |
| Sharpe (net) | 0.98 |  |  |
| Sortino (net) | 1.70 |  | Sharpe: pandas ddof=1 (sample std), annualized by sqrt(periods_per_year). Sortino: target return 0, FULL-SAMPLE N at ddof=0 (not losing-periods-only N). The two denominators are on DIFFERENT footings (M05 carried item 8) - do not compare them via their raw values alone. |
| Max drawdown (net) | -23.25% |  |  |
| Calmar (net) | 0.76 |  |  |
| Hit rate | 62.43% |  |  |
| Mean turnover | 27.01% |  |  |
| Cost drag (CAGR impact) | 0.76% |  |  |
| Benchmark CAGR | 14.81% |  |  |
| Benchmark Sharpe | 1.06 |  |  |
beta 1.13  |  information ratio 0.33  |  tracking error 9.53%  (overlap: 173 periods)


## Trust panel

**Coverage bound: 28.37%** - worst sampled rebalance-date year, % of point-in-time members with no cached history or masked before that date; a ceiling on invisibility, not a return impact.

forced exits, extreme-return exclusions, unscored and dropped tickers are SEPARATE selection effects from the coverage bound above - they are not additive into one headline number (carried M04 verdict item 4).

coverage bound 28.4% (worst sampled year's uncached/masked universe fraction) - this bound and the unscored-ticker / dropped-ticker counts reported separately below are SEPARATE selection effects, not additive into one headline number

| | |
|---|---|
| Forced exits (delisting) | 1 |
| Extreme-return exclusions, long book | 0 |
| Extreme-return exclusions, short book | 0 |
| Rebalance dates with unscored names | 173 |
| Rebalance dates with data-availability drops | 0 |

this run's data_semantics_version (m09) is at or after M04b: this count is strategy-self-reported and genuinely means 'could not be scored'.
### Known caveats
- Yahoo symbol reuse erases delisted history; 42 historical constituent(s) in this run's tracked universe were quarantined because their cached price series belongs to a DIFFERENT, later company now trading under the same symbol (data/quality.py's scan_price_cache) - see provenance.quarantined_tickers.
- 162 ticker(s) in this run's tracked universe have NEVER been visited by `quantlab data scan` - their quarantine status is unknown, not confirmed-clean; run `quantlab data scan` before trusting the quarantined count above as complete. See provenance.never_scanned_tickers.
- 162 ticker(s) in this run's tracked universe are currently suppressed by an ACTIVE negative-cache 'no_data' sidecar (TTL 30 days) - the same config run again after the TTL lapses could see a DIFFERENT set of tickers. See provenance.retry_after_days and provenance.no_data_suppressed_tickers.
- Purged/embargoed CV needs both a purge and an embargo because a contiguous test fold can sit in the MIDDLE of the series with training data on both sides, so a training row's own label window can overlap the test fold from either direction; the walk-forward check (validation/walk_forward.py) needs neither, because its weight choice is made from a STRICTLY PRIOR training block and applied only to the STRICTLY SUBSEQUENT, not-yet-realized test block - there is no way for the test block's own returns to leak backward into that choice.
- n_trials for this family may double-count the strategy's own headline run against a sensitivity grid's base point at the same parameters - the two use independent id schemes and the registry does not reconcile them (registry.py's module docstring). This over-counts N by one trial; unlike an earlier version of this note claimed, over-counting N is NOT generally conservative for DSR once var_sr_trials is estimated from the same trial set (quant-gate VERDICT.md M06 cycle-1 finding 1) - it is disclosed here because it is a small, one-trial effect, not because its direction is guaranteed safe.
- subperiod_oof_sharpe (mean Sharpe over contiguous sub-periods) is a consistency check on a FIXED-PARAMETER strategy, not a purged cross-validation: no model is refit per fold, so purge/embargo cannot change its value (quant-gate VERDICT.md M06 cycle-1 finding 4) - purged_kfold_splits itself remains correct and is kept for a future fitted strategy.
- at least one trial counted toward this family's N (or its dispersion estimate) was recorded from a dirty (uncommitted-changes) working tree - see the provenance section's dirty trial count.

## Validation badges
N trials (distinct): **10** (raw key count: 10, 10 dirty) · PSR 0.9998 · DSR 0.9799 · min track-record length unbounded (n/a)

Reality Check: Reality Check did not run - see the reality_check_pvalue gate's own reason.

Hansen SPA: Hansen SPA did not run - see the spa_pvalue gate's own reason.

RC/SPA benchmark: embedded (result.benchmark_returns) - validation.yaml default · headline's own retained fraction: 100.00%

Monte Carlo: CAGR p5/p50/p95: 10.66% / 16.81% / 25.48%  |  Max drawdown p5/p50/p95: -36.36% / -23.32% / -15.99%  |  Sharpe p5/p50/p95: 0.63 / 0.96 / 1.33  |  observed max drawdown: -23.25% (500 resamples, block_len=6.0).

Capacity: spread percentiles: p10=7.4bps, p25=14.4bps, p50=20.5bps, p75=26.0bps, p90=33.1bps, p99=50.4bps  |  AUM ceiling range: $79,591,755 - $249,754,854 across 4 liquidity assumption(s), 440 ticker(s). For scale only, NOT the output of this run: the old repo capacity estimate on real 2012-2026 S&P 500 data was $95,000,000-$335,000,000 AUM, under an assumed 50-name book (1/50 position_frac).

| Gate | Kind | Value | Threshold | Result | Reason |
|---|---|---|---|---|---|
| deflated_sharpe_ratio | hard | 0.9799 | 0.9500 | PASS | DSR=0.9799 against the 0.95 bar for significance after correcting for N=10 distinct trials (computed on the PER-PERIOD Sharpe 0.2824, not the annualized 0.98 - see deflated_sharpe.py's 'same footing' contract). DSR is not monotone in N above the variance floor; near-duplicate reruns of one grid point can move it. |
| reality_check_pvalue | hard | n/a (could not be computed) | 0.1000 | FAIL | Reality Check could not be run: fewer than 2 registered trials in this family have a stored return series - treated as a FAILURE, not a pass by default. |
| net_sharpe_vs_benchmark | hard | 0.9783 | 1.0583 | FAIL | net Sharpe 0.98 vs benchmark Sharpe 1.06. |
| coverage_bound | hard | 28.3702 | 15.0000 | FAIL | worst-year coverage bound 28.4% against the 15.0% ceiling. |
| min_track_record_length | hard | unbounded (n/a) | 173.0000 | FAIL | needs >= unbounded observations for significance; 173 are available (computed on the PER-PERIOD Sharpe 0.2824, not the annualized 0.98). |
| probabilistic_sharpe_ratio | soft | 0.9998 | 0.9500 | PASS | PSR=0.9998 against the 0.95 bar (computed on the PER-PERIOD Sharpe 0.2824, not the annualized 0.98). min_psr 0.95 binds only below an annualised Sharpe of about 0.47 on a 12-year monthly book - neither is evidence of quality. |
| subperiod_oof_sharpe | soft | 1.0194 | 0.0000 | PASS | mean Sharpe 1.02 over 5 contiguous sub-periods of a strategy with NO FITTED PARAMETERS - purge/embargo have no effect on this value by construction (quant-gate VERDICT.md M06 cycle-1 finding 4); NOT a purged cross-validation. |
| no_cliff_score | soft | 0.9595 | 0.5000 | PASS | no_cliff_score=0.9595 against 0.50 (neighbourhood_size=9, neighbourhood_truncated=False, nan_points=0) - a RELATIVE-SPREAD statistic only, never evidence of quality by itself (see min_net_sharpe below). |
| min_net_sharpe | soft | 0.9783 | 0.3000 | PASS | net Sharpe 0.98 against 0.30 - gated ALONGSIDE no_cliff_score per the M05 carried item (a flat-but-bad neighbourhood must not pass on no_cliff_score alone). Sensitivity grid: (neighbourhood_size=9, neighbourhood_truncated=False, nan_points=0). |
| max_drawdown_floor | soft | -0.2325 | -0.5000 | PASS | FULL-SAMPLE net max drawdown -23.25% against the -50.00% floor (never a rolling column - see max_negative_rolling_window_fraction below for that). |
| max_negative_rolling_window_fraction | soft | 0.0000 | 0.5000 | PASS | 0% of rolling windows had negative CAGR against the 50% bar - computed from the FROZEN ported rolling_window_metrics table, whose CAGR is blind to each window's own first return (ported convention, see rolling.py's module docstring). |
| monte_carlo_drawdown | soft | 0.5120 | 0.5000 | FAIL | P(bootstrap drawdown worse than observed)=0.51. the Monte Carlo drawdown gate sits at the centre of its own statistic's null - neither is evidence of quality. |
| spa_pvalue | soft | n/a (could not be computed) | 0.1000 | FAIL | SPA could not be run (fewer than 2 registered trials with a stored return series) - treated as a FAILURE, not a pass by default. |
| walk_forward_stability | soft | n/a (could not be computed) | 0.5000 | PASS | no walk-forward result was supplied - vacuously satisfied per 'if present'. |
| capacity_ceiling | informational | 79591.7546 | 100.0000 | PASS | worst-case capacity ceiling is 79592x the resolved intended capital ($1,000, configs/validation.yaml intended_capital_usd) against the 100x bar. NOTE: the capacity gate is trivially passable at this stake (79592x against a 100x bar) - this is not evidence of edge, only that the resolved intended capital is small relative to the instrument's liquidity. |
`informational` gates are always reported (value, threshold, result) but never affect the verdict above - see the verdict legend.

## Robustness
### Rolling 3y window

ported convention: each window's first return is omitted from CAGR and hidden from drawdown (M05 carried item; frozen under CLAUDE.md invariant #4 - see validation/rolling.py's module docstring).
 Showing first/last 5 of 138 rows.
| Window end | CAGR | Vol | Sharpe | Max DD |
|---|---|---|---|---|
| 2015-01-30 | 19.35% | 11.91% | 1.64 | -7.60% |
| 2015-02-27 | 20.41% | 12.10% | 1.66 | -7.60% |
| 2015-03-31 | 19.20% | 12.10% | 1.55 | -7.60% |
| 2015-04-30 | 20.90% | 12.46% | 1.34 | -4.12% |
| 2015-05-29 | 22.60% | 11.40% | 1.82 | -4.12% |
| ... |  |  |  |  |
| 2026-02-27 | 29.72% | 19.06% | 1.49 | -15.99% |
| 2026-03-31 | 26.64% | 19.68% | 1.28 | -15.99% |
| 2026-04-30 | 33.70% | 22.36% | 1.43 | -15.99% |
| 2026-05-29 | 35.98% | 22.87% | 1.51 | -15.99% |
| 2026-06-30 | 39.76% | 23.25% | 1.56 | -15.99% |
### Rolling 5y window

ported convention: each window's first return is omitted from CAGR and hidden from drawdown (M05 carried item; frozen under CLAUDE.md invariant #4 - see validation/rolling.py's module docstring).
 Showing first/last 5 of 114 rows.
| Window end | CAGR | Vol | Sharpe | Max DD |
|---|---|---|---|---|
| 2017-01-31 | 13.68% | 12.66% | 1.13 | -8.99% |
| 2017-02-28 | 13.07% | 12.57% | 1.08 | -8.99% |
| 2017-03-31 | 12.48% | 12.53% | 1.03 | -8.99% |
| 2017-04-28 | 14.18% | 12.54% | 0.98 | -8.99% |
| 2017-05-31 | 14.93% | 11.97% | 1.22 | -8.99% |
| ... |  |  |  |  |
| 2026-02-27 | 19.84% | 20.46% | 0.97 | -15.99% |
| 2026-03-31 | 17.11% | 20.74% | 0.90 | -15.99% |
| 2026-04-30 | 21.22% | 22.38% | 0.98 | -15.99% |
| 2026-05-29 | 23.40% | 22.74% | 1.04 | -15.99% |
| 2026-06-30 | 26.34% | 23.07% | 1.10 | -15.99% |

### Sub-period / regime table

| Period | CAGR | Vol | Sharpe | Max DD | Growth |
|---|---|---|---|---|---|
| first_half | 12.91% | 14.17% | 0.93 | -22.86% | 2.3844 |
| second_half | 22.54% | 21.87% | 1.04 | -21.68% | 4.3702 |
| precovid_2012_2019 | 12.74% | 13.74% | 0.95 | -22.86% | 2.5828 |
| covid_2020 | 17.78% | 27.93% | 0.72 | -21.68% | 1.1782 |
| rate_shock_2021_2022 | 5.20% | 21.89% | 0.34 | -15.89% | 1.1066 |
| recent_2023_plus | 38.10% | 21.94% | 1.59 | -15.99% | 3.0944 |

### Parameter sensitivity

no_cliff_score = **0.9595** (neighbourhood_size=9, neighbourhood_truncated=False, nan_points=0) - shown ONLY beside min_net_sharpe below.

no_cliff_score=0.9595 against 0.50 (neighbourhood_size=9, neighbourhood_truncated=False, nan_points=0) - a RELATIVE-SPREAD statistic only, never evidence of quality by itself (see min_net_sharpe below).

net Sharpe 0.98 against 0.30 - gated ALONGSIDE no_cliff_score per the M05 carried item (a flat-but-bad neighbourhood must not pass on no_cliff_score alone). Sensitivity grid: (neighbourhood_size=9, neighbourhood_truncated=False, nan_points=0).

Base point: **lookback_months=12, n_long=50**

| Grid point | Net Sharpe |
|---|---|
| lookback_months=9, n_long=30 | 0.98 |
| lookback_months=9, n_long=50 | 0.99 |
| lookback_months=9, n_long=70 | 0.98 |
| lookback_months=12, n_long=30 | 0.99 |
| lookback_months=12, n_long=50 (base point) | 0.99 |
| lookback_months=12, n_long=70 | 1.00 |
| lookback_months=15, n_long=30 | 0.97 |
| lookback_months=15, n_long=50 | 0.97 |
| lookback_months=15, n_long=70 | 1.01 |




### Flags
- 1 forced exit(s) booked at last available price (delisting)
- 173 rebalance date(s) had declared-universe tickers left unscored (unpriceable) and dropped from weights
- benchmark Sharpe exceeds strategy Sharpe

## Execution conventions

| | |
|---|---|
| Execution mode | close - close = same-session close (the decision date's own close price). |
| Cost model | flat_bps (10.0 bps one-way) |
| Borrow fee (annual) | 30.0 bps |
| Corwin-Schultz lookback | 60 days |
| Delisting haircut | 0.00% |
| Extreme-return policy | exclude_legacy (bound 3.00x) |
| Filing lag | n/a (strategy has no filing-lag parameter) session(s) |
| Max dropped fraction (abort threshold) | 5.00% |
| Abort on unscoreable date | True |

## Provenance appendix

| | |
|---|---|
| Strategy id | `momentum-2b2c9fd50a` |
| Strategy params | `{'book': 'long_only', 'n_long': 30, 'n_short': 30, 'lookback_months': 12, 'skip_months': 1}` |
| Backtest config | `{'start': '2012-01-01T00:00:00', 'end': '2026-06-30T00:00:00', 'strategy_config': 'C:\\Users\\arwga\\Developer\\ClaudeProjects\\Trading\\quantlab\\configs\\strategies\\momentum_12_1.yaml', 'rebalance_freq': 'month_end', 'initial_capital': 1000000.0, 'execution': 'close', 'cost_model': 'flat_bps', 'one_way_cost_bps': 10.0, 'corwin_schultz_lookback_days': 60, 'borrow_fee_annual_bps': 30.0, 'delisting_haircut': 0.0, 'extreme_return_bound': 3.0, 'extreme_return_policy': 'exclude_legacy', 'benchmark': 'SPY', 'max_dropped_fraction': 0.05, 'abort_on_unscoreable': True}` |
| Providers | `{'prices': 'YFinancePriceProvider', 'constituents': 'SP500CommunityConstituentsProvider', 'fundamentals': 'EdgarFundamentalsProvider', 'corporate_actions': 'YFinanceCorporateActionsProvider'}` |
| Actions-cache fetched_at range | 2026-09-11 - 2026-09-11 |
| Cache dir | n/a (not recorded in the provenance for this run) |
| Run seconds | 749.80 |
| Quarantined tickers | 42 |
| Masked-start tickers | 0 |
| quantlab version | 0.1.0 |