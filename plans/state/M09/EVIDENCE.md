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

## 5. Momentum: portfolio size vs the predecessor (quant-gate cycle 1, finding 1)
The predecessor holds 50 names (`MomentumValueStrategy/src/config.py` `top_n=50`); the QuantLab headline holds 30 (`configs/strategies/momentum_12_1.yaml`, `n_long: 30`). QuantLab's committed sensitivity grid contains lookback 12 / n_long 50 (registry trial `momentum_12_1-c993bc68ed`).

| | net CAGR | Sharpe | max DD | series hash (first 10) |
|---|---|---|---|---|
| predecessor (top 50, own data layer) | 15.7% | 0.96 | -19.7% | n/a |
| QuantLab grid point (12, 50) | 16.2899% | 0.9906 | -20.0879% | 9d6aa6d258 |
| QuantLab headline (12, 30) | 17.6532% | 0.9783 | -23.2508% | d02dafe6e9 |

Recompute (nothing is re-run; reads the git-ignored registry series): `uv run python plans/state/M09/recon_tables.py` from the repo root. Conventions: equity = cumprod(1+r) from 1.0, CAGR over n/12 years, Sharpe = mean/std(ddof=1)*sqrt(12), max DD from an equity curve that starts at 1.0. The card's 17.66% headline CAGR uses the card's own convention (it differs from the recomputed 17.65% by under 0.01 pp). Of the nine grid points the headline (12, 30) has the second-lowest Sharpe (grid range 0.968-1.022, from `reports/momentum_12_1/report_card.json` `basic.sensitivity.surface`). The predecessor's SPY figure (14.5%, quoted from the quant gate's comparison) is not reproduced here.

## 6. Value: three-way September comparison (quant-gate cycle 1, finding 2)
Series: 13 Sept headline `value_composite-b6fdfec048` (`reports/trials.bak_pre_cleanrun_2026-10-01/series/f22358628c03a714.parquet`, hash 3638bf89f9); 25 Sept grid point with the headline's own params `value_composite-b67309d696` (`.../cbc6db3a900b31e5.parquet`, hash dd28f8c2bd); final `reports/value_composite/net_returns.parquet`. Same script as section 5.

| run | net CAGR | Sharpe | 2012-19 | 2020 | 2021-22 | 2023+ |
|---|---|---|---|---|---|---|
| 13 Sept (unscanned, git 395bd98 dirty) | 17.62% | 0.9747 | 19.60% | 4.31% | 8.88% | 22.51% |
| 25 Sept (unscanned, same params, dirty tree) | 17.49% | 0.9701 | 19.63% | 3.71% | 6.52% | 23.65% |
| final 1 Oct (36 quarantined, clean dc5356d) | 17.19% | 0.9493 | 19.63% | 3.71% | 6.20% | 22.52% |

13 vs 25 Sept: 172 of 173 periods differ with the quarantine count unchanged (0). 25 Sept vs final: 39 periods differ, the first on 2021-09-30. The script also lists the 66 fundamentals files in `data/cache/fundamentals` first written 2026-09-23 00:29 to 2026-09-24 15:14 (after the 13 Sept run ended; names in the README). Their creation time equals their last-write time and fundamentals are fetch-once with no TTL; a force-refresh on those dates cannot be excluded, which would not change the finding that the facts changed after the 13 Sept run. The attribution of the 13 -> 25 Sept movement is UNRESOLVED.
