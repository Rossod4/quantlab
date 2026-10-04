VERDICT: REJECT

M09 quant gate, cycle 1. Branch `m09-end-to-end`, HEAD 1969fb8, tree clean at start. Inputs: packet, HANDOFF.md, HANDOFF.2.md (authoritative), REVIEW.md, REVIEW.2.md, EVIDENCE.md, QUANT-NOTES.md.

**Summary.** Nothing here weakens a bias guard. The cards, the verdicts and the gate arithmetic are correct, and every orchestrator decision I was asked to judge holds (section C). The rejection is for the two reconciliations the packet makes acceptance criterion 6 ("EXPLAIN every difference by mechanism ... unexplained differences are a finding for the gate"). Both are wrong in the CV-facing README, and the evidence that shows it was already in the repository:

1. The momentum reconciliation leaves out the largest mechanism: portfolio size. QuantLab holds 30 names and the predecessor held 50. The README calls the two "the SAME 12-1 long-only momentum strategy".
2. The value September-to-final attribution is contradicted by a series the developer did not use: the 25 September sensitivity run at the headline's own params.

Both remedies are documentation only. No backtest needs re-running. Findings 3 and 4 are small and required. Findings 5 to 9 are non-blocking and carried forward.

## A. Measured

- Power: on battery (Win32_Battery BatteryStatus 1, 57%).
- `uv run pytest -q`: exit 0, 2m46s wall including `uv` start-up. This ran on battery while my own read-only probes ran concurrently, so it is not a budget measurement. The reviewer's 86 s on AC stands as the reference, with the thin-margin caveat already recorded.
- `uv run ruff check`: clean. `uv run ruff format --check`: 136 files already formatted.
- `uv run quantlab data status` (read-only): prices 644, actions 811, fundamentals 609, no_data 168, quarantined 36, actions fetched_at 2026-09-13. These match the handoff.
- No Application Control block (os error 4551) was seen. Nothing was written under `reports/` or `data/cache/`. My only probe scripts live in the session scratchpad.

## B. Findings

### 1. BLOCKING: the momentum reconciliation omits portfolio size (n_long 30 vs top_n 50) and calls the strategies "the same"

**Risk.** The CV-facing README states a false identity and reports as "unexplained" a gap the platform's own committed grid explains. A reader would conclude that QuantLab's data layer moves momentum by about 2 pp CAGR. That conclusion is unsupported.

**Evidence.**
- The predecessor holds 50 names: `..\MomentumValueStrategy\src\config.py:44` has `top_n: int = 50`, and its README:19 says "equal-weight top-50 portfolios".
- QuantLab's headline holds 30: `configs/strategies/momentum_12_1.yaml` has `n_long: 30`, unchanged since M03 (2855138), so it is not a post-hoc choice.
- `README.md:278` says "measured the SAME 12-1 long-only momentum strategy". `README.md:306-310` and HANDOFF.md:11 then declare "~2 pp CAGR / 3.5 pp deeper drawdown ... unexplained".
- The momentum sensitivity grid already contains the predecessor's exact parameterisation, `(lookback_months=12, n_long=50)`. It is trial `momentum_12_1-c993bc68ed`, series hash `9d6aa6d258...` in `reports/trials/trials.jsonl`. Its card Sharpe of 0.9906 is committed in `reports/momentum_12_1/report_card.json` under `basic.sensitivity.surface["(12, 50)"]`.
- I recomputed all ten momentum series from the registry with `(1+r).cumprod()` from a leading 1.0, CAGR over 173/12 years and Sharpe as mean/std·√12:

  | | net CAGR | Sharpe | max DD |
  |---|---|---|---|
  | predecessor (top 50) | 15.7% | 0.96 | -19.7% |
  | QuantLab (12, 50) | 16.29% | 0.9906 | -20.09% |
  | QuantLab headline (12, 30) | 17.65% | 0.9783 | -23.25% |

  Portfolio size therefore accounts for about 1.4 of the 1.96 pp CAGR gap and about 3.2 of the 3.55 pp drawdown gap. The residual against the predecessor is about +0.6 pp CAGR, +0.03 Sharpe and -0.4 pp drawdown. For scale, SPY over the same window moved +0.3 pp between the two code bases (14.5% predecessor vs 14.81% here). That is the size of the price-vintage and price-basis noise, before quarantine (-0.18 pp, M04b) is counted.

**Required remedy (documentation only):**
- (a) Rewrite `README.md` "Reconciliation against the predecessor repo's momentum result" and the HANDOFF reconciliation line:
  - Remove "the SAME ... strategy".
  - State portfolio size as the first and dominant mechanism, with the (12, 50) row above beside the predecessor's numbers.
  - Restate the residual as about 0.6 pp CAGR / 0.4 pp drawdown, set against SPY's own +0.3 pp vintage difference and the -0.18 pp quarantine effect.
  - Keep "not decomposable further" only for that residual.
