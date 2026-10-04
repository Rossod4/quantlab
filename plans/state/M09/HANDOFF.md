# M09 HANDOFF (developer 3) - for the gate. Real runs at clean sha dc5356d; tree = m09-end-to-end

## One-liners (reports/<name>/report_card.md|json, provenance.json; SPY 14.81% CAGR, Sharpe 1.06)
- momentum_12_1 REJECTED: 17.66% / Sharpe 0.98 / maxDD -23.25%. Hard fails: net Sharpe vs SPY, coverage 28.4% (>15%), Reality Check p=0.144 (K=10), min TRL unbounded. Soft fails: SPA p=0.199, MC drawdown 0.50. DSR 0.982 (N=9) passes.
- value_composite REJECTED: 17.19% / 0.95 / -34.75%. Hard fails: net Sharpe vs SPY, coverage, min TRL. DSR 0.992 (N=3), RC p=0.015 (K=4), SPA p=0.020, no-cliff 0.93 all pass.
- blend_50_50 REJECTED: 17.67% / 1.03 / -28.36%. Hard fails: net Sharpe vs SPY, coverage, RC p=0.1045 (K=3, near miss), min TRL. DSR 0.985 (N=8), SPA p=0.080 pass. Soft fail: no_cliff only because no sensitivity grid is configured for the blend (weight grid is its only axis; none added).
- Ranking agreement (blend card, `ranking_agreement`): 5 points, Kendall tau 1.0, top choice 75/25 agrees, netted vs blend-of-nets Sharpe within 0.0002, OOS window 2017-02..2026-06 (113 months). Walk-forward stability gate passes (70%) but the walk-forward picked 100% value in 7 of 10 steps.
- Wall times (backtest only) 1329 / 23373 / 25352 s: NOT benchmarks (laptop standby, 5 concurrent jobs). Momentum full `run` 10.1 h.

## Reconciliation (detail: README "Reconciliation" and "Value composite" sections)
- Momentum vs old repo (15.7/0.96/-19.7): NOT the same strategy - the old repo holds 50 names, the headline 30. QuantLab's own grid point (12, 50) gives 16.29% / 0.991 / -20.09% (registry series; EVIDENCE.md), so portfolio size explains ~1.4 of the 1.96 pp CAGR gap and ~3.2 of the 3.55 pp drawdown gap; residual ~0.6 pp / 0.4 pp is of the order of SPY's own +0.3 pp vintage difference between the code bases. Engine at 7e904cd vs dc5356d: identical net returns (merge numerics-neutral); vs the 12 Sept run 1.6e-7/period = data vintage. Quarantine moved it -0.18 pp (M04b); window clamp and benchmark-from-store could not.
- Value (13 Sept 17.62%/0.9747 -> 25 Sept same-params run 17.49%/0.9701 -> final 17.19%/0.9493; 25 Sept grid point value_composite-b67309d696): 13->25 Sept (-0.13 pp, all of the 2020 move, most of 2021-22) is NOT quarantine (both unscanned) and is UNRESOLVED; candidates: dirty-tree code differences, 66 fundamentals files first written 23-24 Sept (names in README). 25 Sept->final (-0.30 pp, 39 periods from 2021-09-30) is consistent with quarantine, not proven. Table in README/EVIDENCE.md.

## Why runs are at dc5356d, and what differs at HEAD
Files changed dc5356d..HEAD: cli.py (ranking/--record-trial/--child-result), validation/{netted_grid,registry,report_card}.py, reporting/context.py (report text), data/{cache,quality}.py (scan-manifest JSON only), backtest/engine.py (one caveat string), 4 configs for netted-grid blends. None touches strategies/, price/return code or engine arithmetic; 7e904cd/dc5356d A/B and tests/test_blend_endpoint_equivalence.py (weight-1 blend == child incl. costs) support that. Re-rendering the momentum and value reports with HEAD code left every tracked file byte-identical.

## Decisions / deviations
- Fresh registry: `reports/trials` moved to `reports/trials.bak_pre_cleanrun_2026-10-01` before the runs recorded (old rows came from an unscanned cache, first-seen-wins would have kept stale Sharpes).
- Registry policy: latest row for an identical key supersedes (N unchanged, old rows stay in jsonl); row/series hash mismatch raises `RegistryCoherenceError` (family-scoped).
- 75/25 and 25/75 blend backtests recorded as blend trials (`validate --record-trial`); N=8 = 5 historical rows (momentum weight 1.00/0.75/0.50/0.25/0.00, series-less) + headline + 75/25 + 25/75 backtests: 0.75, 0.50, 0.25 counted twice; endpoints are in the blend family only via the historical rows; series-less rows raise N but not the trial variance (conservative). Their provenance `strategy_config` points at scratchpad YAMLs; committed configs/strategies/blend_{75_25,25_75}.yaml give the same ids (blend-a7f7c30ce1, blend-9231a3894e). Netted-grid run dirs are uncommitted; the blend card's `ranking_agreement` carries every number the README quotes.
- Ranking uses all 5 points; endpoints are the standalone child runs, refused unless window/cost/semantics/params match; each input's run dir + strategy id recorded; failures render "not checked: <reason>".
- Parallel launch before momentum fully exited (cache warm, 0 network fetches).
- Scan fixes: narrowed re-scan no longer wipes the manifest; a rewritten price file stops counting as scanned. Quarantine itself survives prefetch/refresh/clear-negative-cache (tests/test_quarantine_survival.py).

## Closure
Carried 1-12 closed (7: card wired; 3: provenance.json now committed, quarantined count stated in each report; 9: README). Item 13: `slow` marker in place. Measured 2 Oct at HEAD 20cb21e on battery (24%, Balanced plan, CPU ~1.4 GHz, i.e. throttled): default suite 873 passed, 100 deselected in 123.25 s (my own run 121.55 s); `-m slow` 95 passed in 91.34 s. On AC (2 Oct, value still running) 70 s. `--durations=25` shows no dominant tests (slowest 2.7 s, top 25 sum ~28 s; ~0.14 s average over 873), so nothing was newly marked slow: the throttled figure exceeds 90 s but there is no handful of tests to move without deselecting coverage. Note: pytest.exe was transiently blocked by Windows Smart App Control on 2 Oct (os error 4551) and cleared without intervention; if it recurs, stop and report, do not route around it. Criteria 1-6 met. Data status now: prices 644, actions 811, fundamentals 609, actions fetched_at 2026-09-13, no_data 168, quarantined 36, masked truncations 18, never scanned 0 (last scan 2026-10-01). Ruff check and format clean.

## Known warts
- Momentum's nine sensitivity rows are dirty=True/registry_at_record_time: `run` rewrote its own tracked artefacts before recording; fixed for new rows (take headline provenance.dirty), existing rows left as recorded.
- A never-scanned cache is caveated (known_caveats, provenance), not refused. 168 no-data names always show as never scanned. Quarantine was lost by the 12 Sept cache rebuild, not by an ordinary command (circumstantial; no rebuild log).
- Corporate-actions calls ~1,010 per rebalance (membership probe + per-context fetch): by design, no baseline.

## Open questions for the gate
Should a run on a never-scanned cache be refused rather than caveated? Is the latest-supersedes registry policy acceptable? Is counting the two grid blends (and 0.50 twice) the right N for the blend DSR?
