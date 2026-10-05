# Attribution - blend_50_50 (blend-153a7466bc)

Series: strategy net returns. Informational: nothing here changes a gate.

## Sample and data vintage

- Window 2012-02 to 2026-06: 173 of 173 monthly returns used; 0 dropped by alignment; 585 factor months fall outside the window.
- Factors: Ken French data library (monthly US factors, percent -> decimal), fetched 2026-10-05T19:43:02+00:00; F-F_Research_Data_5_Factors_2x3_CSV.zip: This file was created using the 202608 CRSP database. (Last-Modified Fri, 25 Sep 2026 21:55:02 GMT); F-F_Momentum_Factor_CSV.zip: This file was created using the 202608 CRSP database. (Last-Modified Fri, 25 Sep 2026 21:55:02 GMT).
- Monthly decimal returns. Regressions use returns in EXCESS of the factor library's RF. Sharpe figures labelled excess_rf use that RF; the platform's own Sharpe (rf=0) is quoted separately as sharpe_platform_rf0.
- Sharpe (rf=0, platform convention) 1.031; Sharpe on excess over the library's RF 0.941.
- HAC: Bartlett (Newey-West), no small-sample correction; 6 lags - fixed 6 months for monthly data (half a year); the Newey-West plug-in floor(4*(T/100)^(2/9)) would give 4 here. Six is a defensible robustness choice against longer-memory autocorrelation (more lags is not uniformly more conservative: it can raise a t-stat); see each regression's alpha_t_hac_by_lag. P-values: two-sided, normal distribution.

## Regressions

### CAPM: excess return on Mkt-RF

| term | coefficient | HAC s.e. | t (HAC) |
|---|---|---|---|
| alpha (monthly) | +0.1071% | 0.1540% | +0.70 |
| Mkt-RF | +1.1278 | 0.0334 | +33.75 |

- Alpha annualised: +1.29% (monthly x12), +1.29% (geometric); 95% interval (HAC) -2.34% to +4.91%.
- Alpha t-stat (HAC, 6 lags) +0.70: NOT distinguishable from zero (|t| < 1.645). Plain-OLS t +0.84; HAC t by lag: lag 0: +0.76, lag 4: +0.74, lag 6: +0.70, lag 12: +0.67.
- R-squared 0.8952 (adjusted 0.8946), N = 173 months.

### Fama-French 5 factors + Momentum

| term | coefficient | HAC s.e. | t (HAC) |
|---|---|---|---|
| alpha (monthly) | +0.0419% | 0.1114% | +0.38 |
| Mkt-RF | +1.1456 | 0.0235 | +48.80 |
| SMB | +0.1146 | 0.0503 | +2.28 |
| HML | +0.2143 | 0.0668 | +3.21 |
| RMW | +0.0032 | 0.0643 | +0.05 |
| CMA | -0.0457 | 0.0867 | -0.53 |
| Mom | +0.1540 | 0.0569 | +2.71 |

- Alpha annualised: +0.50% (monthly x12), +0.50% (geometric); 95% interval (HAC) -2.12% to +3.12%.
- Alpha t-stat (HAC, 6 lags) +0.38: NOT distinguishable from zero (|t| < 1.645). Plain-OLS t +0.36; HAC t by lag: lag 0: +0.32, lag 4: +0.38, lag 6: +0.38, lag 12: +0.40.
- R-squared 0.9205 (adjusted 0.9176), N = 173 months.

## Rolling 36-month CAPM beta

Mean 1.119; low 1.005 (window ending 2017-09); high 1.266 (window ending 2025-09); latest 1.112. The full series is in attribution.json.

## Excess return over SPY: where it comes from

Beta against SPY excess returns: 1.161. SPY's premium over RF in this sample: +13.29% a year.

| component | pp / yr |
|---|---|
| leverage on beta = (beta - 1) x SPY premium | +2.14 |
| alpha vs SPY (regression intercept x 12) | +0.89 |
| compounding (geometric vs arithmetic annualisation) | -0.16 |
| **excess CAGR on the aligned months** | **+2.86** |

Identity gap (excess minus the three components): 6.9e-18. The platform's date-based CAGRs are +17.67% vs +14.81% (+2.86% excess; +0.00 pp from the aligned figure). Alpha t-stat vs SPY: +0.48.

### Beta-matched SPY (informational)

SPY levered to beta 1.161 compounds at +16.86%; the strategy at +17.67% (+0.81 pp). Sharpe on excess over RF: strategy 0.941, SPY 0.946, levered SPY 0.946 (equal to SPY by construction). Appraisal ratio vs SPY (alpha / idiosyncratic volatility 5.93%): +0.150. Information ratio vs SPY (platform definition): +0.477.

The existing net_sharpe_vs_benchmark gate compares total-risk-adjusted return. SPY levered to the strategy's beta has SPY's Sharpe exactly, so the gate gives no credit for beta leverage and charges for idiosyncratic variance (concentration). The beta-matched comparison belongs in alpha and appraisal-ratio terms (informational only; no gate is changed).

## Concentration

- Idiosyncratic share of variance (1 - R-squared of CAPM): 0.105 over the sample.
- In trailing 36-month windows: mean 0.082, worst 0.211 (window ending 2026-06).
- Largest single idiosyncratic month: 2026-06 (+7.61%), 12.8% of all squared residuals.
- Effective number of holdings (1 / sum w^2): mean 55.1, min 48.6, max 60.0 over 173 rebalances (mean 57.3 positions).

## Sector exposure

Sector exposure not available: the constituents provider carries no point-in-time-safe sector mapping, and none was added for this milestone.
