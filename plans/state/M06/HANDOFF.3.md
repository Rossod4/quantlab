# M06 handoff, iteration 3 (quant-gate REJECT -> all 6 blockers + items 7-9 fixed)

## Per-item status

**1 [blocker] DSR could rise with more trials - FIXED.** `TrialRecord` gained
`series_hash`; `registry.distinct_trials()` collapses same-hash records;
`n_trials()`/`var_sr_trials()` read the deduped view, `n_trials_raw()` keeps
the old per-key count for display. `var_sr_trials(family, n_periods)` floors
at `1/(n_periods-1)` (Lo 2002 null variance); `deflated_sharpe_ratio`'s
`SR*=0` shortcut is now `n_trials==1` only. False "conservative" claim
corrected. Regressions (test_trials_registry.py): 9-sibling case stays FAIL
after 15/40 cosmetic reruns; identical-Sharpe N=2/10/100 strictly decreasing.

**2 [blocker] RC undercounts trials - FIXED.** `build_trial_matrix` labels
columns by the full 3-part key (was `key[0]`), returns `(matrix, excluded)`;
`<2` guard runs on `matrix.shape[1]`. Test: 4 distinct keys -> K=4.

**3 [blocker] RC/SPA benchmark silently zero - FIXED.** New `ValidationConfig.
reality_check.benchmark: embedded|zero` (default embedded = same series
every other gate uses); `--benchmark` override always wins. Resolved source
printed in RC/SPA reasons + provenance.

**4 [blocker] purged CV inert/misnamed - FIXED per team-lead's naming.**
`cv_sharpe`/`PurgedCVResult` -> `subperiod_oof_sharpe`/`SubperiodOOFResult`;
docstring/gate/reason state it never reads training rows; `purged_kfold_
splits` kept for a future fitted strategy. Test: invariant to embargo/
label_horizon incl. a fully-leaky split. ESCALATE-TO-HUMAN design question
is the team lead's call, not mine to loop on; disclosure fix done here.

**5 [blocker] ELIGIBLE_FOR_PAPER unreachable via CLI - FIXED.** `--full` now
seeds historical trials (idempotent), runs the sensitivity grid via a real
engine-backed runner (`cli._make_sensitivity_runner`, monkeypatchable;
`sensitivity_enabled` config default True, `--no-sensitivity` flag) and
records every point, and runs `walk_forward_blend` when family=blend and
>=2 `--child-result` dirs given. Tests (pinned, not "one of three"):
eligible fixture -> ELIGIBLE_FOR_PAPER with zero failing gates; rejected
fixture -> REJECTED, both via CliRunner in test_cli_validate.py.

**6 [blocker] dirty flag never reached the report card - FIXED.** New
`ReportCard.provenance: ReportCardProvenance` (strategy_id, semantics
version, git sha, dirty/dirty_source, n_trials/n_trials_raw,
dirty_trial_count, RC trial count K, RC/SPA benchmark source, untrusted-
fraction line, Sharpe/Sortino convention) rendered in full in report_card.md.

**7 [done] p-value/calibration.** `(1+count)/(B+1)` in RC and SPA (never
exactly 0.0). Measured over-sizing at shipped `block_len=6.0` (~0.123 vs
nominal 0.10) documented in reality_check.py, with the `block_len=1.0`
control (~0.092) confirming the statistic itself is sound. Did NOT raise the
in-tree calibration test's simulation count - left open, not silently fixed.

**8 [done] `intended_capital_usd`.** New config field (default 1000, Alex's
real stake), replacing `initial_capital` (a different thing) as capacity's
denominator. Gate reason states the resolved dollar figure.

**9 [done, then TIGHTENED to true overlap] `min_overlap_fraction`.** New
config field (default 0.8). Replaced the length-ratio heuristic with an
iterative greedy overlap resolver (`reality_check._resolve_overlap`):
repeatedly removes whichever SINGLE trial's exclusion most GROWS the
group's common window, among ALL working trials (not only the ones
currently failing the floor - the true offender often shows 100%
self-retention and would never be flagged by its own fraction alone). Now
correctly handles two same-length, merely-offset windows plus an aligned
majority (excludes the offset one, majority keeps its FULL window) - the
case the length heuristic explicitly missed; tested directly. The
headline trial's own retained fraction is now surfaced in `ReportCard.
provenance.headline_retained_fraction` and printed in the markdown.

**10 [addendum, done] PSR missing the extreme-return caveat.** `_extreme_
return_caveat` now also appended to the `probabilistic_sharpe_ratio` gate's
reason (previously only DSR/MinTRL had it).

**11 [addendum, done] Sensitivity edge/nan flags not surfaced.**
`neighbourhood_size`/`neighbourhood_truncated`/`nan_points` now appended to
BOTH the `no_cliff_score` and `min_net_sharpe` gate reasons when a
sensitivity result is present.

**12 [addendum, done] RC/SPA p-value estimator.** Already `(1+count)/(B+1)`
from item 7 above; added a comment on the calibration test documenting why
(avoids an atom of mass at exactly 0.0 under the null) and confirming
`ks_p > 0.01` still holds empirically under the corrected estimator - full
suite re-run, unchanged pass.

**13 [addendum, done] Sharpe/Sortino convention in the markdown.** Added a
"Headline metrics" section to `_report_card_markdown` printing net CAGR/
max drawdown/Calmar/hit rate/Sharpe/Sortino with the ddof=1-annualised /
target-0-ddof=0 convention statement immediately beside them, not only in
the Provenance section.

**14 [pre-review addendum, done] Walk-forward child frequency mismatch.**
New `cli._check_child_rebalance_frequencies` compares each child's own
`rebalance_freq`; raises a clear `ValueError` naming the mismatched
frequencies BEFORE `walk_forward_blend` can silently intersect two
different-frequency children's dates into a meaningless blend.
`_build_walk_forward_result`'s existing try/except still degrades this to
"walk-forward skipped: <message>" + `None` rather than crashing `--full`,
but the message is now specific, not silence. Tests: direct raise on
mismatch, direct pass on match, and integration test confirming graceful
`None` degradation (not a crash, not a nonsense blend).

## Tests
`uv run pytest tests/ -q`: exit 0, 522 dots, ~17s (budget 90s). `ruff check`
/ `ruff format --check`: clean (97 files).

## Open items
VERDICT finding 8 (remaining markdown completeness beyond headline metrics/
provenance) not in scope. `_resolve_overlap`'s greedy algorithm is best-
effort (one candidate removed per iteration by largest-common-window gain),
not a global optimum, and can still fail loud (raise `<2 trials`) when two
trials mutually conflict with no majority to rescue - documented, not a bug.
