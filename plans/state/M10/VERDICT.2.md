VERDICT: ACCEPT

M10 quant gate, cycle 2. HEAD 217a2fe (iteration 3 is 7647f54, followed by REVIEW.3). I checked the
changes since my cycle-1 verdict with `git diff 02f9384..HEAD`, reading README.md,
docs/paper-trading.md, HANDOFF.3.md and the regenerated artefacts directly rather than relying on
the handoff table.

## A. No numerics changed

- **`src` and `tests`:** `git diff 02f9384..HEAD -- src tests` touches only string literals: the
  `regression.py` docstring, the `build.py` `hac.rule` string and three markdown labels, the
  `reporting/context.py` component name "Alpha vs SPY", and one row label in each of the two
  report templates. There are no test changes, and nothing under validation/, backtest/, data/,
  strategies/ or configs/ changed.
- **Regenerated JSONs:** `git diff --numstat 02f9384..HEAD -- reports/*/attribution.json` shows
  1/1 for each of the four files. The single changed line is `hac.rule`; every number is
  byte-identical.
- **`report.md` x3:** only the "Appraisal ratio vs SPY" and "Alpha vs SPY" label lines changed.
  The `attribution.md` files change only in the HAC rule text and the three "vs SPY" labels.
- **Trials registry:** `reports/trials/` is untouched.
- **Suite and lint:** `uv run pytest tests/ -q` gave exit 0 with 990 passed (progress characters
  counted), 82 s wall, on BATTERY (BatteryStatus 1, 42%, 1400 MHz), not AC-quiet.
  `ruff check` is clean and `ruff format --check` reports 147 files formatted.

## B. Cycle-1 findings: dispositions

1. **MAJOR, Norgate answer: CLOSED.**
   - **README.** The new "Survivorship" and "A question for the data, found after the fact"
     paragraphs give the value half-sample alpha: +4.18%/yr (HAC t 4.15, OLS t 2.78) for
     2012-02..2019-03, and +0.26% (t 0.11) after. They state that the result is roughly robust to
     the split date, set it against the coverage gap (28.4% in 2012, 14.5% in 2019, 2.2% by
     2025-26), and frame it explicitly as not a claim of alpha. The reasons given are that the
     split is in-sample, found after the fact, on a configuration chosen on this window, and that
     the short-sample HAC t sits well above the OLS t. The README concludes that only
     survivorship-free data can tell real-but-decayed alpha from an artefact.
   - **HANDOFF.3 item 3.** It carries the table (CAPM halves included), the coverage-by-year
     series, and the near-miss of a 5% Bonferroni bar.
   - **The three deleted claims.** "More likely lowers" is now "sign UNKNOWN; quarantined names
     skew to acquisition targets". "t-stats would not move" is now "t moves one-for-one with the
     point estimate". "Cannot fix power" is now "sample length is set by data availability; the
     pre-2012 history is the only power lever for momentum; value stays EDGAR-bound".
   - **Old wording still on file.** The old sentences survive only in the superseded HANDOFF.md
     line 29 and HANDOFF.2.md line 8. HANDOFF.3 states that it supersedes them, and loop
     artefacts are records, so that is acceptable.
   - **Numbers.** These match my own cycle-1 reproduction, which REVIEW.3 also re-derived
     independently.
   - **Arithmetic check.** "Roughly robust (2016-2020)" is fair. The magnitude holds at every
     split I ran (+3.0 to +4.2%), though the 2016-12 split alone has OLS t 1.70.
2. **MEDIUM, alpha-gate framing: CLOSED.** HANDOFF.3 item 4 now has four parts:
   - (a) the alpha gate is an AND condition beside `net_sharpe_vs_benchmark`, never a replacement,
     with the non-nesting example (AR 0.55, Sharpe ~0.7) and "all three fail it describes these
     series, not the rule";
   - (b) the threshold is deflated for registered trials (t ~3);
   - (c) the factor set, including whether Mom is used for a momentum rule, and the HAC lag are
     pinned in advance;
   - (d) the gate is prospective only.

   The core ruling, do not lower the Sharpe-vs-SPY bar, is kept. Nothing in iteration 3 touches
   a gate.
3. **MEDIUM, coverage bound beside the alpha: CLOSED for the README; the JSON half is carried, and
   I rule that ACCEPTABLE.**
   - **Where the bound already appears.** The README states the 28.4% bound and its decline
     immediately under the attribution table, and says nothing in the table corrects for it.
     Every `report.md` that contains the Attribution section already shows the coverage bound in
     its trust header.
   - **What remains.** The standalone `attribution.md` and `attribution.json` still carry no bound.
   - **Why carrying it is acceptable.** No artefact claims an alpha. The one alpha-like result
     sits in the README, beside the gap. Closing the gap in the files needs a code change plus a
     regeneration, which this documentation-only cycle deliberately excluded.
   - **Condition.** It must land before any attribution number is used in a gate proposal to Alex
     or in a promotion argument, and in any event at the next attribution touch. See the carried
     item in QUANT-NOTES.
4. **MINOR, beta-leverage basis: CLOSED.**
   - **Geometric basis.** The README states the beta contribution on a geometric basis:
     1.66/2.45/2.05 pp, i.e. 58/103/72% of the excess. The arithmetic split is kept and labelled.
   - **Identity.** It is described as holding "by construction (compounding is the plug)".
   - **Premium caveat.** The 13.3%/yr premium is called roughly double the long-run norm. At a
     ~6% premium the figures become 0.8/1.2/1.0 pp; I checked these as 1.72/2.55/2.14 x 6/13.3,
     which gives 0.78/1.15/0.97. In a falling market the contribution is negative.
   - **Labels and SMB.** "vs SPY" labels are present in the README, attribution.md, report.md and
     the HTML template, and the SMB-vs-CRSP note is added.
5. **MINOR, HAC wording: CLOSED.** The `regression.py` docstring and the `hac.rule` string (all
   four JSON and md files) now say that six lags is a robustness choice and that more lags can
   raise a t-stat. `Grep "more conservative"` finds it only inside that corrected sentence and in
   the superseded HANDOFF.2.
6. **MINOR, CAPM vs FF5+Mom: CLOSED.** The README says the two answer different questions and that
   neither is significant. HANDOFF.3 supersedes the "momentum's relevant number" sentence.
7. **LOW, C4 residuals: DOCUMENTED, carried to before the first real promotion.**
   docs/paper-trading.md section 6 now states both residuals:
   - the in-cycle first-cache window, including the as-of benchmark fetch;
   - the ticker-granular manifest, under which appended bars are never re-scanned.

   It marks them "fix before the first real promotion". QUANT-NOTES already carries them.

## C. New findings

None blocking.

One nit, not required: README line ~398 runs past the paragraph's wrap width ("After controlling
for beta and the five factors plus momentum, no alpha is distinguishable"). It is cosmetic only.

## D. Overall

The milestone now does what the packet asked, and does it honestly:
- It explains the three series by mechanism.
- It states that no full-sample alpha is detectable.
- It shows that most of the excess over SPY is beta, and that this depends on the bull-market
  premium.
- It surfaces the one subperiod result that survivorship-free data could overturn, without
  claiming it.
- It changes no gate, numeric or trial.

It makes the platform harder to fool, not easier. ACCEPT.

## Hygiene

No `quantlab run/validate/backtest`. No writes under `data/cache/` or `reports/`, and no probes
this cycle (read-only diff review plus the suite). `git status --short` shows only this file and
`plans/QUANT-NOTES.md`.
