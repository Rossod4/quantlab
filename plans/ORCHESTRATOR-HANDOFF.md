# Orchestrator Handoff — read this first, then resume the loop

You are the project orchestrator for QuantLab. Your predecessor (a Claude Fable 5
session) built M00–M02 through the subagent loop defined in plans/PROTOCOL.md. Your
job is identical: run the developer → code-reviewer → quant-gate loop per milestone,
merge on ACCEPT, escalate to Alex only at genuine human touchpoints. **You do not
implement milestone code yourself** — the loop does; you write packets, dispatch
agents, enforce the protocol, and carry gate findings forward.

## Current state (2026-09-11, afternoon)

| Milestone | State |
|---|---|
| M00 core scaffold | ✅ merged to main |
| M01 data providers | ✅ merged to main |
| M02 PIT core | ✅ merged to main (141 offline tests green on main) |
| M02b adjustment replay | ✅ merged to main 2026-09-11 (163 offline tests green; gate REJECT→ACCEPT; carried items in QUANT-NOTES) |
| M03 strategy framework | ✅ merged 2026-09-11 (213 tests; filing-lag restrict-only extension; gate ACCEPT) |
| M03b share terms | ✅ merged 2026-09-11 (227 tests; per-share fundamentals restated over (filed, asof]; canonical blend id; gate ACCEPT) |
| M04 backtest engine | ✅ merged 2026-09-11 (329 tests; gate REJECT→ACCEPT; 5 accounting bugs fixed; accounting=True gate) |
| M05 validation I | ✅ merged 2026-09-11 (416 tests; gate REJECT→ACCEPT; sub-period first-return bug fixed) |
| M06 validation II | ✅ merged 2026-09-12 (gate ACCEPT cycle 3 after Alex approved a third cycle; PSR/DSR footing, headline pinning, honest subperiod_oof_sharpe) |
| M07 reporting | ✅ merged 2026-09-12 (735 tests; gate REJECT→ACCEPT; four rendered verdict fixtures) |
| **M09 end-to-end** | ✅ **ACCEPTED 2026-10-04** (gate cycle 2) and merged to main (912 tests; loop: 3 dev iterations + prelim review, review REVISE/APPROVE/APPROVE, gate REJECT→ACCEPT). All three real runs made from clean sha dc5356d on a scanned cache with a fresh trials registry: momentum 17.66%/0.98/−23.25%, value 17.19%/0.95/−34.75%, blend 50/50 17.67%/1.03/−28.36% — **all REJECTED** (net Sharpe < SPY 1.06; coverage bound 28.4% > 15%; momentum and blend also fail the Reality Check). Reconciliation vs the old repo: portfolio size (50 vs 30 names) explains most of the gap — see README and `plans/state/M09/EVIDENCE.md`. **v1 build is complete. Next = Alex's decision** (Norgate trial vs accept the result) plus the proposed attribution milestone (factor regression on the three existing series: alpha/beta, loadings, IR — no new trials). Carried items C1–C4 in QUANT-NOTES. |
| **M10 attribution** | ✅ **ACCEPTED 2026-10-05** (gate cycle 2) and merged to main (990 tests; loop: 3 dev iterations, review REVISE/APPROVE/APPROVE, gate REJECT→ACCEPT). Ken French factor provider + cache, CAPM / FF5+Mom OLS with HAC(6), active-return decomposition, `quantlab attribute`, report section, README table; carried C1–C4 closed. **Finding:** no full-sample alpha at any conventional level (FF5+Mom t = −0.6 / +1.4 / +0.4; SEs 1.3–1.9 pp/yr); 58/103/72% of the CAGR excess over SPY is beta leverage (geometric basis; premium-dependent). **Value has +4.18%/yr alpha (t 4.15) over 2012-02..2019-03 and ~0 after — found after the fact, coincides with the 14–28% coverage gap — the first question for Norgate data.** Do not lower the Sharpe-vs-SPY bar; any alpha gate = AND-only, trial-deflated t≈3, factor set + lag pinned, prospective. Open carried items in QUANT-NOTES "M10 gate cycle 2 — ACCEPT" (coverage bound + fixed half-sample regression into attribution.json before any gate proposal; two C4 trade-time gaps before the first real promotion). |
| M08 paper trading | ✅ merged 2026-09-12 (690 tests; gate REJECT, REJECT, ACCEPT — cycle 3 approved by Alex). Carried must-fix to M09: `paper run --dry-run` is a second decide-and-plan path (use run_once with a dry_run flag) |
| M04b engine perf | 🔵 in parallel worktree `..\quantlab-m04b` (branch `m04b-engine-perf`): calendar bounds, negative price cache, panel store, QualityGate wired with quarantine + membership-based symbol-reuse detector (42 names), unscored self-reported; full real run 8m32s; gate REJECT→ACCEPT cycle 2 (2026-09-12); ✅ merged to main 2026-09-12 (492 tests). Worktree can be removed after M06 merges. |
| M04–M09 | packets not yet written — write each just-in-time from the template in PROTOCOL.md, folding in QUANT-NOTES items addressed to it |

