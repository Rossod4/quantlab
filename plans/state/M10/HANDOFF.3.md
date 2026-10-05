# M10 HANDOFF.3 (answers VERDICT.md cycle 1, REJECT on interpretation) - developer

Not committed. No numerics, gates, backtests or trials touched. Wording-only code edits (strings/labels) and regenerated `attribution.json|md` (offline, `--factors cached`; JSON diff is the single `hac.rule` string) and `report.md` x3 (diff: "vs SPY" labels only). Supersedes HANDOFF.md items 3, 4 and the "momentum's relevant number" sentence.

| # | Status | Evidence |
|---|---|---|
| 1 MAJOR Norgate answer | rewritten (below + README "Survivorship") | gate's split reproduced from the committed return series + cached factors (read-only scratch script) |
| 2 MEDIUM gate recommendation | rewritten (below) | |
| 3 MEDIUM coverage beside the alpha | README: coverage bound 28.4% (2012; 14.5% 2019; 2.2% 2025-26) stated beside the table; dependent variable carries the gap. Carried (not done): copy `overall_bound`+`by_year` into attribution.json|md | |
| 4 MINOR beta-leverage basis | README on geometric basis 1.66/2.45/2.05 pp (58/103/72% of excess); arithmetic 1.72/2.55/2.14 kept and labelled; premium-dependence stated (13.3%/yr ~2x long-run; at 6% about 0.8/1.2/1.0 pp; negative in a fall); identity "holds by construction (compounding is the plug)"; "Alpha"/"Appraisal ratio" labelled "vs SPY" in README, attribution.md, report section; SMB-vs-CRSP note | `report.md` diff shows only the two label lines |
| 5 MINOR "6 lags more conservative" | removed from regression.py docstring and the `hac.rule` string (now: defensible robustness to longer-memory autocorrelation; more lags can raise a t; value's alpha t = 1.18/1.32/1.38/1.50 at lags 0/4/6/12; conclusions lag-invariant) | JSONs regenerated |
| 6 MINOR CAPM vs FF5+Mom | README: they answer different questions; neither significant. For momentum, CAPM +1.84% (t 0.67) = premium after market beta; FF5+Mom -1.19% (t -0.62) = anything beyond known factors (UMD itself is non-investable long-short) | |
| 7 LOW C4 residuals | docs/paper-trading.md section 6: check runs before targets, so a ticker first cached in-cycle (incl. the as-of benchmark fetch) is used unscanned that cycle; manifest is ticker-granular so appended bars are never re-scanned. No code; fix before first real promotion | |

## Item 3 (Norgate), replacement
Value's FF5+Mom alpha by half (86 / 87 months; HAC 6 lags; reproduced):
| value_composite | alpha %/yr | t HAC | t OLS | CAPM alpha (t HAC) |
|---|---|---|---|---|
| 2012-02..2019-03 | +4.18 | 4.15 | 2.78 | +3.66 (3.00) |
| 2019-04..2026-06 | +0.26 | 0.11 | 0.10 | -1.55 (-0.40) |
Momentum: h1 -3.73 (t -1.59), h2 +1.58 (0.50); blend: h1 +0.23 (0.19), h2 +0.92 (0.40). Value's coverage gap by year (%): 2012 28.4, 27.6, 26.7, 23.9, 20.8, 18.4, 17.2, 2019 14.5; then 12.3, 10.5, 6.8, 5.2, 3.8, 2.2, 2.2 (2020-26).
- This is a QUESTION FOR THE DATA found after the fact, not alpha: in-sample split chosen after seeing the full-sample result, on a configuration chosen on this window; HAC t (4.15) well above OLS t (2.78) on 86 months (short-sample optimism); over 12 (strategy x half x model) cells OLS t 2.78 misses a 5% Bonferroni bar (2.87).
- It lives exactly where 14-28% of the index is invisible to the strategy. Either real alpha that decayed, or a survivorship artefact; free data cannot tell which. Survivorship-free data is the only thing that can adjudicate it, and that is the most decision-relevant output of this milestone for the Norgate decision.
- The sign of the survivorship correction is UNKNOWN. The quarantined names skew to acquisition targets taken at a premium (missing takeover premia bias a long book DOWN) plus ticker reuses; the ~116-168 no-data names' composition was not examined. Only the magnitude is bounded (coverage gap).
- t = alpha / SE moves one-for-one with the point estimate; only the SE is roughly data-invariant. Sample length is set by data availability: for the price-only momentum rule, survivorship-free history before 2012 (vendor depth to confirm) is the only lever on power (SE ~ 1/sqrt(T): doubling T takes momentum's FF5+Mom SE from 1.92 to ~1.36%/yr) and adds bear markets, which test the "it is beta" reading. Value stays bound to EDGAR XBRL (2009+) whatever the price vendor.

## Item 4 (gate recommendation), replacement
Core ruling stands: do not lower the Sharpe-vs-SPY bar (any beta-adjusted variant now would be chosen after seeing +1.2/-0.1/+0.8 pp vs beta-matched SPY). If Alex wants an alpha gate: (a) AND condition beside `net_sharpe_vs_benchmark`, never a replacement - the tests are non-nested (alpha t >= 2 needs only appraisal ratio ~0.53 at T=14.4y; a low-beta strategy with AR 0.55 and Sharpe ~0.7 passes it and fails today's gate, so as a substitute it is looser for that class; "all three fail it" describes these series, not the rule); (b) threshold deflated for the registered trial count (Bonferroni/Harvey-Liu-Zhu, t ~ 3), as DSR does for Sharpe; (c) factor set (FF5 vs FF5+Mom, and whether a momentum rule is regressed on Mom) and HAC lag fixed in advance; (d) prospective only: trials registered after Alex's decision.

## Verification
Default tier 990 passed, 102 deselected, 56.27 s (pytest timer), BATTERY (BatteryStatus 1), not AC-quiet. ruff check and format --check clean (147 files).
