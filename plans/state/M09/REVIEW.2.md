VERDICT: APPROVE

M09 iteration 2 review. Branch m09-end-to-end, HEAD a7a6519. All 12 findings from REVIEW.md re-checked by re-running my own mutations and re-deriving the numbers, not from HANDOFF.2.md. Counts: 0 blocker, 0 major, 3 minor (new, non-forcing).

## Measured

- Default suite: all passed, 1m26s wall (includes `uv run` startup), on AC (BatteryStatus 2, 56% charge), nothing of mine running; the developer reports 899 passed. Under the 90 s budget with a thin margin; I did not re-run the slow tier (no slow-tier code changed except new default-tier tests).
- `uv run ruff check` clean; `uv run ruff format --check`: 136 files already formatted.
- `git status --short` before this file: empty.

## Closure of the 12 findings (mutations re-run, each reverted)

1. TTM post-asof quarter (`as_of_date + 3650d` in `_ttm_duration_components`): now FAILS 4 of 4 cases of the new canary `test_canary_future_filed_quarter_and_future_split_have_zero_effect_on_ttm_eps` (provider and panel_store modes, no_split and future_split). Closed.
2. Drift `asof=_asof + 30d`: FAILS `test_drift_recompute_context_is_bound_to_each_journaled_asof` and the blend-children variant. Closed.
3. Promotion gate: `strategy_id` to `True` fails 2 tests (`test_runner`, `test_cli_paper`); `data_semantics_version` to `True` fails 2; accepting REJECTED fails 2. Closed.
4. Exit code always 3: fails `test_run_exits_with_the_code_for_each_verdict[ELIGIBLE_FOR_PAPER-0]` and `[RESEARCH_ONLY-2]` in the default tier. Closed.
5. Base point: `_build_sensitivity_result` now passes the headline params and refuses off-grid or missing axes. Momentum card/report show "Base point: lookback_months=12, n_long=30", neighbourhood_size 6, truncated True. Closed (see minor 1).
6. README value text names the three hard failures and states drawdown is context only. Closed.
7. Paths: `core/paths.portable_path` used in ranking run dirs and report provenance; `reports/*/provenance.json` are no longer tracked (`git ls-files reports | grep provenance` is empty). Only `reports/value_composite/report_card.md:176` still carries `C:\Users\arwga\...`; the developer discloses this (value's card stays as produced). Closed, residue disclosed.
8. README recipe now lists the three `quantlab backtest` commands from committed configs, `--record-trial` and the report step; strategy YAML headers corrected; strategy ids unchanged (blend-a7f7c30ce1 / blend-9231a3894e). Closed.
9. Suite time: 1m26s on AC as measured above; battery figures (2m00s earlier) remain over budget, as the handoff states. Closed with the same caveat.
10. `plans/state/M09/EVIDENCE.md` plus `validated_by_git_sha` / `validated_by_dirty` on the cards. Verified from files that exist: final momentum `net_returns.parquet` float64 SHA-256 starts `d02dafe6e969581a` (173 periods); the September series in `reports/trials.bak_pre_cleanrun_2026-10-01/series/082067b4935a354b.parquet` hashes to `270cf1b07abd7d45` and its max absolute difference from the final series is 1.6158e-7, as the note states. Not independently verifiable by me: the 7e904cd A/B (worktree no longer exists) and the 42-to-36 ticker list (the old provenance was overwritten); both are described with commands and, for the A/B, a shared hash. Closed.
11. Prefetch `start_ts` instead of `_EPOCH`: FAILS `test_prefetch_requests_actions_from_the_epoch_not_from_the_window_start`. Closed.
12. min-TRL "inf" instead of "unbounded": FAILS `test_unbounded_min_track_record_length_is_worded_unbounded_never_inf`. Closed.

## Card checks

- Momentum card (re-validated, `validated_by_git_sha` 8eb8ce1, `validated_by_dirty` False): diffed against 022bb28 by JSON path. Changed: `base_point.n_long` 50 to 30, `neighbourhood_size` 9 to 6, `neighbourhood_truncated` False to True, `no_cliff_score` 0.9452 to 0.9720 (gate value and reason text), one added truncation flag, `dirty_trial_count` 9 to 0 with the corresponding dirty-trial caveat dropped (known_caveats 7 to 6; correct, the sensitivity rows are now dirty=False), and the two new provenance fields. Every other gate value, verdict, N=9 and K=10 identical. `validation_basic.json` differs only in the sensitivity block.
- Blend card (`validated_by_git_sha` 212159c, dirty False): diff is the two new provenance fields and the five `ranking_agreement.inputs[].run_dir` values, now repo-relative. Values, verdict, N=8, K=3 unchanged. `validation_basic.json` identical.
- Value card and `validation_basic.json`: byte-identical values to 022bb28.
- README numbers still trace: the README never quoted momentum's no-cliff number; wall times map to the "Run seconds" row present in all three `report.md` and `report_card.md` (1328.84 / 23373.25 / 25352.39); call counts map to EVIDENCE.md section 4, which matches the figures I read from the (ignored) provenance files in iteration 1.

## Minor findings (do not force REVISE)

1. `README.md:229` says momentum "passes ... the no-cliff sensitivity gate" without noting that the score is now computed on a truncated 6-point neighbourhood (n_long=30 is the grid edge), which mechanically flatters it. The card and report disclose it (flag and gate reason); the README should carry one clause, since it is the CV-facing document.
2. The 7e904cd-vs-dc5356d A/B in EVIDENCE.md section 1 cannot be re-verified from the repository (worktree and its copied cache are gone); the final and September series hashes it cites do verify. Acceptable, but keep the wording "reported by the developer" rather than "verified" in any later summary.
3. Suite time margin is thin (86 s wall vs 90 s budget on AC); on battery it is about 2 min. Tracked, not blocking; the largest `test_walk_forward` / `test_netted_grid` fixtures are the candidates for `slow` if the budget is enforced strictly.
