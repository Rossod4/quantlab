VERDICT: REJECT

M10 quant gate, cycle 1. Branch `m10-attribution`, HEAD b052a16 (diff `main..HEAD`). Inputs: the
packet, HANDOFF.md + HANDOFF.2.md (authoritative), REVIEW.md (REVISE) and REVIEW.2.md (APPROVE),
QUANT-NOTES "M09 gate cycle 2 - ACCEPT".

**Summary.** The machinery is right and every number reproduces exactly. The rejection is on
acceptance criterion 6, the plain-English interpretation that this milestone exists to give
Alex. That is the deliverable that informs the Norgate decision. Its Norgate answer is
unsupported in three places, and it misses the single most decision-relevant result in the
data (finding 1). Its gate recommendation calls a non-nested gate "stricter" (finding 2).
The remedy is documentation only: rewritten handoff and README paragraphs, no code change,
no re-run. Cycle 2 should be one short iteration.

## A. Informational-only: confirmed (no gate, threshold, numeric or trial changed)

- `git diff main..HEAD -- configs src/quantlab/validation src/quantlab/backtest src/quantlab/data
  src/quantlab/strategies` has exactly two parts. One is the additive C1 provenance field
  (`backtest/context.py::fundamentals_fetched_at`, plus `engine.py`'s
  `provenance["fundamentals_cache_fetched_at"]`, which renames or removes no key and touches no
  numeric). The other is the single `_VINTAGE_KEYS` line in `validation/netted_grid.py`.
  `configs/` and `src/quantlab/data`/`strategies` are untouched.
- `git diff --stat main..HEAD -- reports/trials configs` is empty. The only files under
  `reports/` that changed are the four `attribution.json|md` pairs and the three `report.md`
  files, each of which gains only the "Attribution" section. No `report_card.*` changed.
- Nothing in this milestone constitutes a post-hoc change of the bar. The card text and the
  `gate_note` say "informational only; no gate is changed", and no config reads attribution.

## B. Methodology checks that PASS (reproduced at the gate)

1. **Regression and standard errors: reproduced exactly.** I parsed the cached Ken French zips
   independently (my own parser, not `factors.py`), joined them to each run's
   `net_returns.parquet`, and ran `statsmodels` OLS with `cov_type="HAC", maxlags=6` (scratch
   script, `uv run --with statsmodels`, outside the repo). Every committed figure matches to
   the printed precision:
   momentum CAPM alpha +1.842%/yr t +0.672, beta 1.0975; FF5+Mom alpha -1.190%/yr t -0.620,
   Mom 0.4636, R² 0.8518. Value FF5+Mom +2.190% t +1.377. Blend +0.503% t +0.376.
   SPY calibration beta 0.9597, alpha +0.502% t +1.252. HAC alpha SEs (%/yr): 1.92/1.59/1.34
   (FF5+Mom) and 2.74/2.24/1.85 (CAPM), matching HANDOFF.2 item 4. The Bartlett, no-small-sample
   convention is statsmodels' default, and with `use_correction=True` the t-stats move by
   <0.03. P-values on the normal distribution: fine.
2. **Sample and alignment: honest.** 173/173 months, 2012-02..2026-06, 0 dropped. Labelling is
   right. Shifting the returns one month drops CAPM R² from 0.75/0.81/0.90 to 0.024/0.034/0.033,
   so the month-end label is the month the return was earned in (`execution: close`,
   month-end rebalance).
3. **Annualisation: stated correctly.** Monthly intercept x12 is primary and the geometric
   `(1+a)^12-1` is given beside it. The t-stat belongs to the monthly intercept, the CI is in
   x12 terms, and each of these is labelled.
4. **Lag choice: defensible.** 6 is a fixed half-year. The NW plug-in gives 4 at T=173. The lag
   table (0/4/6/12) never moves an alpha |t| above 1.50, so the conclusion is lag-invariant.
   The wording needs correcting, though (finding 5).
