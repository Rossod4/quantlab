# M09 — End-to-end: `quantlab data`, one-command chain, docs, the real-data run

Goal: One command takes a strategy YAML from data refresh through backtest, full
validation, and report; the data layer gets its operational commands (prefetch, refresh,
invalidate); the repo gets a README that states what the platform does and what its
numbers mean; and the three real strategies (momentum_12_1, value_composite,
blend_50_50) are run on the prefetched 2012–2026 data with their report cards committed
under reports/. The expected honest outcome is that the gates REJECT or mark
RESEARCH_ONLY versus SPY — that is a correct platform output, not a failure, and the
handoff must say which it was and why in plain English.

## Sequencing note (2026-09-12)
M08 (paper trading) is NOT yet merged to main — it is escalated at the gate cap in the worktree
`..\quantlab-m08`. Do everything in this packet that does not depend on `src/quantlab/paper/`
first (data ops, `quantlab run`, README, the real runs and reconciliation, TTM EPS, the
carried M06/M07 items). The promotion-gating end-to-end check and carried item 8 (paper
drift check) are done LAST, after the orchestrator merges M08 into this branch — the
handoff must say whether that happened.

## In scope
- src/quantlab/data/ops.py + CLI `quantlab data prefetch [--start] [--end] [--universe
  sp500_history]` (formalises the 2026-09-11 scratchpad script: universe = every
  point-in-time constituent over the window + benchmark; prices, actions with
  fetched_at, EDGAR facts; per-ticker failure summary JSON), `quantlab data refresh
  [--tickers ...|--all] [--actions] [--prices] [--fundamentals]` (calls
  `refresh_actions_cache`, re-fetches prices past `requested_end`, clears expired
  negative-cache sidecars; QUANT-NOTES M01/M02b/M04 items), `quantlab data status`
  (cache coverage, oldest fetched_at, negative-cache count, masked truncations).
- CLI `quantlab run --strategy <yaml> --backtest <yaml> [--validation <yaml>] --out
  <dir>`: backtest → validate --full → report, with the trials registry updated and the
  three artefacts in one directory; exit code reflects the verdict (0 eligible, 2
  research-only, 3 rejected) so a scheduler can branch on it.
- Promotion gating wiring: `quantlab paper run` (M08) resolves the report card by
  strategy_id + data_semantics_version from reports_dir — verify end-to-end with the
  mock broker on a fixture that was marked ELIGIBLE by a fixture card.
- reports/ layout + `.gitignore` policy: report_card.json, validation_basic.json, the
  markdown report and the PNGs ARE committed for the three real strategies (small, the
  point of the project); parquet result series and HTML are not.
- README.md for quantlab (CV-grade, same standard as the old repo's README): what it
  is, the bias controls by construction, the loop that built it and what the gate caught
  (link the VERDICT files), how to run, the three real results with their verdicts and
  the caveats verbatim, what "REJECTED vs SPY" means, and the honest limitations (free
  data, ~13% invisible universe, TTM EPS share-terms residual, no live money).
- **The real run** (network tier is NOT needed if the cache is warm; run it as part of
  the milestone, not as a test): momentum_12_1_2012_2026, value_composite_2012_2026,
  blend_50_50_2012_2026 with `quantlab run`; record wall times; compare the momentum
  net CAGR / Sharpe / maxDD to the old repo's 15.7% / 0.96 / −19.7% and EXPLAIN every
  difference by mechanism (coverage, forced exits, adjustment replay, filing lag,
  netted-book blend costs, extreme-guard policy) in the handoff; unexplained
  differences are a finding for the gate, not a footnote.
- Post-M06 data follow-on folded in here (QUANT-NOTES M03b): per-component TTM EPS share
  terms — restate each summed quarter by the splits between ITS filed date and asof
  before summing (needs `_ttm_duration_with_latest_filed` to return components; additive
  provenance; frozen numerics when no split). Test: the gate's four-standalone-quarters
  straddling-split fixture now gives TTM EPS 4.0, not 10.0. Bump DATA_SEMANTICS_VERSION
  to "m09" and note that all pre-M09 registry trials are keyed on "m03b".
- tests: test_data_ops.py (offline with fake providers; negative-cache expiry; refresh
  updates fetched_at), test_cli_run.py (fixture end-to-end, exit codes), test_ttm_share_terms.py.

## Out of scope
Trading212 real adapter, Norgate provider, forward-vs-backtest drift dashboard (post-v1
backlog — list them in README as such).

## Context (read these, nothing else)
- This packet; CLAUDE.md; plans/QUANT-NOTES.md (every open item — this milestone closes
  the operational ones and must say which remain); plans/ORCHESTRATOR-HANDOFF.md
- src/quantlab/cli.py; src/quantlab/data/{cache,corporate_actions,pit}.py;
  src/quantlab/data/providers/{yfinance_prices,edgar_fundamentals}.py;
  src/quantlab/backtest/{engine,panel_store}.py; src/quantlab/validation/report_card.py;
  src/quantlab/reporting/render.py; src/quantlab/paper/runner.py; the old repo README
  (C:\Users\arwga\Developer\ClaudeProjects\Trading\MomentumValueStrategy\README.md) as
  the style reference; the orchestrator's prefetch script for the universe logic
  (plans/M04b-engine-perf.md describes it).

## Acceptance criteria
1. `uv run pytest` green offline; ruff clean; the three real runs complete on the warm
   cache and their cards + markdown reports are under reports/.
2. `quantlab run` exit codes match verdicts on fixtures.
3. Data ops: prefetch is idempotent; refresh clears a planted stale actions cache and an
   expired negative sidecar; status reports the counts.
4. TTM EPS per-component restatement passes the gate fixture; no-split parity unchanged.
5. README complete; every number in it traceable to a committed report file.
6. Handoff contains the three one-liners, the verdicts, and the mechanism-by-mechanism
   reconciliation against the old repo's momentum result.

## Verification commands
- `uv run pytest tests/ -q`; `uv run ruff check`; `uv run ruff format --check`
- `uv run quantlab data status`; `uv run quantlab run --strategy configs/strategies/
  momentum_12_1.yaml --backtest configs/backtests/momentum_12_1_2012_2026.yaml --out reports/momentum_12_1`

## Carried from the M04b verdict (binding — see the worktree's plans/QUANT-NOTES.md "From M04b verdict")
1. `quantlab data scan` exposes M04b's `scan_price_cache` (quality gate + zero-volume +
   unexplained-jump + symbol-reuse detectors); `quantlab data status` lists quarantined
   tickers with reasons; `quantlab data refresh --unquarantine <ticker>` re-fetches and
   re-scans one name. The three real runs are made only on a scanned cache and the report
   states the quarantined count.
