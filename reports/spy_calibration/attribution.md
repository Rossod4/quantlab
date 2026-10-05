# Attribution - momentum_12_1 (SPY calibration)

Series: embedded benchmark (SPY) returns. Informational: nothing here changes a gate.

## Sample and data vintage

- Window 2012-02 to 2026-06: 173 of 173 monthly returns used; 0 dropped by alignment; 585 factor months fall outside the window.
- Factors: Ken French data library (monthly US factors, percent -> decimal), fetched 2026-10-05T19:43:02+00:00; F-F_Research_Data_5_Factors_2x3_CSV.zip: This file was created using the 202608 CRSP database. (Last-Modified Fri, 25 Sep 2026 21:55:02 GMT); F-F_Momentum_Factor_CSV.zip: This file was created using the 202608 CRSP database. (Last-Modified Fri, 25 Sep 2026 21:55:02 GMT).
- Monthly decimal returns. Regressions use returns in EXCESS of the factor library's RF. Sharpe figures labelled excess_rf use that RF; the platform's own Sharpe (rf=0) is quoted separately as sharpe_platform_rf0.
- Sharpe (rf=0, platform convention) 1.058; Sharpe on excess over the library's RF 0.946.
- HAC: Bartlett (Newey-West), no small-sample correction; 6 lags - fixed 6 months for monthly data (half a year); the Newey-West plug-in floor(4*(T/100)^(2/9)) would give 4 here. Six is a defensible robustness choice against longer-memory autocorrelation (more lags is not uniformly more conservative: it can raise a t-stat); see each regression's alpha_t_hac_by_lag. P-values: two-sided, normal distribution.

## Regressions

### CAPM: excess return on Mkt-RF

| term | coefficient | HAC s.e. | t (HAC) |
|---|---|---|---|
| alpha (monthly) | +0.0418% | 0.0334% | +1.25 |
| Mkt-RF | +0.9597 | 0.0086 | +111.72 |

- Alpha annualised: +0.50% (monthly x12), +0.50% (geometric); 95% interval (HAC) -0.28% to +1.29%.
- Alpha t-stat (HAC, 6 lags) +1.25: NOT distinguishable from zero (|t| < 1.645). Plain-OLS t +1.24; HAC t by lag: lag 0: +1.32, lag 4: +1.30, lag 6: +1.25, lag 12: +1.33.
- R-squared 0.9888 (adjusted 0.9887), N = 173 months.

### Fama-French 5 factors + Momentum

| term | coefficient | HAC s.e. | t (HAC) |
|---|---|---|---|
| alpha (monthly) | -0.0088% | 0.0166% | -0.53 |
| Mkt-RF | +0.9860 | 0.0078 | +126.42 |
| SMB | -0.1120 | 0.0094 | -11.94 |
| HML | +0.0219 | 0.0128 | +1.70 |
| RMW | +0.0561 | 0.0181 | +3.10 |
| CMA | +0.0202 | 0.0148 | +1.37 |
| Mom | +0.0032 | 0.0080 | +0.40 |

- Alpha annualised: -0.11% (monthly x12), -0.11% (geometric); 95% interval (HAC) -0.50% to +0.29%.
- Alpha t-stat (HAC, 6 lags) -0.53: NOT distinguishable from zero (|t| < 1.645). Plain-OLS t -0.44; HAC t by lag: lag 0: -0.50, lag 4: -0.50, lag 6: -0.53, lag 12: -0.58.
- R-squared 0.9963 (adjusted 0.9962), N = 173 months.

## Rolling 36-month CAPM beta

Mean 0.958; low 0.936 (window ending 2021-02); high 0.987 (window ending 2023-12); latest 0.963. The full series is in attribution.json.

## Calibration: SPY against the library's market

SPY minus the library's total market return: -0.03% a year on average, tracking error 1.60%, correlation 0.9944. Expected causes of any gap:

- SPY holds the S&P 500 (large caps); the library's market is the CRSP value-weighted return of all US listings (and Mkt-RF is that minus RF)
- SPY's ~0.09% annual expense ratio is netted out of its return
- SPY's return here is the data vendor's adjusted close (dividends reinvested at the ex-date); the library compounds monthly total returns
- RF is the library's 1-month T-bill series (Ibbotson to 2024-05, ICE BofA thereafter)

## Sector exposure

Sector exposure not available: the constituents provider carries no point-in-time-safe sector mapping, and none was added for this milestone.