- (b) The (12, 50) CAGR and drawdown live only in the git-ignored registry series. Put the three-row table, the series hash and the one-line computation command in `plans/state/M09/EVIDENCE.md` so the README number traces to a committed file (criterion 5).

### 2. BLOCKING: the value September-to-final attribution is contradicted by the repository's own 25 September run

**Risk.** The README attributes the 2020-2022 divergence to quarantine ("the contrast is the strongest evidence"). On the evidence, most of that divergence happened on two equally unscanned caches, so quarantine cannot be its cause. The README also asserts "same code path" for a run made from a dirty tree.

**Evidence.**
- `reports/trials.bak_pre_cleanrun_2026-10-01/trials.jsonl` holds the 25 September value sensitivity run.
- Its point `value_composite-b67309d696` (n_holdings=30) has the headline's own params. In the final registry its series hash `87179ef0fd` equals the headline's.
- It was recorded on 25 September 13:47, on the same rebuilt, UNSCANNED cache as the 13 September run (EVIDENCE.md section 2: 0 quarantined until the 1 October scan).
- Three-way comparison (series `f22358628c03a714`, `cbc6db3a900b31e5` and the final `reports/value_composite/net_returns.parquet`):

  | | net CAGR | Sharpe | 2012-19 | 2020 | 2021-22 | 2023+ |
  |---|---|---|---|---|---|---|
  | 13 Sept (unscanned) | 17.62% | 0.9747 | 19.60% | 4.31% | 8.88% | 22.51% |
  | 25 Sept (unscanned, same params) | 17.49% | 0.9701 | 19.63% | 3.71% | 6.52% | 23.65% |
  | final, 1 Oct (36 quarantined) | 17.19% | 0.9493 | 19.63% | 3.71% | 6.20% | 22.52% |

  - 13→25 September: 172 of 173 periods differ, and the quarantine count did not change.
  - 25 September→final: only 39 periods differ, the first on 2021-09-30.
  - So the whole 2020 move and 2.36 of the 2.67 pp 2021-22 move are NOT quarantine. `README.md:331-333` ("TE, BEAM, NE, S, STI line up with the 2020-2022 divergence") is not supported.
  - What changed during the window that quarantine could have touched (25 September→final) is about -0.31 pp CAGR and -0.021 Sharpe, concentrated from 2021-09. About -0.13 pp and -0.005 Sharpe came from something else.
- Candidate non-quarantine channels that the README does not mention:
  - **Code.** The 13 September run is `git 395bd98, dirty=True`, the in-progress M09 iteration-1 tree (`git show dc5356d:reports/value_composite/report_card.json`). The 25 September run is also dirty. The 7e904cd/dc5356d A/B is momentum-only and cannot vouch for the fundamentals path.
  - **Fundamentals cache vintage.** That run's `run_timestamp` is 2026-09-13T18:07:05 UTC and it lasted 10,278 s, so it ran from about 16:16 to 19:07 BST. Its first rebalance's alphabetical EDGAR sweep is visible in `data/cache/fundamentals` file times: A..SNA written 16:22-16:31, then a one-hour gap. The 2012 members alphabetically from SNDK to ZION (65 files, including XOM, WMT, VZ, T, UNH, V, WFC, USB, TXN and TGT) were first written on 2026-09-23 00:29-00:32, and LVS on 2026-09-24. Those 66 tickers' facts were therefore not in the cache when the 13 September run ended, and fundamentals are fetch-once with no TTL. (Reproduce: list `data/cache/fundamentals` by LastWriteTime/CreationTime and look for the gap after SNA.)
- The README sentence "the effect of quarantine cannot be separated from data-vintage noise by re-running without the quarantine (about 6.5 hours of compute)" is wrong as well. The 25 September point already is that re-run without quarantine.

**Required remedy (documentation only):**
- Rewrite `README.md` "Value composite: the September run against the final run" and HANDOFF.md:12 around the three-way table. Attribute only the 25 September→final change (about -0.31 pp / -0.021 Sharpe, from 2021-09) to quarantine, as "consistent with", since code also moved between those two dirty trees.
- State the 13→25 September change (about -0.13 pp, the whole 2020 move, most of 2021-22) as a non-quarantine change. Name the candidates (dirty-tree code, 66 fundamentals files first written after the 13 September run) and mark it unresolved.
- Delete "same code path" and "the strongest evidence".
- Put the table and the series hashes in EVIDENCE.md.

### 3. REQUIRED (small): `paper drift` does not model the timing convention; its "model price" is the decision-bar close

