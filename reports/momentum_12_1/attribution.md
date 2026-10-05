# Attribution - momentum_12_1 (momentum-2b2c9fd50a)

Series: strategy net returns. Informational: nothing here changes a gate.

## Sample and data vintage

- Window 2012-02 to 2026-06: 173 of 173 monthly returns used; 0 dropped by alignment; 585 factor months fall outside the window.
- Factors: Ken French data library (monthly US factors, percent -> decimal), fetched 2026-10-05T19:43:02+00:00; F-F_Research_Data_5_Factors_2x3_CSV.zip: This file was created using the 202608 CRSP database. (Last-Modified Fri, 25 Sep 2026 21:55:02 GMT); F-F_Momentum_Factor_CSV.zip: This file was created using the 202608 CRSP database. (Last-Modified Fri, 25 Sep 2026 21:55:02 GMT).
- Monthly decimal returns. Regressions use returns in EXCESS of the factor library's RF. Sharpe figures labelled excess_rf use that RF; the platform's own Sharpe (rf=0) is quoted separately as sharpe_platform_rf0.
- Sharpe (rf=0, platform convention) 0.978; Sharpe on excess over the library's RF 0.894.
- HAC: Bartlett (Newey-West), no small-sample correction; 6 lags - fixed 6 months for monthly data (half a year); the Newey-West plug-in floor(4*(T/100)^(2/9)) would give 4 here. Six is a defensible robustness choice against longer-memory autocorrelation (more lags is not uniformly more conservative: it can raise a t-stat); see each regression's alpha_t_hac_by_lag. P-values: two-sided, normal distribution.

## Regressions

### CAPM: excess return on Mkt-RF

| term | coefficient | HAC s.e. | t (HAC) |
|---|---|---|---|
| alpha (monthly) | +0.1535% | 0.2285% | +0.67 |
| Mkt-RF | +1.0975 | 0.0555 | +19.77 |

- Alpha annualised: +1.84% (monthly x12), +1.86% (geometric); 95% interval (HAC) -3.53% to +7.22%.
- Alpha t-stat (HAC, 6 lags) +0.67: NOT distinguishable from zero (|t| < 1.645). Plain-OLS t +0.74; HAC t by lag: lag 0: +0.76, lag 4: +0.71, lag 6: +0.67, lag 12: +0.63.
- R-squared 0.7521 (adjusted 0.7507), N = 173 months.

### Fama-French 5 factors + Momentum

| term | coefficient | HAC s.e. | t (HAC) |
|---|---|---|---|
| alpha (monthly) | -0.0992% | 0.1600% | -0.62 |
| Mkt-RF | +1.2040 | 0.0360 | +33.49 |
| SMB | +0.0684 | 0.0722 | +0.95 |
| HML | +0.1093 | 0.0914 | +1.20 |
| RMW | -0.2689 | 0.1032 | -2.61 |
| CMA | -0.0079 | 0.1398 | -0.06 |
| Mom | +0.4636 | 0.0750 | +6.18 |

- Alpha annualised: -1.19% (monthly x12), -1.18% (geometric); 95% interval (HAC) -4.95% to +2.57%.
- Alpha t-stat (HAC, 6 lags) -0.62: NOT distinguishable from zero (|t| < 1.645). Plain-OLS t -0.59; HAC t by lag: lag 0: -0.58, lag 4: -0.64, lag 6: -0.62, lag 12: -0.62.
- R-squared 0.8518 (adjusted 0.8465), N = 173 months.

## Rolling 36-month CAPM beta

Mean 1.077; low 0.922 (window ending 2022-02); high 1.466 (window ending 2026-05); latest 1.460. The full series is in attribution.json.

## Excess return over SPY: where it comes from

Beta against SPY excess returns: 1.130. SPY's premium over RF in this sample: +13.29% a year.

| component | pp / yr |
|---|---|
| leverage on beta = (beta - 1) x SPY premium | +1.72 |
| alpha vs SPY (regression intercept x 12) | +1.45 |
| compounding (geometric vs arithmetic annualisation) | -0.33 |
| **excess CAGR on the aligned months** | **+2.85** |

Identity gap (excess minus the three components): 4.2e-17. The platform's date-based CAGRs are +17.66% vs +14.81% (+2.85% excess; +0.00 pp from the aligned figure). Alpha t-stat vs SPY: +0.53.

### Beta-matched SPY (informational)

SPY levered to beta 1.130 compounds at +16.46%; the strategy at +17.65% (+1.19 pp). Sharpe on excess over RF: strategy 0.894, SPY 0.946, levered SPY 0.946 (equal to SPY by construction). Appraisal ratio vs SPY (alpha / idiosyncratic volatility 9.35%): +0.155. Information ratio vs SPY (platform definition): +0.333.

The existing net_sharpe_vs_benchmark gate compares total-risk-adjusted return. SPY levered to the strategy's beta has SPY's Sharpe exactly, so the gate gives no credit for beta leverage and charges for idiosyncratic variance (concentration). The beta-matched comparison belongs in alpha and appraisal-ratio terms (informational only; no gate is changed).

## Concentration

- Idiosyncratic share of variance (1 - R-squared of CAPM): 0.248 over the sample.
- In trailing 36-month windows: mean 0.202, worst 0.318 (window ending 2017-12).
- Largest single idiosyncratic month: 2026-06 (+11.35%), 10.7% of all squared residuals.
- Effective number of holdings (1 / sum w^2): mean 30.0, min 30.0, max 30.0 over 173 rebalances (mean 30.0 positions).

## Sector exposure

Sector exposure not available: the constituents provider carries no point-in-time-safe sector mapping, and none was added for this milestone.