2. `quantlab data refresh --clear-negative-cache [--tickers]` force-clears no_data sidecars.
3. Provenance records `retry_after_days` and the count of no_data-suppressed and
   quarantined tickers (the TTL makes runs wall-clock dependent; say so in the README).
4. The reconciliation of the momentum number against the old repo must list which M04b
   mechanisms could not have moved it (window clamp, benchmark-from-store) and which did
   (symbol-reuse quarantine), with the before/after one-liners.

## Carried from the M06 verdict (cycle 3) — binding
5. `build_trial_matrix` → `load_series`: a missing or corrupt series parquet raises OSError,
   which escapes report_card.py's `except ValueError` and crashes `validate --full`. Guard
   it: degrade to a failed Reality Check gate with the reason naming the trial and path.
   Test with a planted missing sidecar.
6. **Capacity gate — DECIDED by the orchestrator (Alex's stake is £100–500):** keep
   `intended_capital_usd: 1000` and DEMOTE the capacity gate from soft to `informational`
   in configs/validation.yaml (a new gate class that is always reported with its value,
   the AUM ceiling, the spread percentiles and the old repo's $95M–$335M context, but
   never affects the verdict). The README and report say why: at retail scale capacity is
   not a constraint, and a green badge would imply an edge it does not evidence. If Alex
   later trades institutional size, flip it back to soft in config.

## Carried from M07 (binding)
7. `validation/walk_forward.py`: retain per-step training Sharpes in `WalkForwardResult`
   (additive field) and compute the "ranking agreement under both cost conventions" check
   for blends — rank the grid points by Sharpe under (a) blend-of-net-returns and (b) the
   engine's netted-book costing on the real blend run, report Kendall tau and whether the
   top choice agrees. The M07 report's "not checked" line then reads the real result.
   Frozen numerics of the ported walk-forward unchanged (parity test still passes).

## Carried from the M08 verdict (binding — see plans/QUANT-NOTES.md "From M08 verdict")
8. Forward-vs-backtest drift check (post-v1 dashboard stays post-v1, but the CHECK lands
   here as a CLI `quantlab paper drift --strategy ...`): compare each journaled paper
   rebalance's targets with the backtest engine's targets for the same asof on the same
   data, and model the paper timing convention explicitly (decide at the previous completed
   session, fill at the next open ≈ 1.5 sessions after the backtest's close convention);
   report target-weight agreement, fill-vs-model price gap, and per-ticker data-asof lag
   from the journal (M08 iteration 2 adds these fields). journal_to_frame must expose
   promoting_report_card, known_caveats, refreshed_actions_tickers and targets.
9. Canaries: keep the extended canary (k) (asof ≤ last cached bar) and record the
   `object.__setattr__(ctx, "_accounting", True)` residual as a documented, unguardable
   Python limitation in the README's limitations section — no further code.
10. Cosmetic (M07 review nit): `_provenance_section`'s cache_dir fallback string carries a
    bare apostrophe that renders as `&#39;` in HTML; reword or Markup-wrap it.
11. report_card.py's min_track_record_length gate-reason prose still says "inf" when the
    length is unbounded; format it as "unbounded" at the source (M07 could only fix its
    own formatting of the number).
12. Cosmetic (M07 gate): a NaN sensitivity cell renders "excluded" three times (formatter
    reason + template suffix); de-duplicate.
13. Suite time: the offline suite is at ~80 s against a 90 s budget. M09 must keep it under
    90 s — prefer a `slow` marker for the largest bootstrap tests (deselected by default,
    run in CI nightly) over shrinking test coverage.
