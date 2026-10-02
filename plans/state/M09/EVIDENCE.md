# M09 evidence note (what the README and HANDOFF cite but the committed reports cannot show)

All run on 2026-10-01 on one machine; "final" = `reports/momentum_12_1/` at clean commit dc5356d.

## 1. Is the M08 merge numerics-neutral? (A/B at 7e904cd vs dc5356d)
- 7e904cd is the last M09 commit BEFORE main (M08) was merged (f555dd5 is the merge); dc5356d is the commit the real runs used.
- Setup: `git worktree add --detach <dir> 7e904cd`, `uv sync --extra paper` there, a COPY of `data/cache` (so the shared cache could not be written), and a platform YAML with absolute `cache_dir`/`reports_dir` pointing at the copy.
- Command (in the 7e904cd worktree): `uv run quantlab backtest --platform <platform.yaml> --config configs/backtests/momentum_12_1_2012_2026.yaml --out <out_dir>`.
- Result: net CAGR 17.66%, Sharpe 0.98, maxDD -23.25%, 36 quarantined, clean sha.
- Comparison of `net_returns.parquet` (173 monthly periods, same index):
  - 7e904cd vs final (dc5356d): max absolute difference **0.0**, 0 of 173 periods differ. SHA-256 of the float64 values: both `d02dafe6e969581a...` (first 16 hex digits).
  - 7e904cd vs the 12 Sept run (git 395bd98, dirty; series hash `270cf1b07abd7d45...`): max abs diff **1.6158e-7**, all 173 periods differ (about 1e-8 to 1e-7 each).
- Conclusion: the merge and engine extraction change nothing; the 1.6e-7 is data vintage between 12 Sept and 1 Oct. Two candidate causes cannot be separated (the 12 Sept cache is gone): the full price-cache rebuild on 2026-09-12 19:00-20:xx (776 price sidecars and 644 parquets all rewritten in that window, per file mtimes) and the corporate-actions refresh of 2026-09-13 (old run's `actions_cache_fetched_at` was 2026-09-11, new 2026-09-13).
- The same engine-equivalence assumption for blends is pinned by `tests/test_blend_endpoint_equivalence.py`.

## 2. Quarantine count 42 -> 36 and "six now have no cached series"
- The September momentum card committed at dc5356d (`git show dc5356d:reports/momentum_12_1/report_card.json`, known_caveats) states "42 historical constituent(s) ... quarantined".
- Its ticker list was in the (uncommitted, since overwritten) run provenance. Comparing that full list with the post-scan `quantlab data status` list on 2026-10-01 gave: in the old list only = AVB, BBBY, CSRA, EA, EQR, LEG; in the new list only = none (so 36 of the 42 were re-quarantined by the scan). After the rebuild and before that scan, the cache had 0 quarantined and no scan manifest.
- The six no longer quarantined (AVB, BBBY, CSRA, EA, EQR, LEG) have no price parquet and a `no_data` sidecar (`fetched_at` 2026-09-12): the rebuild's re-download returned zero rows for them, which overwrote their sidecars. They are still invisible to every strategy (a `no_data` ticker is served empty), so numerics are unaffected; they sit in the 168-name negative cache.
- Reproduce the status: `uv run quantlab data status` (prices 644, actions 811, fundamentals 609, no_data 168, quarantined 36, masked truncations 18, never scanned 0).

## 3. Netted-grid backtests (75/25 and 25/75)
Not committed (about 7 h each). Regenerate with the commands in README "How to run it"; the committed `configs/backtests/blend_{75_25,25_75}_2012_2026.yaml` and `configs/strategies/blend_{75_25,25_75}.yaml` give strategy ids blend-a7f7c30ce1 and blend-9231a3894e. The runs recorded in `reports/blend_50_50/report_card.json` used byte-identical strategy YAML content from a scratch directory (same ids); their Sharpes and ids are in that card's `ranking_agreement` block.

## 4. Run-level provenance (the uncommitted `reports/<name>/provenance.json`, copied here because the committed cards carry only the counts in prose)

| run | backtest s | provider calls (constituents / corporate_actions / fundamentals / price) | total | network price fetches | quarantined | no_data suppressed | never scanned (universe) | retry_after_days | sha | started (UTC) |
|---|---|---|---|---|---|---|---|---|---|---|
| momentum_12_1 | 1328.8 | 348 / 174739 / 0 / 174 | 175261 | 0 | 36 | 168 | 168 | 30 | dc5356d | 2026-10-01T08:51:11 |
| value_composite | 23373.2 | 348 / 174739 / 86964 / 13950 | 276001 | 0 | 36 | 168 | 168 | 30 | dc5356d | 2026-10-01T15:36:59 |
| blend_50_50 | 25352.4 | 521 / 261703 / 86964 / 14123 | 363311 | 0 | 36 | 168 | 168 | 30 | dc5356d | 2026-10-01T16:09:57 |

The 'never scanned' count is the no_data names (no cached series, so nothing to scan); `quantlab data status` reports 0 never scanned among cached tickers. The two netted-grid runs share the blend's call counts (same universe and fundamentals access).
