# QuantLab report - value_composite-b6fdfec048

**Verdict: REJECTED** **DIRTY TREE**
`value_composite-b6fdfec048` · data semantics `m09` · run 2026-09-13T18:07:05.660529+00:00 · git `395bd9894b720d2408df854290106e345bf33983` · quantlab 0.1.0

net CAGR 17.63%, Sharpe 0.97, max drawdown -34.76% - verdict REJECTED.

_REJECTED: at least one HARD gate failed. RESEARCH_ONLY: every hard gate passed but at least one SOFT gate failed. ELIGIBLE_FOR_PAPER: every hard and soft gate passed. Hard-gate failures cap the verdict at REJECTED; soft-gate failures cap it at RESEARCH_ONLY; gates of kind INFORMATIONAL (capacity, at Alex's retail stake - orchestrator decision, plans/QUANT-NOTES.md) and the informational notes beside min_psr and the Monte Carlo drawdown gate are always reported but never affect the verdict at all. A verdict is not evidence of edge; it states which tests the result survived._

## Headline vs. benchmark
| Metric | Net | Gross | Note |
|---|---|---|---|
| CAGR | 17.63% | 17.97% |  |
| Annualized volatility (net) | 18.56% |  |  |
| Sharpe (net) | 0.97 |  |  |
| Sortino (net) | 1.55 |  | Sharpe: pandas ddof=1 (sample std), annualized by sqrt(periods_per_year). Sortino: target return 0, FULL-SAMPLE N at ddof=0 (not losing-periods-only N). The two denominators are on DIFFERENT footings (M05 carried item 8) - do not compare them via their raw values alone. |
| Max drawdown (net) | -34.76% |  |  |
| Calmar (net) | 0.51 |  |  |
| Hit rate | 67.63% |  |  |
| Mean turnover | 12.14% |  |  |
| Cost drag (CAGR impact) | 0.34% |  |  |
| Benchmark CAGR | 14.81% |  |  |
| Benchmark Sharpe | 1.06 |  |  |
beta 1.19  |  information ratio 0.38  |  tracking error 8.51%  (overlap: 173 periods)


## Trust panel

**Coverage bound: 27.97%** - worst sampled rebalance-date year, % of point-in-time members with no cached history or masked before that date; a ceiling on invisibility, not a return impact.

forced exits, extreme-return exclusions, unscored and dropped tickers are SEPARATE selection effects from the coverage bound above - they are not additive into one headline number (carried M04 verdict item 4).

coverage bound 28.0% (worst sampled year's uncached/masked universe fraction) - this bound and the unscored-ticker / dropped-ticker counts reported separately below are SEPARATE selection effects, not additive into one headline number

| | |
|---|---|
| Forced exits (delisting) | 0 |
| Extreme-return exclusions, long book | 0 |
| Extreme-return exclusions, short book | 0 |
| Rebalance dates with unscored names | 173 |
| Rebalance dates with data-availability drops | 0 |

this run's data_semantics_version (m09) is at or after M04b: this count is strategy-self-reported and genuinely means 'could not be scored'.
### Known caveats
- TTM EPS is restated PER-COMPONENT (M09, data/pit.py's fundamentals() restatement using data/providers/edgar_fundamentals.py's ttm_eps_components): a split falling BETWEEN two component filings no longer leaves the sum in mixed share terms (closing plans/QUANT-NOTES.md 'From M03b verdict' item 1 - was bounded to the P/E leg, adverse direction, up to 2.5x on the gate's own straddling-split fixture). A narrower residual remains when a fundamentals provider supplies no per-component data at all (falls back to the pre-M09 single-filed-date restatement) or a filer's own reporting convention does not follow the modelled quarter/annual duration windows; treat any value/blend result touching ttm_eps with this narrower caveat in mind.
- 27 point-in-time constituent(s) had already joined the index before this run's cached price history for them begins, within this run's own [start, end] window - their early membership span is invisible to every strategy (PriceAvailability.masked_start; counted in the coverage bound above, not a second, separate deduction) - see coverage_report.masked_start_tickers for the per-year breakdown and per-ticker reasons.
- 805 ticker(s) in this run's tracked universe have NEVER been visited by `quantlab data scan` - their quarantine status is unknown, not confirmed-clean; run `quantlab data scan` before trusting the quarantined count above as complete. See provenance.never_scanned_tickers.
- 168 ticker(s) in this run's tracked universe are currently suppressed by an ACTIVE negative-cache 'no_data' sidecar (TTL 30 days) - the same config run again after the TTL lapses could see a DIFFERENT set of tickers. See provenance.retry_after_days and provenance.no_data_suppressed_tickers.
- Purged/embargoed CV needs both a purge and an embargo because a contiguous test fold can sit in the MIDDLE of the series with training data on both sides, so a training row's own label window can overlap the test fold from either direction; the walk-forward check (validation/walk_forward.py) needs neither, because its weight choice is made from a STRICTLY PRIOR training block and applied only to the STRICTLY SUBSEQUENT, not-yet-realized test block - there is no way for the test block's own returns to leak backward into that choice.
- n_trials for this family may double-count the strategy's own headline run against a sensitivity grid's base point at the same parameters - the two use independent id schemes and the registry does not reconcile them (registry.py's module docstring). This over-counts N by one trial; unlike an earlier version of this note claimed, over-counting N is NOT generally conservative for DSR once var_sr_trials is estimated from the same trial set (quant-gate VERDICT.md M06 cycle-1 finding 1) - it is disclosed here because it is a small, one-trial effect, not because its direction is guaranteed safe.
- subperiod_oof_sharpe (mean Sharpe over contiguous sub-periods) is a consistency check on a FIXED-PARAMETER strategy, not a purged cross-validation: no model is refit per fold, so purge/embargo cannot change its value (quant-gate VERDICT.md M06 cycle-1 finding 4) - purged_kfold_splits itself remains correct and is kept for a future fitted strategy.
- at least one trial counted toward this family's N (or its dispersion estimate) was recorded from a dirty (uncommitted-changes) working tree - see the provenance section's dirty trial count.

## Validation badges
N trials (distinct): **1** (raw key count: 1, 1 dirty) · PSR 0.9993 · DSR n/a (registry too thin - fewer than 2 distinct trials) · min track-record length unbounded (n/a)

Reality Check: Reality Check did not run - see the reality_check_pvalue gate's own reason.

Hansen SPA: Hansen SPA did not run - see the spa_pvalue gate's own reason.

RC/SPA benchmark: embedded (result.benchmark_returns) - validation.yaml default · headline's own retained fraction: 100.00%

Monte Carlo: CAGR p5/p50/p95: 10.16% / 17.65% / 24.73%  |  Max drawdown p5/p50/p95: -45.71% / -34.76% / -16.56%  |  Sharpe p5/p50/p95: 0.55 / 1.00 / 1.47  |  observed max drawdown: -34.76% (500 resamples, block_len=6.0).

Capacity: spread percentiles: p10=5.5bps, p25=11.8bps, p50=19.5bps, p75=25.4bps, p90=31.4bps, p99=41.1bps  |  AUM ceiling range: $89,751,248 - $264,962,831 across 4 liquidity assumption(s), 203 ticker(s). For scale only, NOT the output of this run: the old repo capacity estimate on real 2012-2026 S&P 500 data was $95,000,000-$335,000,000 AUM, under an assumed 50-name book (1/50 position_frac).

| Gate | Kind | Value | Threshold | Result | Reason |
|---|---|---|---|---|---|
| deflated_sharpe_ratio | hard | n/a (could not be computed) | 0.9500 | FAIL | DSR could not be computed - fewer than 2 distinct trials are registered for this family (N=1); this is the registry being too thin, NOT a statistical failure - treated as a FAILURE (not a pass) until more genuinely distinct trials are recorded. |
| reality_check_pvalue | hard | n/a (could not be computed) | 0.1000 | FAIL | Reality Check could not be run: fewer than 2 registered trials in this family have a stored return series - treated as a FAILURE, not a pass by default. |
| net_sharpe_vs_benchmark | hard | 0.9747 | 1.0583 | FAIL | net Sharpe 0.97 vs benchmark Sharpe 1.06. |
| coverage_bound | hard | 27.9678 | 15.0000 | FAIL | worst-year coverage bound 28.0% against the 15.0% ceiling. |
| min_track_record_length | hard | unbounded (n/a) | 173.0000 | FAIL | needs >= unbounded observations for significance; 173 are available (computed on the PER-PERIOD Sharpe 0.2814, not the annualized 0.97). |
| probabilistic_sharpe_ratio | soft | 0.9993 | 0.9500 | PASS | PSR=0.9993 against the 0.95 bar (computed on the PER-PERIOD Sharpe 0.2814, not the annualized 0.97). min_psr 0.95 binds only below an annualised Sharpe of about 0.47 on a 12-year monthly book - neither is evidence of quality. |
| subperiod_oof_sharpe | soft | 1.1965 | 0.0000 | PASS | mean Sharpe 1.20 over 5 contiguous sub-periods of a strategy with NO FITTED PARAMETERS - purge/embargo have no effect on this value by construction (quant-gate VERDICT.md M06 cycle-1 finding 4); NOT a purged cross-validation. |
| no_cliff_score | soft | n/a (could not be computed) | 0.5000 | FAIL | no sensitivity grid was supplied - treated as a FAILURE, not a pass by default. |
| min_net_sharpe | soft | 0.9747 | 0.3000 | PASS | net Sharpe 0.97 against 0.30 - gated ALONGSIDE no_cliff_score per the M05 carried item (a flat-but-bad neighbourhood must not pass on no_cliff_score alone). |
| max_drawdown_floor | soft | -0.3476 | -0.5000 | PASS | FULL-SAMPLE net max drawdown -34.76% against the -50.00% floor (never a rolling column - see max_negative_rolling_window_fraction below for that). |
| max_negative_rolling_window_fraction | soft | 0.0072 | 0.5000 | PASS | 1% of rolling windows had negative CAGR against the 50% bar - computed from the FROZEN ported rolling_window_metrics table, whose CAGR is blind to each window's own first return (ported convention, see rolling.py's module docstring). |
| monte_carlo_drawdown | soft | 0.3040 | 0.5000 | PASS | P(bootstrap drawdown worse than observed)=0.30. the Monte Carlo drawdown gate sits at the centre of its own statistic's null - neither is evidence of quality. |
| spa_pvalue | soft | n/a (could not be computed) | 0.1000 | FAIL | SPA could not be run (fewer than 2 registered trials with a stored return series) - treated as a FAILURE, not a pass by default. |
| walk_forward_stability | soft | n/a (could not be computed) | 0.5000 | PASS | no walk-forward result was supplied - vacuously satisfied per 'if present'. |
| capacity_ceiling | informational | 89751.2477 | 100.0000 | PASS | worst-case capacity ceiling is 89751x the resolved intended capital ($1,000, configs/validation.yaml intended_capital_usd) against the 100x bar. NOTE: the capacity gate is trivially passable at this stake (89751x against a 100x bar) - this is not evidence of edge, only that the resolved intended capital is small relative to the instrument's liquidity. |
`informational` gates are always reported (value, threshold, result) but never affect the verdict above - see the verdict legend.

## Robustness
### Rolling 3y window

ported convention: each window's first return is omitted from CAGR and hidden from drawdown (M05 carried item; frozen under CLAUDE.md invariant #4 - see validation/rolling.py's module docstring).
 Showing first/last 5 of 138 rows.
| Window end | CAGR | Vol | Sharpe | Max DD |
|---|---|---|---|---|
| 2015-01-30 | 20.40% | 12.18% | 1.67 | -10.20% |
| 2015-02-27 | 22.09% | 12.58% | 1.71 | -10.20% |
| 2015-03-31 | 21.87% | 12.68% | 1.56 | -9.16% |
| 2015-04-30 | 26.40% | 12.58% | 1.63 | -3.86% |
| 2015-05-29 | 25.69% | 10.83% | 2.27 | -3.86% |
| ... |  |  |  |  |
| 2026-02-27 | 21.20% | 14.85% | 1.31 | -10.34% |
| 2026-03-31 | 20.37% | 14.85% | 1.31 | -10.34% |
| 2026-04-30 | 25.04% | 15.02% | 1.41 | -10.34% |
| 2026-05-29 | 20.77% | 14.54% | 1.55 | -10.34% |
| 2026-06-30 | 18.28% | 13.83% | 1.44 | -10.34% |
### Rolling 5y window

ported convention: each window's first return is omitted from CAGR and hidden from drawdown (M05 carried item; frozen under CLAUDE.md invariant #4 - see validation/rolling.py's module docstring).
 Showing first/last 5 of 114 rows.
| Window end | CAGR | Vol | Sharpe | Max DD |
|---|---|---|---|---|
| 2017-01-31 | 19.75% | 12.76% | 1.53 | -10.20% |
| 2017-02-28 | 19.98% | 12.77% | 1.53 | -10.20% |
| 2017-03-31 | 20.54% | 12.74% | 1.50 | -9.16% |
| 2017-04-28 | 23.43% | 12.68% | 1.55 | -8.71% |
| 2017-05-31 | 22.57% | 11.69% | 1.87 | -8.71% |
| ... |  |  |  |  |
| 2026-02-27 | 14.91% | 20.09% | 0.85 | -28.18% |
| 2026-03-31 | 13.07% | 19.93% | 0.78 | -28.18% |
| 2026-04-30 | 13.84% | 19.86% | 0.77 | -28.18% |
| 2026-05-29 | 13.47% | 19.89% | 0.73 | -28.18% |
| 2026-06-30 | 13.21% | 19.89% | 0.74 | -28.18% |

### Sub-period / regime table

| Period | CAGR | Vol | Sharpe | Max DD | Growth |
|---|---|---|---|---|---|
| first_half | 18.81% | 13.02% | 1.40 | -16.56% | 3.4334 |
| second_half | 16.47% | 22.83% | 0.79 | -34.76% | 3.0234 |
| precovid_2012_2019 | 19.60% | 13.80% | 1.38 | -16.56% | 4.1247 |
| covid_2020 | 4.30% | 39.13% | 0.30 | -34.76% | 1.0431 |
| rate_shock_2021_2022 | 8.90% | 24.57% | 0.47 | -28.18% | 1.1854 |
| recent_2023_plus | 22.52% | 15.95% | 1.36 | -10.34% | 2.0354 |





### Flags
- 173 rebalance date(s) had declared-universe tickers left unscored (unpriceable) and dropped from weights
- benchmark Sharpe exceeds strategy Sharpe
- 1% of rolling 3y windows negative (by CAGR)

## Execution conventions

| | |
|---|---|
| Execution mode | close - close = same-session close (the decision date's own close price). |
| Cost model | flat_bps (10.0 bps one-way) |
| Borrow fee (annual) | 30.0 bps |
| Corwin-Schultz lookback | 60 days |
| Delisting haircut | 0.00% |
| Extreme-return policy | exclude_legacy (bound 3.00x) |
| Filing lag | 1 session(s) |
| Max dropped fraction (abort threshold) | 5.00% |
| Abort on unscoreable date | True |

## Provenance appendix

| | |
|---|---|
| Strategy id | `value_composite-b6fdfec048` |
| Strategy params | `{'n_holdings': 30, 'filing_lag_sessions': 1}` |
| Backtest config | `{'start': '2012-01-01T00:00:00', 'end': '2026-06-30T00:00:00', 'strategy_config': 'C:\\Users\\arwga\\Developer\\ClaudeProjects\\Trading\\quantlab\\configs\\strategies\\value_composite.yaml', 'rebalance_freq': 'month_end', 'initial_capital': 1000000.0, 'execution': 'close', 'cost_model': 'flat_bps', 'one_way_cost_bps': 10.0, 'corwin_schultz_lookback_days': 60, 'borrow_fee_annual_bps': 30.0, 'delisting_haircut': 0.0, 'extreme_return_bound': 3.0, 'extreme_return_policy': 'exclude_legacy', 'benchmark': 'SPY', 'max_dropped_fraction': 0.05, 'abort_on_unscoreable': True}` |
| Providers | `{'prices': 'YFinancePriceProvider', 'constituents': 'SP500CommunityConstituentsProvider', 'fundamentals': 'EdgarFundamentalsProvider', 'corporate_actions': 'YFinanceCorporateActionsProvider'}` |
| Actions-cache fetched_at range | 2026-09-13 - 2026-09-13 |
| Cache dir | n/a (not recorded in the provenance for this run) |
| Run seconds | 10278.07 |
| Quarantined tickers | 0 |
| Masked-start tickers | 27 |
| quantlab version | 0.1.0 |