**Risk.** Packet item 8 and the M08 verdict say "model the paper timing convention explicitly". `paper/drift.py:212-226` takes the model price as the raw close on `price_asof_by_ticker` (the decision bar). So `fill_vs_model_price_gap_bps` mixes the about-1.5-session overnight move (decision close → fill-session open, which is exactly the offset against the backtest's `close` convention) with execution slippage (open → fill). `assumed_fill_session` is echoed but never used. Once a real journal exists, the first number printed would report the timing offset as "fill vs model" drift, which is the failure the M08 gate warned about. The reviewer raised this for the gate; I rule it unmet.

**Required remedy:**
- Fetch the `open` of `assumed_fill_session` for each filled ticker and report two numbers per fill:
  - `timing_gap_bps` = open(fill session) vs close(decision bar), the modelled convention offset;
  - `execution_gap_bps` = fill vs open(fill session).
- Rename or re-document the current figure accordingly. Treat a missing open as "not computed", never 0.
- Add one fixture test whose decision close, fill-session open and fill price are all different.

### 4. REQUIRED (wording): the blend N statement undercounts its own double-counting

**Evidence.** The registry's five historical blend rows are momentum weights 1.00 / 0.75 / 0.50 / 0.25 / 0.00 (`reports/trials/trials.jsonl` lines 1-5). The 0.75 and 0.25 hypotheses are therefore also counted twice, as historical rows plus the new interior backtests, not only 0.50. The two endpoints DO sit in the blend family through their historical rows. That contradicts "the grid endpoints ... are not blend trials" (`README.md:256-258`, HANDOFF.md:20).

**Gate check.** The direction claim holds in this specific case. `var_sr_trials` uses only finite-Sharpe distinct trials (`registry.py:669-678`) and series-less rows enter N only, so they can only raise SR* and lower DSR. N=8 is a defensible, conservative count.

**Required remedy.** Correct the sentence: "0.75, 0.50 and 0.25 are each counted twice; the endpoints enter the blend family only via the predecessor's historical rows". Add that the historical rows raise N without entering the trial-variance estimate.

### 5. Non-blocking (carried): the ranking-agreement comparability check ignores data vintage and treats missing child params as matching

- `netted_grid._check_comparable` compares the 11 backtest-config keys and the semantics version. It does not compare `quantlab_git_sha`, `dirty`, the actions `fetched_at` range or `quarantined_count`. A standalone child run from a different cache state, such as the September unscanned value run, would be accepted as a grid endpoint.
- `netted_grid.py:218` (`own.get(key, want) != want`) treats a child param absent from provenance as a match.
- No impact on the committed result: all five inputs are dc5356d on one scanned cache (EVIDENCE.md section 4).
- **Gate ruling on the check itself:** sound. Both conventions use `sharpe_ratio(returns, rf=0, PERIODS_PER_YEAR[freq])` over the identical walk-forward out-of-sample index. `standard_metrics`' first-return blindness does not touch Sharpe. rf is 0 on both paths (`cli.py:641-648` passes no rf).
- **Caveat for readers:** two of the five points are identical by construction, and on long-only sleeves netting barely matters (largest gap 0.0002), so tau=1.0 is weak evidence. The README should not lean on it beyond "the costing convention does not change the ranking here".

### 6. Non-blocking (carried): `ttm_eps_split_factor` is meaningless for sign-mixed components

- The effective `raw_sum / restated_sum` reads -2.0 on my probe with components (4, 0, -1, -1) and a 4:1 split. It is provenance-only and no code consumes it (grep), so there is no numeric risk.
- Document it as undefined when components differ in sign, or emit per-component factors.

### 7. Non-blocking (carried): a card built on a never-scanned cache can still promote to paper

- Decision 5 (caveat, not refuse) is acceptable for research runs, and the three real runs were on a scanned cache.
- `find_promoting_report_card`, however, accepts an ELIGIBLE card whose provenance lists never-scanned cached tickers.
- Before any strategy is promoted, the promotion gate should refuse such a card. It must exclude the no_data names, which can never be scanned.

### 8. Non-blocking (cosmetic): the value strategy YAML header says "quarterly"

- `configs/strategies/value_composite.yaml:1` says "Composite value (...), quarterly", but every value and blend backtest config rebalances `month_end`.
- The predecessor's value result (15.9-16.1%, `top_n` 50, quarterly) is therefore a different construction on two axes. Note this if the README ever compares the two.

### 9. Non-blocking (carried): suite time

- 2m46s wall on battery with concurrent load (this gate), against 86 s on AC (reviewer). The default tier is near the 90 s budget on AC only.
- The REVIEW.2 minor-3 candidates (largest `test_walk_forward` / `test_netted_grid` fixtures to `slow`) stand.

## C. Orchestrator decisions: rulings

1. **Registry moved aside before the real runs: ACCEPTED.** Verified that no trial key was lost. Every key in both `reports/trials.bak_pre_cleanrun_2026-10-01` (19 keys) and `reports/trials.bak_pre_m09_step3` (16 keys) is present in the live registry, so N is not under-counted by the move.
2. **Latest-row-supersedes, N unchanged, hash mismatch loud: ACCEPTED.** A re-run of an identical key is the same hypothesis on a newer vintage, not a new trial. Superseded rows stay in the jsonl (36 raw rows, 22 keys), and `_check_series_coherent` makes a row/series disagreement fatal. Residual: a superseded row's series file is overwritten, so only its Sharpe survives for audit. That is acceptable.
3. **75/25 and 25/75 recorded as blend trials, 0.50 twice: ACCEPTED, with the wording fix in finding 4.**
4. **Five-point ranking with standalone runs as endpoints, refused on mismatch: ACCEPTED.** The code refuses on the 11 config keys plus semantics, strategy family and child params. The residual gaps are in finding 5.
5. **Never-scanned cache caveated, not refused: ACCEPTED for research runs.** Promotion residual in finding 7.
6. **Sensitivity base point = headline params even on a grid edge: ACCEPTED.** The momentum no-cliff 0.9720 is over 6 points with `neighbourhood_truncated=True`, disclosed in the card, the report and README:229-232. Two of my own observations:
   - The recomputed grid shows the headline (12, 30) has the second-lowest Sharpe of the nine points, so the headline was not cherry-picked.
   - Grid Sharpes span 0.968-1.022, so no point would clear the SPY 1.06 hard gate. The REJECT is robust to the grid.
7. **Backtests at dc5356d, validated at later shas: ACCEPTED for dc5356d→HEAD.** I re-ran `git diff --stat dc5356d HEAD -- src/quantlab/{data,strategies,backtest}`: 41 lines in engine.py, cache.py and quality.py, with the content as the reviewer described (a caveat string and scan-manifest bookkeeping). No price, return or signal arithmetic changed. The 7e904cd A/B covers momentum only and is reported by the developer, not verifiable now (REVIEW.2 minor 2). It does not cover the value or fundamentals path, which matters for finding 2.

## D. Probes the lead asked for

- **Per-component TTM EPS: correct and look-ahead-safe.** Gate probe `probe_ttm.py` (scratchpad), using the real `get_point_in_time_fundamentals` and `PITDataContext`:

  | case | ttm_eps |
  |---|---|
  | straddling 4:1 split | 4.0 |
  | plus a quarter filed after asof AND a post-split restatement of Q1 filed after asof | 4.0 (unchanged) |
  | plus a 10:1 split ex-dated after asof | 4.0 (unchanged) |
  | Q1 restated in post-split terms, filed before asof (dedup keeps it, factor 1) | 4.0 |
  | split ex-dated exactly on Q3's filed date | 4.0 (Q3 not re-restated) |
  | two splits (2:1 between Q1/Q2, 3:1 between Q3/Q4), components 6/3/3/1 | 4.0 |
  | sign-mixed components | -1.0 (correct; factor issue is finding 6) |
  | Q4 filed on asof itself | lag 0 → 4.0; lag 1 → None (Q4 excluded, no annual fallback) |

  Combined with canary (l) and the reviewer's mutation, closed.
- **K vs N:** verified from the live registry.
  - Momentum: 10 keys. The headline series hash equals the (12, 30) grid point, giving N=9 distinct and K=10. A duplicated column cannot change a max-statistic bootstrap.
  - Value: 4 keys, headline = n_holdings 30 point, giving N=3, K=4.
  - Blend: 5 series-less historical + 3 series-bearing, giving N=8, K=3. Variance is from the 3 finite Sharpes (1.031/1.021/1.005), floored at 1/(n-1).
- **Ranking agreement footing:** same footing (finding 5).
- **Paper drift timing:** not modelled (finding 3).
- **Coverage bound in the README:**
  - Correctly described as "a ceiling on invisibility, not a return impact" (README:351-357), and as the worst sampled year in the headline paragraph.
  - The direction claim ("slightly flatters every strategy-vs-SPY comparison") is plausible but unquantified. Acceptable as worded, but it should not be strengthened.
- **Momentum reconciliation:** finding 1.
- **Value September→final:** finding 2.

## E. Not reproduced / limits

- I did not run `quantlab run`, `validate` or `backtest` on real configs (operating rule).
- The finding-2 fundamentals-vintage inference rests on file times. For the 66 late files, CreationTime equals LastWriteTime, and fundamentals are fetch-once. A force-refresh on 23 September could in principle have rewritten existing files. Either way those files changed after the 13 September run, which is all finding 2 needs.
- The decomposition does not depend on this: the 13→25 September series difference is measured directly.

`git status --short` at finish: `plans/state/M09/VERDICT.md` and `plans/QUANT-NOTES.md` only.
