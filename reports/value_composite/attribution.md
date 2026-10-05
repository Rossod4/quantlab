# Attribution - value_composite (value_composite-b6fdfec048)

Series: strategy net returns. Informational: nothing here changes a gate.

## Sample and data vintage

- Window 2012-02 to 2026-06: 173 of 173 monthly returns used; 0 dropped by alignment; 585 factor months fall outside the window.
- Factors: Ken French data library (monthly US factors, percent -> decimal), fetched 2026-10-05T19:43:02+00:00; F-F_Research_Data_5_Factors_2x3_CSV.zip: This file was created using the 202608 CRSP database. (Last-Modified Fri, 25 Sep 2026 21:55:02 GMT); F-F_Momentum_Factor_CSV.zip: This file was created using the 202608 CRSP database. (Last-Modified Fri, 25 Sep 2026 21:55:02 GMT).
- Monthly decimal returns. Regressions use returns in EXCESS of the factor library's RF. Sharpe figures labelled excess_rf use that RF; the platform's own Sharpe (rf=0) is quoted separately as sharpe_platform_rf0.
- Sharpe (rf=0, platform convention) 0.949; Sharpe on excess over the library's RF 0.864.
- HAC: Bartlett (Newey-West), no small-sample correction; 6 lags - fixed 6 months for monthly data (half a year); the Newey-West plug-in floor(4*(T/100)^(2/9)) would give 4 here. Six is a defensible robustness choice against longer-memory autocorrelation (more lags is not uniformly more conservative: it can raise a t-stat); see each regression's alpha_t_hac_by_lag. P-values: two-sided, normal distribution.

## Regressions

### CAPM: excess return on Mkt-RF

| term | coefficient | HAC s.e. | t (HAC) |
|---|---|---|---|
| alpha (monthly) | +0.0602% | 0.1869% | +0.32 |
| Mkt-RF | +1.1581 | 0.0727 | +15.93 |

- Alpha annualised: +0.72% (monthly x12), +0.73% (geometric); 95% interval (HAC) -3.67% to +5.12%.
- Alpha t-stat (HAC, 6 lags) +0.32: NOT distinguishable from zero (|t| < 1.645). Plain-OLS t +0.33; HAC t by lag: lag 0: +0.30, lag 4: +0.31, lag 6: +0.32, lag 12: +0.34.
- R-squared 0.8127 (adjusted 0.8116), N = 173 months.

### Fama-French 5 factors + Momentum

| term | coefficient | HAC s.e. | t (HAC) |
|---|---|---|---|
| alpha (monthly) | +0.1825% | 0.1326% | +1.38 |
| Mkt-RF | +1.0871 | 0.0443 | +24.51 |
| SMB | +0.1608 | 0.0677 | +2.38 |
| HML | +0.3194 | 0.0775 | +4.12 |
| RMW | +0.2752 | 0.0757 | +3.63 |
| CMA | -0.0835 | 0.0878 | -0.95 |
| Mom | -0.1556 | 0.0708 | -2.20 |

- Alpha annualised: +2.19% (monthly x12), +2.21% (geometric); 95% interval (HAC) -0.93% to +5.31%.
- Alpha t-stat (HAC, 6 lags) +1.38: NOT distinguishable from zero (|t| < 1.645). Plain-OLS t +1.31; HAC t by lag: lag 0: +1.18, lag 4: +1.32, lag 6: +1.38, lag 12: +1.50.
- R-squared 0.9013 (adjusted 0.8977), N = 173 months.

## Rolling 36-month CAPM beta

Mean 1.161; low 0.765 (window ending 2026-06); high 1.351 (window ending 2020-03); latest 0.765. The full series is in attribution.json.

## Excess return over SPY: where it comes from

Beta against SPY excess returns: 1.192. SPY's premium over RF in this sample: +13.29% a year.

| component | pp / yr |
|---|---|
| leverage on beta = (beta - 1) x SPY premium | +2.55 |
| alpha vs SPY (regression intercept x 12) | +0.32 |
| compounding (geometric vs arithmetic annualisation) | -0.49 |
| **excess CAGR on the aligned months** | **+2.38** |

Identity gap (excess minus the three components): 1.7e-17. The platform's date-based CAGRs are +17.19% vs +14.81% (+2.38% excess; +0.00 pp from the aligned figure). Alpha t-stat vs SPY: +0.14.

### Beta-matched SPY (informational)

SPY levered to beta 1.192 compounds at +17.25%; the strategy at +17.19% (-0.07 pp). Sharpe on excess over RF: strategy 0.864, SPY 0.946, levered SPY 0.946 (equal to SPY by construction). Appraisal ratio vs SPY (alpha / idiosyncratic volatility 8.33%): +0.038. Information ratio vs SPY (platform definition): +0.327.

The existing net_sharpe_vs_benchmark gate compares total-risk-adjusted return. SPY levered to the strategy's beta has SPY's Sharpe exactly, so the gate gives no credit for beta leverage and charges for idiosyncratic variance (concentration). The beta-matched comparison belongs in alpha and appraisal-ratio terms (informational only; no gate is changed).

## Concentration

- Idiosyncratic share of variance (1 - R-squared of CAPM): 0.187 over the sample.
- In trailing 36-month windows: mean 0.137, worst 0.463 (window ending 2026-06).
- Largest single idiosyncratic month: 2020-03 (-10.44%), 11.6% of all squared residuals.
- Effective number of holdings (1 / sum w^2): mean 30.0, min 30.0, max 30.0 over 173 rebalances (mean 30.0 positions).

## Sector exposure

Sector exposure not available: the constituents provider carries no point-in-time-safe sector mapping, and none was added for this milestone.