5. **SPY calibration (packet criterion 4): adequate.** Beta 0.96 is within 0.05. Alpha +0.50%/yr
   is under 1 pp, with t 1.25. The mechanism is fully accounted for: SPY minus the library
   market is -0.03%/yr (correlation 0.994), so the CAPM alpha is almost entirely
   (1 - 0.96) x the 13.3%/yr premium, about 0.53 pp. That is a large-cap effect (SMB -0.11,
   t -11.9), not a pipeline error, and the FF5+Mom alpha is -0.11 (t -0.53). One consequence
   for reading the strategy rows belongs in finding 4: the strategies' SMB loadings are
   measured against CRSP, so relative to SPY their small-cap tilt is about 0.1 larger than it
   looks.
6. **Decomposition arithmetic: right and correctly labelled informational.**
   `12 mean(r_s) - 12 mean(r_b) = 12a + (beta-1) 12 mean(x_b)` is exact for OLS with an
   intercept. I reproduced the components (momentum: beta_SPY 1.1296, leverage 1.722, alpha
   1.454, compounding -0.329, excess 2.847 pp) and the beta-matched line (strategy minus
   levered SPY: +1.19/-0.07/+0.81 pp). The statement that levered SPY has SPY's Sharpe is
   correct.
   The developer's gate-note wording ("gives no credit for beta leverage and charges for
   idiosyncratic variance") is MORE accurate than the packet's "penalises beta": the Sharpe gate
   is beta-neutral, not beta-penalising. Accepted as written.
7. **"No alpha at any conventional level" (full sample): supported.** FF5+Mom t -0.62/+1.38/+0.38
   and CAPM t 0.67/0.32/0.70. The 95% intervals in HANDOFF.md item 1 reproduce. "~60-100% of the
   excess is beta leverage" is also supported (60/107/75%; 58/103/72% on a geometric-consistent
   basis, see finding 4).
8. **Gate recommendation, core ruling: sound.** Do NOT lower the Sharpe-vs-SPY bar. Any
   beta-adjusted variant adopted now would be chosen after seeing +1.2/-0.1/+0.8 pp versus
   beta-matched SPY. That is the post-hoc softening the platform exists to stop, and the
   handoff says so. What is wrong is the characterisation of the alternative (finding 2).
9. **Suite and lint.** `uv run pytest tests/ -q`: exit 0, 990 passed (progress characters
   counted), 89 s wall. Power: BATTERY (Win32_Battery BatteryStatus 1, 55%), CPU 1400 MHz,
   other agents present, so this is not an AC-quiet figure. `ruff check` is clean and
   `ruff format --check` reports 147 files formatted.

## C. Findings

### 1. MAJOR (blocking): the Norgate answer is unsupported, and it misses the one significant alpha in the data

HANDOFF.md item 3 says: "better data cannot fix the power problem ... the 168 no-data + 36
quarantined names are mostly delisted/corrupt, so correcting them more likely lowers
returns/alpha ... Numbers that would move: coverage bound, net CAGR, alpha. The t-stats would
not." The README attribution paragraph carries the same reading. Four problems:

(a) **The value strategy has a large, significant alpha in the first half of the sample, and
none in the second.** Gate reproduction (statsmodels, FF5+Mom, HAC 6 lags, mechanical
midpoint split):

| value_composite | months | FF5+Mom alpha %/yr | t (HAC) | t (OLS) |
|---|---|---|---|---|
| 2012-02..2019-03 | 86 | +4.18 | +4.15 | +2.78 |
| 2019-04..2026-06 | 87 | +0.26 | +0.11 | +0.10 |

The result is robust to the split date. Pre-split alpha is +3.3 to +4.2%/yr (OLS t 1.7-2.8) for
splits at 2016-12, 2017-12, 2018-12, 2019-03 and 2020-12. Post-split alpha is +0.3 to
+2.2%/yr (t 0.1-1.1). CAPM on the same halves gives +3.66% (t 3.00) and then -1.55% (t -0.40).
Momentum and the blend show nothing comparable (momentum h1 -3.73% t -1.59; blend +0.23/+0.92).

