REVIEW: APPROVE

## Verification performed

- `uv run pytest tests/ -q`: exit 0, 213 dots, no failures.
- `uv run ruff check` / `uv run ruff format --check`: clean, 51 files formatted.
- Independent signal parity: ran the OLD repo's `compute_momentum_signal`,
  `select_top_n`/`select_bottom_n`, `compute_value_ratios`,
  `compute_composite_score`, and `select_top_n` directly (via `sys.path`
  insertion into `MomentumValueStrategy`, not by reading the packet's own
  parity test) against the new plugins on shared fixtures (3-ticker
  momentum panel; 4-ticker value fundamentals including a loss-maker and a
  bank with no EBITDA). All outputs matched to `1e-10` (exact string/float
  equality in most cases). Confirms the packet's own hard-coded-golden-number
  parity file is not the only evidence of parity.
- Mutation-tested both canaries myself (not just re-read the handoff's
  claim):
  - Momentum: switched `_month_end_prices` to pivot on `raw_close` instead
    of `close` -> `test_momentum_score_across_nvda_style_split_is_flat_for_flat_value_stock`
    failed with score `-0.9` (matches HANDOFF.md's reported failure mode).
    Reverted; suite green again.
  - Filing-lag: switched `_fundamentals_effective_asof`'s stepping from
    `prev_trading_day` to `next_trading_day` -> `test_canary_increasing_filing_lag_only_ever_narrows_visible_filings`
    failed, returning `[300.0, 300.0, 300.0, 300.0]` instead of
    `[300.0, 200.0, 100.0, None]` (matches HANDOFF.md). Reverted.
  - `git diff --stat -- src` after both mutation/revert cycles: `pit.py |
    43 ++++++++++++++++++++++++++++++++++++++++---, 1 file changed, 40
    insertions(+), 3 deletions(-)` — identical to the pre-mutation state;
    `momentum.py` diff empty. No production code left modified.
- Read every changed/new file in full: `data/pit.py` diff,
  `strategies/{base,registry,momentum,value,blend}.py`, both canary/parity
  test files, `test_strategy_base.py`, `test_registry.py`,
  `test_momentum_strategy.py`, `test_value_strategy.py`, `test_blend.py`,
  and all five `configs/strategies/*.yaml`.

## Checks against the team-lead's specific concerns

1. **`filing_lag_sessions` cannot loosen the gate.** Confirmed by code
   (`_fundamentals_effective_asof` raises `ValueError` for negative, and
   `filing_lag_sessions=0` reduces to the untouched
   `_last_session_on_or_before(asof)`) and by test
   (`test_filing_lag_zero_matches_the_pre_extension_default_gate` diffs
   the explicit-0 and no-argument call paths). Confirmed the reverse-mutation
   canary above. `prices()` is untouched (verified: only `fundamentals()`'s
   signature and body changed).
2. **Value composite pairs price levels with filings correctly.** Confirmed:
   `_asof_raw_price` reads `ctx.prices([ticker], 1)["raw_close"]` (the
   single most-recent/asof row, true traded price), never `close` history
   and never a per-share filing figure combined with an adjusted historical
   close. Matches the carried item and is exercised by
   `test_asof_raw_price_uses_the_current_row_not_a_stale_pre_split_row`.
3. **No strategy touches `prices_for_returns()` or `volume`.** Confirmed by
   grep across `src/quantlab/strategies/`: the only hits are in `base.py`'s
   docstring prohibiting exactly this; no plugin calls either.
4. **`generate_targets` is pure.** Confirmed by direct test in each of
   `test_strategy_base.py`, `test_momentum_strategy.py`,
   `test_value_strategy.py`, `test_blend.py` (call twice, compare
   `TargetWeights` equality; also a params-not-mutated check in
   `test_strategy_base.py`).
5. **Weight sums per acceptance criterion 5.** Confirmed:
   `test_long_only_selects_winner_and_sums_to_one` (sum ~1.0),
   `test_long_short_is_dollar_neutral_gross_two` (sum ~0.0, gross 2.0),
   `test_130_30_nets_one_gross_sixteen_tenths` (net 1.0, gross 1.6).
6. **`strategy_id` stability and registry error path.** Confirmed:
   `test_strategy_id_stable_for_same_params`/`_changes_with_params` in
   `test_strategy_base.py`; `test_load_strategy_unknown_name_raises_and_lists_known_names`
   in `test_registry.py` asserts both the bad name and a known name appear
   in the message.
7. **Every YAML round-trips.** Confirmed:
   `test_every_config_yaml_round_trips` is parametrized over all five
   configs in `configs/strategies/`, asserting the right concrete type and
   a non-empty `strategy_id`.

## Findings (minor only; none block approval)

1. (minor) `configs/strategies/value_composite.yaml:2-4` — stale comment.
   It reads "filing_lag_sessions is DECIDED-default 1 ... but currently
   unenforceable - see strategies/value.py's module docstring and
   plans/state/M03/HANDOFF.md for the escalation." That escalation is
   resolved in this same milestone (HANDOFF.md's "Open questions: None
   blocking"; `PITDataContext.fundamentals(..., filing_lag_sessions=)` is
   implemented and tested) — the parameter is now enforced. Fix: update or
   delete this comment so a future reader isn't told the default is inert
   when it is not.
2. (minor) The M02b-carried item 1 text asks for "a test that the value
   composite on a fixture spanning a split gives the same score as the
   hand computation using raw price x filing-in-force" as one scenario.
   What's actually written is two narrower tests instead: `_asof_raw_price`
   is unit-tested directly across a split
   (`test_asof_raw_price_uses_the_current_row_not_a_stale_pre_split_row`,
   `tests/test_value_strategy.py:228`), and the composite ranking math
   itself is pinned separately in `tests/parity/test_signal_parity.py`
   against hand-derived numbers (no split in that fixture). Composing the
   two gives equivalent assurance — confirmed independently by my own
   parity run above — but there is no single end-to-end
   `generate_targets`-level test exercising a split-spanning fixture
   through the full ratio/rank/select pipeline. Suggest adding one in a
   follow-up if this exact scenario needs a standing regression test,
   but not a blocker given the equivalent coverage already in place.
3. (minor, performance/efficiency, out of packet scope) `strategies/value.py`'s
   `_asof_raw_price` is called once per ticker inside a Python loop in
   `ValueStrategy.generate_targets`, each issuing its own
   `ctx.prices([ticker], 1)` call rather than a single batched
   `ctx.prices(tickers, 1)`. Not a correctness issue (declared lookback is
   honored either way) and immaterial at M03 scope; worth a look if
   provider round-trip cost matters once M04 wires in a real backtest loop.

## Verdict

APPROVE. All seven acceptance criteria are met and independently verified
(not merely re-read from the handoff), the orchestrator-authorised
`filing_lag_sessions` extension is genuinely restrict-only, both canaries
are real (fail under mutation, pass otherwise), and parity holds to 1e-10
against the old repo's own functions run directly. The three findings above
are minor documentation/coverage/performance notes, not corrections the
developer must make before this milestone can close.
