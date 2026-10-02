# QuantLab report - blend-153a7466bc

**Verdict: REJECTED**
`blend-153a7466bc` · data semantics `m09` · run 2026-10-01T16:09:57.728818+00:00 · git `dc5356d7c0fa02929ea4d8d1c6144083dbdcae70` · quantlab 0.1.0

net CAGR 17.67%, Sharpe 1.03, max drawdown -28.36% - verdict REJECTED.

_REJECTED: at least one HARD gate failed. RESEARCH_ONLY: every hard gate passed but at least one SOFT gate failed. ELIGIBLE_FOR_PAPER: every hard and soft gate passed. Hard-gate failures cap the verdict at REJECTED; soft-gate failures cap it at RESEARCH_ONLY; gates of kind INFORMATIONAL (capacity, at Alex's retail stake - orchestrator decision, plans/QUANT-NOTES.md) and the informational notes beside min_psr and the Monte Carlo drawdown gate are always reported but never affect the verdict at all. A verdict is not evidence of edge; it states which tests the result survived._

## Headline vs. benchmark
| Metric | Net | Gross | Note |
|---|---|---|---|
| CAGR | 17.67% | 18.22% |  |
| Annualized volatility (net) | 17.36% |  |  |
| Sharpe (net) | 1.03 |  |  |
| Sortino (net) | 1.67 |  | Sharpe: pandas ddof=1 (sample std), annualized by sqrt(periods_per_year). Sortino: target return 0, FULL-SAMPLE N at ddof=0 (not losing-periods-only N). The two denominators are on DIFFERENT footings (M05 carried item 8) - do not compare them via their raw values alone. |
| Max drawdown (net) | -28.36% |  |  |
| Calmar (net) | 0.62 |  |  |
| Hit rate | 65.90% |  |  |
| Mean turnover | 19.46% |  |  |
| Cost drag (CAGR impact) | 0.55% |  |  |
| Benchmark CAGR | 14.81% |  |  |
| Benchmark Sharpe | 1.06 |  |  |
beta 1.16  |  information ratio 0.48  |  tracking error 6.34%  (overlap: 173 periods)


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
- TTM EPS is restated PER-COMPONENT (M09, data/pit.py's fundamentals() restatement using data/providers/edgar_fundamentals.py's ttm_eps_components): a split falling BETWEEN two component filings no longer leaves the sum in mixed share terms (closing plans/QUANT-NOTES.md 'From M03b verdict' item 1 - was bounded to the P/E leg, adverse direction, up to 2.5x on the gate's own straddling-split fixture). A narrower residual remains when a fundamentals provider supplies no per-component data at all (falls back to the pre-M09 single-filed-date restatement) or a filer's own reporting convention does not follow the modelled quarter/annual duration windows; treat any value/blend result touching ttm_eps with this narrower caveat in mind.
- Yahoo symbol reuse erases delisted history; 36 historical constituent(s) in this run's tracked universe were quarantined because their cached price series belongs to a DIFFERENT, later company now trading under the same symbol (data/quality.py's scan_price_cache) - see provenance.quarantined_tickers.
- 168 ticker(s) in this run's tracked universe have NEVER been visited by `quantlab data scan` - their quarantine status is unknown, not confirmed-clean; run `quantlab data scan` before trusting the quarantined count above as complete. See provenance.never_scanned_tickers.
- 168 ticker(s) in this run's tracked universe are currently suppressed by an ACTIVE negative-cache 'no_data' sidecar (TTL 30 days) - the same config run again after the TTL lapses could see a DIFFERENT set of tickers. See provenance.retry_after_days and provenance.no_data_suppressed_tickers.
- Purged/embargoed CV needs both a purge and an embargo because a contiguous test fold can sit in the MIDDLE of the series with training data on both sides, so a training row's own label window can overlap the test fold from either direction; the walk-forward check (validation/walk_forward.py) needs neither, because its weight choice is made from a STRICTLY PRIOR training block and applied only to the STRICTLY SUBSEQUENT, not-yet-realized test block - there is no way for the test block's own returns to leak backward into that choice.
- n_trials for this family may double-count the strategy's own headline run against a sensitivity grid's base point at the same parameters - the two use independent id schemes and the registry does not reconcile them (registry.py's module docstring). This over-counts N by one trial; unlike an earlier version of this note claimed, over-counting N is NOT generally conservative for DSR once var_sr_trials is estimated from the same trial set (quant-gate VERDICT.md M06 cycle-1 finding 1) - it is disclosed here because it is a small, one-trial effect, not because its direction is guaranteed safe.
- subperiod_oof_sharpe (mean Sharpe over contiguous sub-periods) is a consistency check on a FIXED-PARAMETER strategy, not a purged cross-validation: no model is refit per fold, so purge/embargo cannot change its value (quant-gate VERDICT.md M06 cycle-1 finding 4) - purged_kfold_splits itself remains correct and is kept for a future fitted strategy.
- Walk-forward Sharpe ranking checked against the real engine's netted-book costing at the same 5 grid points (M09): Kendall tau=1.0000, top choice AGREES between the two cost conventions.
- Verified (M09, WalkForwardResult.training_sharpes): no chosen walk-forward step had a NaN training Sharpe - the NaN-seeded-tie-break hazard described in walk_forward.py's module docstring did not fire on this result.

## Validation badges
N trials (distinct): **8** (raw key count: 8, 0 dirty) · PSR 0.9997 · DSR 0.9849 · min track-record length unbounded (n/a)

Reality Check: K=3 realised trials over n_periods=173 common periods, B=200 bootstrap resamples, block_len=6.0. measured size ≈ 0.12 at the 0.10 bar (block length 6.0); treat the bar as approximate.

Hansen SPA: K=3 realised trials over n_periods=173 common periods, B=200 bootstrap resamples, block_len=6.0. measured size ≈ 0.12 at the 0.10 bar (block length 6.0); treat the bar as approximate.

RC/SPA benchmark: embedded (result.benchmark_returns) - validation.yaml default · headline's own retained fraction: 100.00%

Monte Carlo: CAGR p5/p50/p95: 10.95% / 17.41% / 23.71%  |  Max drawdown p5/p50/p95: -39.26% / -28.36% / -16.19%  |  Sharpe p5/p50/p95: 0.63 / 1.05 / 1.47  |  observed max drawdown: -28.36% (500 resamples, block_len=6.0).

Capacity: spread percentiles: p10=8.2bps, p25=14.4bps, p50=20.4bps, p75=26.0bps, p90=33.0bps, p99=48.1bps  |  AUM ceiling range: $153,318,114 - $475,575,573 across 4 liquidity assumption(s), 483 ticker(s). For scale only, NOT the output of this run: the old repo capacity estimate on real 2012-2026 S&P 500 data was $95,000,000-$335,000,000 AUM, under an assumed 50-name book (1/50 position_frac).

| Gate | Kind | Value | Threshold | Result | Reason |
|---|---|---|---|---|---|
| deflated_sharpe_ratio | hard | 0.9849 | 0.9500 | PASS | DSR=0.9849 against the 0.95 bar for significance after correcting for N=8 distinct trials (computed on the PER-PERIOD Sharpe 0.2976, not the annualized 1.03 - see deflated_sharpe.py's 'same footing' contract). DSR is not monotone in N above the variance floor; near-duplicate reruns of one grid point can move it. |
| reality_check_pvalue | hard | 0.1045 | 0.1000 | FAIL | White Reality Check p=0.1045 against the 0.10 bar, over K=3 realised trials, benchmark=embedded (result.benchmark_returns) - validation.yaml default. |
| net_sharpe_vs_benchmark | hard | 1.0310 | 1.0583 | FAIL | net Sharpe 1.03 vs benchmark Sharpe 1.06. |
| coverage_bound | hard | 28.3702 | 15.0000 | FAIL | worst-year coverage bound 28.4% against the 15.0% ceiling. |
| min_track_record_length | hard | unbounded (n/a) | 173.0000 | FAIL | needs >= unbounded observations for significance; 173 are available (computed on the PER-PERIOD Sharpe 0.2976, not the annualized 1.03). |
| probabilistic_sharpe_ratio | soft | 0.9997 | 0.9500 | PASS | PSR=0.9997 against the 0.95 bar (computed on the PER-PERIOD Sharpe 0.2976, not the annualized 1.03). min_psr 0.95 binds only below an annualised Sharpe of about 0.47 on a 12-year monthly book - neither is evidence of quality. |
| subperiod_oof_sharpe | soft | 1.1740 | 0.0000 | PASS | mean Sharpe 1.17 over 5 contiguous sub-periods of a strategy with NO FITTED PARAMETERS - purge/embargo have no effect on this value by construction (quant-gate VERDICT.md M06 cycle-1 finding 4); NOT a purged cross-validation. |
| no_cliff_score | soft | n/a (could not be computed) | 0.5000 | FAIL | no sensitivity grid was supplied - treated as a FAILURE, not a pass by default. |
| min_net_sharpe | soft | 1.0310 | 0.3000 | PASS | net Sharpe 1.03 against 0.30 - gated ALONGSIDE no_cliff_score per the M05 carried item (a flat-but-bad neighbourhood must not pass on no_cliff_score alone). |
| max_drawdown_floor | soft | -0.2836 | -0.5000 | PASS | FULL-SAMPLE net max drawdown -28.36% against the -50.00% floor (never a rolling column - see max_negative_rolling_window_fraction below for that). |
| max_negative_rolling_window_fraction | soft | 0.0000 | 0.5000 | PASS | 0% of rolling windows had negative CAGR against the 50% bar - computed from the FROZEN ported rolling_window_metrics table, whose CAGR is blind to each window's own first return (ported convention, see rolling.py's module docstring). |
| monte_carlo_drawdown | soft | 0.3720 | 0.5000 | PASS | P(bootstrap drawdown worse than observed)=0.37. the Monte Carlo drawdown gate sits at the centre of its own statistic's null - neither is evidence of quality. |
| spa_pvalue | soft | 0.0796 | 0.1000 | PASS | Hansen SPA p=0.0796 against the 0.10 bar, over K=3 realised trials, benchmark=embedded (result.benchmark_returns) - validation.yaml default. |
| walk_forward_stability | soft | 0.7000 | 0.5000 | PASS | walk-forward chose the modal weight tuple in 70% of steps against the 50% bar. |
| capacity_ceiling | informational | 153318.1139 | 100.0000 | PASS | worst-case capacity ceiling is 153318x the resolved intended capital ($1,000, configs/validation.yaml intended_capital_usd) against the 100x bar. NOTE: the capacity gate is trivially passable at this stake (153318x against a 100x bar) - this is not evidence of edge, only that the resolved intended capital is small relative to the instrument's liquidity. |
`informational` gates are always reported (value, threshold, result) but never affect the verdict above - see the verdict legend.

## Robustness
### Rolling 3y window

ported convention: each window's first return is omitted from CAGR and hidden from drawdown (M05 carried item; frozen under CLAUDE.md invariant #4 - see validation/rolling.py's module docstring).
 Showing first/last 5 of 138 rows.
| Window end | CAGR | Vol | Sharpe | Max DD |
|---|---|---|---|---|
| 2015-01-30 | 20.32% | 11.41% | 1.79 | -8.38% |
| 2015-02-27 | 21.60% | 11.66% | 1.81 | -8.38% |
| 2015-03-31 | 20.82% | 11.69% | 1.67 | -8.38% |
| 2015-04-30 | 23.89% | 11.82% | 1.58 | -2.68% |
| 2015-05-29 | 24.21% | 10.31% | 2.21 | -2.68% |
| ... |  |  |  |  |
| 2026-02-27 | 25.39% | 15.36% | 1.54 | -12.51% |
| 2026-03-31 | 23.51% | 15.74% | 1.40 | -12.51% |
| 2026-04-30 | 29.35% | 16.99% | 1.55 | -12.51% |
| 2026-05-29 | 28.29% | 16.95% | 1.66 | -12.51% |
| 2026-06-30 | 28.99% | 16.90% | 1.66 | -12.51% |
### Rolling 5y window

ported convention: each window's first return is omitted from CAGR and hidden from drawdown (M05 carried item; frozen under CLAUDE.md invariant #4 - see validation/rolling.py's module docstring).
 Showing first/last 5 of 114 rows.