(b) **That window is exactly where the survivorship gap is largest.**
`reports/value_composite/coverage_report.json` `by_year` reads 28.4, 27.6, 26.7, 23.9, 20.8,
18.4, 17.2 and 14.5% for 2012-2019, against 12.3% falling to 2.2% for 2020-2026. So the only
statistically significant alpha this milestone produced lives in the years when 14-28% of the
index is invisible to the strategy. Either it is real alpha that decayed, or it is a
survivorship artefact. Free data cannot tell these apart. Survivorship-free data can, and that
is the most decision-relevant thing the attribution says about Norgate. The handoff's answer,
"better data ... does not create alpha", inverts it: better data is the only way to adjudicate
the one alpha that is there.

Caveat, which the cycle-2 text must carry: this split was examined at the gate, after the fact.
It is in-sample for a configuration chosen on this window, and the HAC t on 86 months runs well
above OLS (4.15 vs 2.78), a known short-sample HAC optimism. It is a question for the data, not
a claim of alpha. Against a Bonferroni bar over the 12 (strategy x half x model) cells, OLS t
2.78 just misses 5% two-sided (|t| 2.87) and clears 10% (|t| ~2.64). HAC t 4.15 clears both.

(c) **"More likely lowers returns/alpha" is not supported.** The quarantined names visible in
the coverage report's 2012 list are predominantly acquisition targets taken out at a premium
(EMC, BMC, CAM, APC, LIFE, BEAM, HOT, COL, HAR, SPLS, POM, TE/TEG, SCG, NFX, PCL, S, SE, STI, ADT)
plus ticker reuses (FB, FOX/FOXA, IR, LB). Only a few are distress cases (NE, SBNY). Missing
takeover premia biases a long book's return DOWN, not up. The composition of the ~116-168
no-data names was not examined by the developer or by me. The sign of the correction is
unknown; only its magnitude is bounded.

(d) **"The t-stats would not move" is wrong.** t = alpha / SE. Only the SE is roughly invariant
to data quality, so any change in the point estimate moves t one-for-one. "Better data cannot
fix the power problem (alpha SE is set by sample length and idio vol)" is also incomplete. The
sample length is itself set by data availability. For the price-only momentum rule, a
survivorship-free history that reaches before 2012 (vendor depth to be confirmed) is the only
lever on power that exists: SE scales as 1/sqrt(T), so doubling T takes momentum's FF5+Mom SE
from 1.92 to ~1.36%/yr. It would also add bear markets, which test the "it's beta" reading
directly (see finding 4). Value stays bound to EDGAR XBRL (2009+) whatever the price vendor.

**Remedy (documentation only):** HANDOFF.3.md replaces item 3 with:
- the subperiod table above;
- the coverage-by-year alignment;
- "sign of the survivorship correction unknown; the visible quarantined names skew to M&A
  targets";
- t moves with the point estimate;
- the sample-length lever for momentum.

The README attribution paragraph gains one sentence giving the first-half/second-half value
alpha with the coverage-gap context and the after-the-fact caveat. No code change is required.
Optionally, a per-half regression in `attribution.json` can be carried (QUANT-NOTES).

### 2. MEDIUM (blocking): the prospective alpha gate is called "stricter, not looser", which holds only as an ADDITIONAL condition

HANDOFF.md item 4: "an FF5(+Mom ...) alpha gate needs t >= 2 on the alpha, which all three FAIL,
so it is stricter, not looser."