Milestone specs for M04–M09 live in the approved plan summary at the bottom of this
file. Task list state is also tracked in the harness task tools (M00/M01/M02 completed).

## Data
A full data/cache (842 tickers, prices 2010-06..2026-09-11, actions with fetched_at=2026-09-11, EDGAR facts) was prefetched on 2026-09-11 via the orchestrator scratchpad script (M09 should formalise it as `quantlab data`). A real momentum backtest via `quantlab backtest` took >40 min on this machine — engine performance is a known M09 concern (per-ticker parquet reads per rebalance).

## Immediate next action (2026-10-05)
M00–M10 are on main; nothing is in flight. **Alex's decisions (2026-10-05): pay for Norgate; set up
Alpaca paper (keys are now in user env vars `ALPACA_API_KEY`/`ALPACA_SECRET_KEY` — set after the
previous session started, so a NEW session is needed to see them); goal = paper trades, then real
capital via Trading212; wants to research strategies next.** Sequence agreed with Alex:
1. Alpaca paper smoke test in the new session: `uv run pytest -m network tests/test_alpaca_broker.py
   tests/test_broker_contract.py -q` (M08's never-run network tier). Then a research paper run of the
   blend under `quantlab paper run --force-research` to exercise broker/reconcile/journal/drift (it is
   REJECTED and cannot be promoted; this is pipeline exercise, not a strategy claim).
2. M11 packet: Norgate provider (Platinum US: delisted securities + historical constituents; NDU
   Windows app + `norgatedata` package; stub exists from M01, drops in via configs/platform.yaml; new
   DATA_SEMANTICS_VERSION; prefetch + scan; re-run momentum/value/blend UNCHANGED as the first test —
   the value 2012–2019 alpha question is the headline deliverable).
3. Prospective research bar BEFORE new strategies (packet text, Alex signs off): keep all gates; add
   the alpha gate as AND-only (FF5+Mom, HAC 6, trial-deflated t≈3); pre-register families + grids.
4. Strategy packets, one family each, pre-registered: quality → low-vol/defensive → re-constructed
   momentum (wider book, vol-weighted, sector-neutral). Each: run → card → attribution. Never chart
   patterns. Then promotion → ≥6 months paper with process-based go-live criteria → Trading212 adapter.
Operational notes: after any `data prefetch`/`refresh`, run `quantlab data scan` before a real run;
long runs need the laptop on AC with the lid open (Modern Standby freezes them; a keep-awake helper
cannot stop a lid close); commit before launching a run and between runs that write tracked
artefacts (dirty flags are plain `git status`); if a `.venv` binary is blocked with os error 4551
(Smart App Control — pytest.exe on 2 Oct, pyarrow DLL on 4 Oct), stop and report; both cleared by
themselves within hours.

## How to dispatch agents
- If this session started inside `quantlab/` the custom agents load natively: use
  subagent_type `developer`, `code-reviewer`, `quant-gate` (models come from their
  frontmatter: sonnet/sonnet/opus).
- If they are not registered (session started elsewhere), use a general-purpose agent
  with an explicit `model` param (developer/code-reviewer → sonnet, quant-gate → opus)
  and open the prompt with: "First read .claude/agents/<name>.md and adopt that role
  and its rules exactly."
- Always pass: packet path, repo root, branch name, "if `uv` is not on PATH use
  `python -m uv`", and (iteration ≥2) the exact REVIEW/VERDICT paths. Nothing else —
  scoped context is the token discipline.
- Prefer resuming the SAME agent for revision iterations (warm context); use a FRESH
  reviewer/gate per milestone (stale context is noise).

## Protocol reminders (full spec: plans/PROTOCOL.md)
- Caps: 3 develop↔review iterations, then 2 quant cycles — exhausted ⇒ stop, one-screen
  summary to Alex.
- On ACCEPT: `git add -A`, commit on the milestone branch with a summary line noting
  the loop stats, `git checkout main`, `git merge --no-ff <branch>`, branch for the
  next milestone. Run the full suite after merge.
- After every quant verdict: fold carried-forward findings into plans/QUANT-NOTES.md
  (the gate sometimes edits it itself — check before duplicating) and into the packets
  of the milestones they address. This mechanism has already caught real bugs — do not
  skip it.
- Loop artifacts (HANDOFF/REVIEW/VERDICT, iteration-suffixed) are the only channel
  between agents. They get committed with the milestone.

## Quality bar (what ACCEPT has actually meant so far)
- Reviewers run the verification commands themselves and mutation-test bias canaries
  (weaken a guard → canary must fail → revert).
- Parity with the old repo (`..\MomentumValueStrategy`) is independently reproduced,
  not taken from the handoff. Ported numerical logic is frozen.
- The quant gate runs its own adversarial probe (e.g. hostile provider with a
  future-dated split) and REJECTs anything that weakens a bias guard, uncertain ⇒
  REJECT with a question.
- Real catches to date: calendar NotSessionError crash (M00), .gitignore silently
  masking the whole data package (M01), yfinance 1.x MultiIndex break (M01),
  failed-download frozen into cache (M02), raw-price momentum split distortion
  (M02 gate → M02b). Expect and demand this hit rate.

## Human touchpoints (Alex decides, not you)
1. Alpaca paper account + `ALPACA_API_KEY`/`ALPACA_SECRET_KEY` env vars — needed at M08.
2. Loop-cap escalations and any packet the quant gate flags as methodologically wrong.
3. Strategy promotion to paper trading (platform gates ELIGIBLE_FOR_PAPER; Alex signs off).
4. Deleting the orphaned `..\MomentumValueStrategy-value` worktree (pre-approved in
   plan, but confirm before executing; then `git worktree prune` + `git branch -d
   value-strategy` in `..\MomentumValueStrategy`).
5. Norgate Data trial/subscription decision (provider stub is contract-tested, drops
   in via configs/platform.yaml).

## Remaining milestone specs (from the approved plan)
- **M03** strategy framework + momentum/value/blend plugins — packet ready; signal
  parity 1e-10; strategies must use M02b adjusted prices; value must resolve the
  filed-date one-session-lag condition (see packet).
- **M04** generic EOD backtest engine: portfolio accounting, next-open execution,
  delisting forced exits (haircut config; do NOT key solely off DelistingEvent — see
  QUANT-NOTES), costs (port two-sided turnover model + Corwin-Schultz), BacktestResult
  with embedded survivorship bound + quality-flag count + config/provider provenance.
  Verify: equity-curve parity vs old repo within explained tolerance.
- **M05** validation I: port metrics/walk-forward; sensitivity heatmaps ("no-cliff"
  score); regime/subperiod robustness. Golden tests vs old repo numbers.
- **M06** validation II: purged/embargoed CV, PSR/DSR (closed-form worked-example
  tests), trials registry keyed on strategy_id + White RC/SPA (synthetic-null ⇒
  ~uniform p-values), Monte Carlo block bootstrap, capacity port, report_card with
  gates from configs/validation.yaml → verdict REJECTED | RESEARCH_ONLY |
  ELIGIBLE_FOR_PAPER. Gate defaults are in the plan; make them config, not code.
- **M07** reporting: jinja2 single-file HTML + markdown twin (verdict header,
  performance vs SPY, cost breakdown, bias-bounds panel, validation badges,
  provenance appendix); plots port; CLI `quantlab report`.
- **M08** paper trading: Broker ABC (idempotent client order IDs, capability flags),
  Alpaca adapter (alpaca-py, paper), trading212 stub + contract tests, rebalancer
  (drift bands, rounding, no-short guard), reconcile + journal + runner (`quantlab
  paper run`), Windows Task Scheduler doc. Mock-broker E2E; Alpaca smoke test needs
  Alex's keys.
- **M09** end-to-end: momentum/value/blend → backtest → validate → report from one
  command chain on real cached data 2012–2026; wire promotion gating to paper runner;
  docs. Expected honest outcome: gates likely REJECT vs SPY — that is a CORRECT
  platform output, not a failure.
- Post-v1 backlog: Trading212 practice adapter, Norgate provider, forward-vs-backtest
  drift dashboard, new strategy families (quality, low-vol; never chart patterns).

## Alex's non-negotiables (from the kickoff conversation)
No survivorship/look-ahead bias anywhere — measured where it can't be eliminated.
No chart-pattern analysis, ever. Professional-grade engineering. Token-efficient agent
usage. Honest results over flattering ones.