| Window end | CAGR | Vol | Sharpe | Max DD |
|---|---|---|---|---|
| 2017-01-31 | 16.34% | 11.97% | 1.39 | -8.38% |
| 2017-02-28 | 16.13% | 11.88% | 1.37 | -8.38% |
| 2017-03-31 | 16.06% | 11.83% | 1.32 | -8.38% |
| 2017-04-28 | 18.28% | 11.84% | 1.31 | -8.29% |
| 2017-05-31 | 18.16% | 11.01% | 1.61 | -8.29% |
| ... |  |  |  |  |
| 2026-02-27 | 17.13% | 19.13% | 0.95 | -23.25% |
| 2026-03-31 | 14.81% | 19.25% | 0.86 | -23.25% |
| 2026-04-30 | 17.25% | 19.86% | 0.91 | -23.25% |
| 2026-05-29 | 18.13% | 19.91% | 0.94 | -23.25% |
| 2026-06-30 | 19.56% | 20.05% | 0.99 | -23.25% |

### Sub-period / regime table

| Period | CAGR | Vol | Sharpe | Max DD | Growth |
|---|---|---|---|---|---|
| first_half | 15.96% | 12.79% | 1.23 | -18.57% | 2.8853 |
| second_half | 19.39% | 20.97% | 0.96 | -28.36% | 3.6174 |
| precovid_2012_2019 | 16.25% | 12.83% | 1.24 | -18.57% | 3.2937 |
| covid_2020 | 10.95% | 33.18% | 0.47 | -28.36% | 1.1097 |
| rate_shock_2021_2022 | 5.91% | 22.69% | 0.36 | -23.25% | 1.1214 |
| recent_2023_plus | 30.62% | 16.94% | 1.67 | -12.51% | 2.5464 |