The two tests are non-nested. For a strategy with beta > 0, appraisal ratio AR = alpha/sigma_e
and market Sharpe SR_m, the strategy's Sharpe satisfies SR_s >= min(AR, SR_m) and can sit
anywhere above that. Alpha t >= 2 over T years needs only AR >= 2/sqrt(T), which is ~0.53 at
T = 14.4. SPY's excess Sharpe in this sample is 0.95. So a strategy with AR 0.55 (t ~2.1) and a
Sharpe of ~0.7 passes an alpha gate and fails today's Sharpe gate. As a REPLACEMENT, the alpha
gate is looser for exactly that class of strategy: low-beta, high-idio. "All three fail it" is a
statement about these three series, not about the rule, and that is the post-hoc reasoning the
handoff warns against.

Two further omissions:
- A single-test t >= 2 ignores the trials registry. The platform deflates Sharpe for N via
  DSR, so an alpha gate needs the same treatment: a Bonferroni-style or Harvey-Liu-Zhu
  threshold (t ~3) over registered trials.
- The factor set (FF5 vs FF5+Mom, and whether a momentum rule is regressed on Mom) and the HAC
  lag must be pinned before any trial is run. Otherwise they are researcher degrees of freedom.

**Remedy (documentation only):** HANDOFF.3.md item 4 states that any alpha gate is proposed as
an AND condition beside `net_sharpe_vs_benchmark`, never a substitute. Its t threshold is
deflated for the registered trial count. Factor set and lag are fixed in advance. It applies
only to trials registered after Alex's decision. The core ruling (do not lower the bar) stands
as written.

### 3. MEDIUM (non-blocking, fold into cycle 2): the survivorship gap is not surfaced beside the alpha figures

`attribution.json`, `attribution.md` and the README "Attribution" section contain no coverage
bound (`Grep -i "surviv|coverage|quarantin"` over `reports/*/attribution.*` and
`src/quantlab/attribution/` returns nothing). The dependent variable of every regression carries
a 28.4% worst-year coverage gap. CLAUDE.md invariant #2 says it is measured, not footnoted, and
a standalone `attribution.md` or the README table will be quoted without the report card beside
it. `report.md` is fine, since it shows the bound at the top.

**Required in cycle 2:** one README sentence. **Carried:** `build.py` copies
`coverage_report.overall_bound` + `by_year` into `attribution.json|md`.

### 4. MINOR: the beta-leverage share is arithmetic-on-geometric and specific to the sample's premium

- "Leverage on beta" is arithmetic, so the extra variance drag that comes from beta itself lands
  in "compounding". The geometric-consistent beta contribution (levered-SPY CAGR minus SPY CAGR)
  is 1.66/2.45/2.05 pp against the 1.72/2.55/2.14 pp reported. The 60-100% claim survives
  (58/103/72%).
- The 13.3%/yr SPY premium in 2012-2026 is roughly double long-run norms. The pp attributed to
  beta are a property of this bull market. At a ~6% premium they would be about half, and in a
  falling market they are negative. Say so beside the table.
- The decomposition identity holds by construction ("compounding" is the plug). The 1e-16
  identity test checks arithmetic, not a model, and should be described that way.
- The decomposition table in `report.md` and the README labels the SPY-regression intercept
  "Alpha" (0.32 for value), next to a CAPM alpha against Mkt-RF (0.72). The appraisal ratio is
  also the SPY-regression one. Label both "vs SPY".
- SMB is measured against CRSP. SPY itself loads -0.11, so the strategies' +0.07..+0.16 is about
  +0.2 relative to their own S&P 500 benchmark: the equal-weight 30-name small-cap tilt.

### 5. MINOR: "6 lags is the more conservative choice" is wrong as stated

`regression.py` module docstring and the `build.py` `hac.rule` string: more lags is not more
conservative in general. Value's alpha t RISES with the lag (0: 1.18, 4: 1.32, 6: 1.38,
12: 1.50) because the residual autocorrelation is negative. Six is defensible as robustness to
longer memory, and the lag table shows the conclusion does not depend on it. Reword to "robust
to longer-memory autocorrelation; see alpha_t_hac_by_lag". This is carried, since it needs a
regeneration of the four JSONs (`quantlab attribute`, which is permitted).

