REVIEW: APPROVE

# M05 Validation I — Code Review

## Verification (run myself)
- `uv run pytest tests/ -q`: exit 0, 398 dots, 0 failures.
- `uv run ruff check`: all checks passed.
- `uv run ruff format --check`: 79 files already formatted.
- `uv run quantlab validate --help`: OK, matches packet's basic-tier CLI.
- Independently re-ran the OLD repo's own `tests/test_metrics.py` and
  `tests/test_walk_forward.py` fixtures through the NEW `quantlab.validation`
  functions (not the checked-in parity tests — a separate script importing
  both trees and asserting to 1e-12): all pass, 0 diffs.

## Findings

1. (info) `metrics.py`'s ported `cagr`/`annualized_vol`/`sharpe_ratio`/
   `max_drawdown` are byte-for-byte identical in logic to
   `..\MomentumValueStrategy\src\evaluation\metrics.py` (only docstrings
   were trimmed of old-repo-specific phrasing). `rolling.py`'s
   `rolling_window_metrics` is likewise identical to the old
   `walk_forward.py`'s function of the same name, built on an equivalent
   `standard_metrics`/`_window_metrics` helper. No numeric drift.
2. (info) Both parity test files (`tests/parity/test_metrics_parity.py`,
   `test_walk_forward_parity.py`) import the old repo's functions via
   `sys.path` insertion rather than re-implementing/hard-coding expected
   values — confirmed by reading both files. This is one of the two
   approaches the packet explicitly allows, and is the stronger of the two
   (numeric drift in either tree is caught automatically).
3. (info) Ran the old repo's own `tests/test_walk_forward.py` fixtures
   (`test_walk_forward_picks_dominant_sleeve`,
   `test_walk_forward_picks_other_sleeve_when_dominance_flips`, the partial-
   final-block and common-dates-alignment fixtures) through the new
   N-sleeve `walk_forward_blend` with the legacy 5-point 2-sleeve grid:
   `oos_returns` and `chosen_weights` match the old scalar implementation
   exactly (1e-12) in all four shapes, including the dominance-flip case
   the team-lead specifically called out.
4. (info) `periods_per_year` is a required, explicit argument on every
   metric function and is never derived from a series' own index/frequency
   anywhere in `metrics.py`, `rolling.py`, or `walk_forward.py` (confirmed
   by reading all three modules top to bottom). `summary()` and
   `sensitivity_grid()` both read it from `PERIODS_PER_YEAR[result's
   rebalance_freq]` (provenance / `BacktestConfig`), never from the data.
   The mapping (`daily`→252, `weekly`→52, `month_end`→12, `quarter_end`→4)
   matches the packet's own listing; `quarter_end` is dead but harmless
   since `core/calendar.py`'s `RebalanceFreq` Literal doesn't currently
   emit it — confirmed by reading `calendar.py:20`.
5. (info) New metrics hand-checked against their docstrings:
   `sortino` = annualized mean / annualized downside deviation (target 0);
   `calmar` = CAGR / |max drawdown|, NaN on zero drawdown;
   `hit_rate` = fraction of strictly-positive periods;
   `tracking_error`/`information_ratio`/`beta` all common-dates-align first,
   matching the old repo's `blend_returns` alignment convention;
   `cost_drag_cagr` = gross CAGR − net CAGR, an exact match for the old
   repo's `comparison.py` "Cost Drag (CAGR)" row. All formulas are standard
   and match their docstrings; the shipped hand-computed tests in
   `tests/test_metrics.py` reproduce the same arithmetic independently.
6. (info) Carried M04-verdict items: `metrics.summary()` reads only
   `net_returns`/`gross_returns`/`net_equity`/`gross_equity`/`turnover`/
   benchmark series — confirmed by reading the function body, and
   `test_summary_does_not_touch_snapshots` (using an `Exploding()` sentinel
   that raises on any attribute/item access) passes. `_quality_flags()` in
   `basic.py` reports `forced_exits`, `extreme_returns_long`,
   `extreme_returns_short`, `unscored_by_date`, `dropped_tickers_by_date`
   exactly once each and never mentions `missing_forward_prices` — verified
   by reading the function and by `test_validate_basic_reports_each_
   quality_counter_once` / `test_validate_basic_omits_zero_quality_
   counters`. The coverage-bound flag text combines the bound with the
   unscored/dropped counts and states "SEPARATE selection effects", per the
   binding wording. `tests/canaries/test_no_prices_for_returns_in_
   strategies.py` includes `test_canary_detects_a_planted_violation`, which
   proves the AST scan actually fires on a planted `ctx.prices_for_returns(
   ...)` call rather than only currently finding nothing — satisfies "canary
   fails under mutation".