### Walk-forward (blend weight honesty check)

Purged/embargoed CV needs both a purge and an embargo because a contiguous test fold can sit in the MIDDLE of the series with training data on both sides, so a training row's own label window can overlap the test fold from either direction; the walk-forward check needs neither, because its weight choice is made from a STRICTLY PRIOR training block and applied only to the STRICTLY SUBSEQUENT, not-yet-realized test block - there is no way for the test block's own returns to leak backward into that choice.

ranking agreement under both cost conventions (M09): Kendall tau=1.0000 over 5 grid points - top choice AGREES between blend-of-net-returns and the engine's netted-book costing. Both conventions measured on the walk-forward out-of-sample window (2017-02-28 to 2026-06-30, 113 periods, 12/year). Netted-book inputs: 1/0 = momentum-2b2c9fd50a (standalone child run, C:\Users\arwga\Developer\ClaudeProjects\Trading\quantlab\reports\momentum_12_1, Sharpe 0.957); 0.75/0.25 = blend-a7f7c30ce1 (netted blend backtest, C:\Users\arwga\Developer\ClaudeProjects\Trading\quantlab\reports\netted_grid\blend_75_25, Sharpe 0.967); 0.5/0.5 = blend-153a7466bc (netted blend backtest, C:\Users\arwga\Developer\ClaudeProjects\Trading\quantlab\reports\blend_50_50, Sharpe 0.943); 0.25/0.75 = blend-9231a3894e (netted blend backtest, C:\Users\arwga\Developer\ClaudeProjects\Trading\quantlab\reports\netted_grid\blend_25_75, Sharpe 0.884); 0/1 = value_composite-b6fdfec048 (standalone child run, C:\Users\arwga\Developer\ClaudeProjects\Trading\quantlab\reports\value_composite, Sharpe 0.801).