### 6. MINOR: momentum's "relevant number is CAPM alpha" overstates

Both numbers are relevant; they answer different questions. CAPM alpha (+1.84%, t 0.67)
measures the momentum premium harvested after market beta. FF5+Mom alpha (-1.19%, t -0.62)
measures anything beyond a known factor. The second is the question for "would I do better
with a cheap factor product?", though UMD itself is a non-investable long-short. Neither is
significant. Reword in HANDOFF.3 and the README.

### 7. LOW (non-blocking, carried): C4 leaves a one-cycle window, and appended bars are never re-scanned

Probed with a planted ticker (scratch pytest reusing `tests/test_runner.py`'s fixtures, outside
the repo):
- `force_research=True, dry_run=True` with an unscanned `GATEPLANT`: REFUSED, `PromotionGateError`
  naming it, journal empty (dry run). PASS.
- Card present, cache with prices but the manifest deleted: REFUSED. PASS.
- A price provider that caches a NEW ticker `MIDRUN` during the strategy's own price fetch (stage
  "targets", after the check): the first run COMPLETES (`refused_reason: None`, orders planned,
  with `MIDRUN` unscanned in the cache). The next run refuses naming `MIDRUN`. So a name first
  cached during a cycle is used unscanned for that cycle. `resolve_asof`'s benchmark fetch
  (line 564) also precedes the check.
- Separately, the scan manifest is ticker-granular (`data/quality.py::unscanned_tickers`). Bars
  appended to an already-scanned ticker (every paper day) are never re-scanned, so a ticker
  reassigned to a new issuer after the scan passes the check. This predates M10.

C4 as specified ("the CURRENT cache's scan coverage ... before placing orders") is CLOSED. These
are residuals, to fix before the first real promotion: re-run the check after
`generate_targets` and before `plan_orders`, and give the manifest a per-ticker scanned-through
date. The real cache reads 0 unscanned today (`current_unscanned_cached_tickers("data/cache")`,
read-only). The check also refuses on ANY cached ticker, not only the strategy's universe. That
is conservative and acceptable.

## D. Carried items C1-C4

- **C1, CLOSED.** `provenance.fundamentals_cache_fetched_at {min,max,basis}` is additive, emitted
  only when the fundamentals provider was called, and added to `_VINTAGE_KEYS`. None-vs-dict on
  old-vs-new runs is disclosed, not refused. Basis is file mtime, honestly labelled: a
  re-written or touched file reads as its rewrite date. That is acceptable as the only evidence
  that exists. A real `fetched_at` sidecar on the EDGAR cache is a future data-layer item.
- **C2, CLOSED.** docs/paper-trading.md section 7 has the ex-dividend sentence.
- **C3, CLOSED.** README has "the only window where removing them changed the series".
- **C4, CLOSED, with residuals (finding 7).**

## E. Required for cycle 2 (all documentation, no code, no re-run)

1. HANDOFF.3.md item 3, the Norgate answer, rewritten per finding 1 (a)-(d).
2. HANDOFF.3.md item 4, the gate recommendation: AND-only, trial-deflated threshold, pinned
   factor set and lag, prospective (finding 2).
3. README attribution paragraph: the value subperiod sentence with the coverage context and
   the after-the-fact caveat, plus the coverage-bound sentence (finding 3) and the
   bull-market-premium sentence (finding 4).
4. Wording for findings 4 (labels) and 6, where cheap.

Findings 3 (attribution.json field), 5 and 7 are carried in QUANT-NOTES.

## Hygiene

No `quantlab run/validate/backtest`. No writes under `data/cache/` or `reports/`; the factor
cache and committed artefacts were read only, and every probe and script lived in the session
scratchpad. `git status --short` shows only this file and `plans/QUANT-NOTES.md`.