7. (info) Sensitivity: independently recomputed `no_cliff_score` by hand for
   both shipped tests. Flat case: three identical-Sharpe neighbours →
   median = spread = 0 → score = 1 (matches `pytest.approx(1.0)`). Planted
   1-D cliff case (`lookback_months` 15 flips sign): neighbourhood Sharpes
   are `{+S, +S, −S}` → median `S`, spread `2S` → score `1 − 2 = −1`, well
   below the test's `< 0.5` bound. Definition in code matches its own
   docstring. `_strategy_id_for_point` hashes the full per-point param dict,
   giving a distinct id per grid point (confirmed by the 3- and 6-point
   trial tests asserting distinct id counts). `grep -n "run_backtest"
   src/quantlab/validation/sensitivity.py` returns nothing — the injected
   `runner` is the only way a backtest-shaped call happens; no real
   strategies/engine import exists in the module.
8. (minor) `configs/validation.yaml`'s `thresholds` block is read by
   `ValidationConfig.thresholds: dict[str, Any]` and exercised only by
   `test_load_validation_config_parses_shipped_config`
   (`config.thresholds["min_net_sharpe"] == 0.3`); a repo-wide grep confirms
   no threshold value is hard-coded anywhere else. Satisfies the packet's
   "gates are config not code" requirement for M06. No action needed now —
   noted only because M06 will be the first real consumer and should keep
   reading through this same model rather than re-parsing the YAML.
9. (minor) HANDOFF deviation 6: the carried M04-verdict wording ("any
   nonzero count must appear in the one-line summary and in
   `ValidationBasic.flags`") is satisfied for `ValidationBasic.flags`
   (finding 6 above), but the `quantlab validate` CLI's own one-line summary
   (`cli.py`, the `net CAGR=... Sharpe=... hit_rate=...` line) does not
   include `extreme_returns_long/short` — the developer's documented
   reasoning is that M04's `backtest` CLI already prints the combined
   `extreme_returns` count on its own one-liner (confirmed at
   `cli.py:104`: `extreme_returns={qf.extreme_returns}`). That earlier
   one-liner (a) only ever shows the combined count, not the per-book
   long/short breakdown the carried item's parenthetical calls out by name,
   and (b) may not be visible to whoever later runs `quantlab validate` on
   a result saved in an earlier/different session. The information is not
   lost — it appears immediately below the metrics line, every time,
   because `_quality_flags` always includes it in `ValidationBasic.flags`
   and the CLI echoes every flag — so this is a polish gap, not a
   correctness or visibility failure, and not worth blocking approval over.
   Recommend M06 (or a follow-up) add the per-book counts to `validate`'s
   own one-liner when nonzero, to fully discharge the packet's literal
   wording.
10. (info) The other four/five HANDOFF deviations are all sound and
    correctly scoped:
    - `validate_basic`'s keyword-only precomputed `walk_forward`/
      `sensitivity` args: correct call — those two need inputs (per-child
      return series; an injected runner) a single `BacktestResult` cannot
      supply, and the packet's three positional args are honored exactly.
    - Adding `tests/parity/test_walk_forward_parity.py` beyond the packet's
      literal "In scope" file list: required by acceptance criterion 3;
      not adding it would leave that criterion unverified.
    - `summary(result, benchmark_result=None)`'s extra optional kwarg:
      `summary()` is a new-for-M05 function, not one of the frozen ported
      functions the "Interfaces to honor" section restricts, and the
      default preserves the packet's literal single-argument call.
    - `PERIODS_PER_YEAR["quarter_end"] = 4` is not actually a deviation —
      the packet's own prose lists `quarter_end → 4` explicitly; it is
      simply unreachable today given `RebalanceFreq`'s current Literal.

## Deviations from packet wording — verdict
Accept all six documented in `plans/state/M05/HANDOFF.md`. None weaken a
frozen numeric, none touch `BacktestResult`, and each is justified by an
information a single positional argument genuinely cannot carry (child
sleeve series, an injected runner) or by a scope boundary the packet itself
draws (ported vs. new functions). Finding 9 above is the one place a
deviation's real-world coverage is slightly short of the letter of a
carried item, but it is minor and does not affect correctness, determinism,
or test rigor.

## Items 1–8 (team-lead checklist) — summary
1. Frozen numerics: identical logic; both parity tests import the old repo
   via `sys.path`; independently reran the old repo's own metrics and
   walk-forward test fixtures against the new code to 1e-12 — all pass.
2. Walk-forward N-sleeve generalisation: dominance-flip fixture reproduces
   the old chosen-weight sequence and oos_returns exactly (checked via the
   shipped parity test and independently).
3. `periods_per_year`: never inferred from data anywhere in the module;
   `RebalanceFreq` mapping correct; `quarter_end` entry is dead but
   harmless and matches the packet's own listing.
4. New metrics: all seven hand-check clean against their docstrings.
5. Carried items: snapshots-untouched sentinel passes; each quality flag
   reported exactly once; `missing_forward_prices` excluded;
   coverage-bound + unscored/dropped combined with the required "separate
   selection effects" wording; AST canary has its own fires-under-mutation
   test.
6. Sensitivity: `no_cliff_score` matches its docstring by hand-computation;
   planted cliff low, flat surface ≈1; trials have distinct `strategy_id`s
   per grid point; `runner` is never bypassed (no `run_backtest` import in
   the module).
7. Five/six deviations: all accepted, with one minor caveat (finding 9).
8. `configs/validation.yaml`: thresholds present for M06, read only through
   `ValidationConfig`, never hard-coded.