per-step training Sharpes are NOT retained on WalkForwardResult, so whether any CHOSEN step had a NaN training Sharpe (which would lock in the first grid weight regardless of the others) cannot be verified here - open item, carried to whoever next touches validation/walk_forward.py; this report does not fabricate the missing figures.

walk-forward chose the modal weight tuple in 70% of steps against the 50% bar.

#### Chosen weight per step

| Step date | momentum_12_1 | value_composite |
|---|---|---|
| 2017-02-28 | 0.00 | 1.00 |
| 2018-02-28 | 0.00 | 1.00 |
| 2019-02-28 | 0.00 | 1.00 |
| 2020-02-28 | 0.00 | 1.00 |
| 2021-02-26 | 0.00 | 1.00 |
| 2022-02-28 | 0.00 | 1.00 |
| 2023-02-28 | 0.00 | 1.00 |
| 2024-02-29 | 0.75 | 0.25 |
| 2025-02-28 | 1.00 | 0.00 |
| 2026-02-27 | 0.75 | 0.25 |

ported convention: each window's first return is omitted from CAGR and hidden from drawdown (M05 carried item; frozen under CLAUDE.md invariant #4 - see validation/rolling.py's module docstring).

| Grid point | CAGR | Vol | Sharpe | Max DD |
|---|---|---|---|---|
| Walk-Forward | 20.25% | 22.81% | 0.94 | -34.75% |
| Fixed 100% momentum_12_1/0% value_composite | 19.47% | 20.91% | 0.96 | -23.25% |
| Fixed 75% momentum_12_1/25% value_composite | 18.70% | 19.93% | 0.97 | -25.05% |
| Fixed 50% momentum_12_1/50% value_composite | 17.76% | 19.67% | 0.94 | -28.36% |
| Fixed 25% momentum_12_1/75% value_composite | 16.66% | 20.16% | 0.88 | -31.59% |
| Fixed 0% momentum_12_1/100% value_composite | 15.41% | 21.34% | 0.80 | -34.75% |



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
| Strategy id | `blend-153a7466bc` |
| Strategy params | `{'children': [{'params': {'book': 'long_only', 'lookback_months': 12, 'n_long': 30, 'skip_months': 1}, 'strategy': 'momentum', 'weight': 0.5}, {'params': {'filing_lag_sessions': 1, 'n_holdings': 30}, 'strategy': 'value_composite', 'weight': 0.5}]}` |
| Backtest config | `{'abort_on_unscoreable': True, 'benchmark': 'SPY', 'borrow_fee_annual_bps': 30.0, 'corwin_schultz_lookback_days': 60, 'cost_model': 'flat_bps', 'delisting_haircut': 0.0, 'end': '2026-06-30T00:00:00', 'execution': 'close', 'extreme_return_bound': 3.0, 'extreme_return_policy': 'exclude_legacy', 'initial_capital': 1000000.0, 'max_dropped_fraction': 0.05, 'one_way_cost_bps': 10.0, 'rebalance_freq': 'month_end', 'start': '2012-01-01T00:00:00', 'strategy_config': 'C:\\Users\\arwga\\Developer\\ClaudeProjects\\Trading\\quantlab\\configs\\strategies\\blend_50_50.yaml'}` |
| Providers | `{'constituents': 'SP500CommunityConstituentsProvider', 'corporate_actions': 'YFinanceCorporateActionsProvider', 'fundamentals': 'EdgarFundamentalsProvider', 'prices': 'YFinancePriceProvider'}` |
| Actions-cache fetched_at range | 2026-09-13 - 2026-09-13 |
| Cache dir | n/a (not recorded in the provenance for this run) |
| Run seconds | 25352.39 |
| Quarantined tickers | 36 |
| Masked-start tickers | 0 |
| quantlab version | 0.1.0 |