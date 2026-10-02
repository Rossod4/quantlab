# M09 HANDOFF (developer 3, DRAFT - value_composite results pending)

Branch `m09-wire` (on dc5356d), merged into `m09-end-to-end` by the orchestrator. Real runs: clean sha dc5356d.

## Results (files under reports/<name>/: report_card.md/json, provenance.json)
- momentum_12_1: REJECTED, 17.66% / 0.98 / -23.25% (SPY 14.81% / 1.06). Hard fails: net Sharpe vs SPY, coverage 28.4% > 15%, Reality Check p=0.144, min TRL. DSR 0.9823 (N=9) passes.
- blend_50_50: REJECTED, 17.67% / 1.03 / -28.36%. Hard fails: net Sharpe vs SPY, coverage, and DSR/RC "not computable" (N=6, <2 series-bearing trials; counted as failures). Walk-forward stability passes (70% modal) but chose 100% value in 7 of 10 steps.
- value_composite: PENDING (run in its validation grid).
- Ranking agreement (blend card): 5 grid points, Kendall tau 1.0, top choice (75/25) agrees, netted vs blend-of-nets Sharpes within 0.0002; OOS window 2017-02..2026-06 (113 months).
- Wall times (backtest only, shared/sleeping machine, upper bounds): momentum 1329 s, blend 25352 s, value 23373 s.

## Reconciliation with the old repo (15.7% / 0.96 / -19.7%): see README. Key A/B
- Engine at 7e904cd (pre-M08 merge) vs dc5356d on one cache copy: net returns identical (max abs diff 0.0). The merge is numerics-neutral.
- New vs the 12 Sept run: 1.6e-7 per period in all 173 periods; headline unchanged to 7 digits. Cause is data vintage: the price cache was rebuilt 2026-09-12 19:00-20:xx (after the old 17:18 run) and actions refreshed 09-13. Not separable further (old cache gone).
- Residual vs the old repo is NOT decomposable; reported as open.

## Findings fixed in this branch
1. Ranking agreement was never fed by the CLI. New `validation/netted_grid.py`; `validate --full`/`run` take `--child-result` and `--netted-grid-result "w1,w2=<dir>"`. Endpoints = standalone children (refused unless window/cost/semantics/params match); window = walk-forward OOS; each input's run dir + strategy id recorded; failures -> "not checked: <reason>" (also when no walk-forward is built).
2. Trials registry: re-recording an identical key left a stale first row beside the new series. Now the latest row supersedes (N unchanged, old rows kept in jsonl); row/series hash mismatch raises `RegistryCoherenceError`, checked per returned family. Live registry was moved aside to `reports/trials.bak_pre_cleanrun_2026-10-01` before the runs recorded.
3. Scan manifest: `refresh --unquarantine X` overwrote the manifest with just [X] (everything else became "never scanned"); a rewritten price file kept counting as scanned. Fixed (union on narrowed scan; `invalidate_scan_coverage` in the sidecar writer). Quarantine itself survives prefetch/refresh/clear-negative-cache (tests/test_quarantine_survival.py).
4. Sensitivity registry rows read `dirty=True` because `run` rewrites its own tracked `reports/<name>/` artefacts before recording. Rows now take the headline run's `provenance.dirty`. The 9 momentum sensitivity rows already recorded (2026-10-01 18:33) stay `dirty=True, registry_at_record_time`: the run started from a clean tree; the only dirt was its own artefacts.
5. Quarantine state was lost by the 2026-09-12 cache rebuild (all sidecars rewritten; no ordinary command does this). Pre-fix September grid trials ran on an unscanned cache; they are not in the current registry.
6. Minor: never-scanned caveat wording (names with no cached series cannot be scanned; live-run provenance carries the old wording), refresh-level negative-sidecar tests, 75/25 and 25/75 netted-grid configs, `.gitignore` now commits `provenance.json` (quarantine/no-data/never-scanned counts live only there).

## Carried items: see audit in the phase A report; item 13 suite time: 871 passed, 100 deselected, 70 s pytest-reported with value still running (budget 90 s; slow marker deselects 100).

## Verification
`uv run pytest` -> 871 passed, 100 deselected; `uv run ruff check` and `ruff format --check` clean (worktree, last run before the dirty-flag commit).

## Open questions
- The five blend-grid backtests are trials in the search but only the headline is in the registry (blend N=6). Record them? Orchestrator decision.
- Corporate-actions call count 1,010 per rebalance is design (membership probe plus per-context fetch); no baseline exists (counter new in M09).
- Value card, README value cells and the final suite timing remain for phase B.
