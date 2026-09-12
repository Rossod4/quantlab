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
| **M06 validation II** | 🔵 **cycle 3 APPROVED by Alex 2026-09-12; iteration 4 in progress** (was escalated 2026-09-11 evening) — 3 dev iters, review APPROVE, gate REJECT ×2 (cap). 5/6 blockers closed; remaining: headline trial can be dropped from the RC matrix by the overlap resolver (plans/state/M06/VERDICT.2.md). Recommended: one narrow cycle 3. Work is uncommitted on branch `m06-validation-2`. |
| M04b engine perf | 🔵 in parallel worktree `..\quantlab-m04b` (branch `m04b-engine-perf`): calendar bounds, negative price cache, panel store, QualityGate wired with quarantine + membership-based symbol-reuse detector (42 names), unscored self-reported; full real run 8m32s; gate REJECT→ACCEPT cycle 2 (2026-09-12); ✅ merged to main 2026-09-12 (492 tests). Worktree can be removed after M06 merges. |
| M04–M09 | packets not yet written — write each just-in-time from the template in PROTOCOL.md, folding in QUANT-NOTES items addressed to it |

Milestone specs for M04–M09 live in the approved plan summary at the bottom of this
file. Task list state is also tracked in the harness task tools (M00/M01/M02 completed).

## Data
A full data/cache (842 tickers, prices 2010-06..2026-09-11, actions with fetched_at=2026-09-11, EDGAR facts) was prefetched on 2026-09-11 via the orchestrator scratchpad script (M09 should formalise it as `quantlab data`). A real momentum backtest via `quantlab backtest` took >40 min on this machine — engine performance is a known M09 concern (per-ticker parquet reads per rebalance).

## Immediate next action
M06 is at the loop cap awaiting Alex's decision (see table). If approved: one narrow cycle 3 on the
headline-pinning fix + disclosures listed in VERDICT.2.md, then review, gate, merge. M04b merges after
M06 (rebase the worktree branch on main; conflicts expected only in QUANT-NOTES.md). Then M07 (packet
drafted in the orchestrator scratchpad), M08, M09 (drafted). Then the
real-data run of momentum / value / blend_50_50 through the report card — Alex's decision
point. Post-M06 data follow-on: per-component TTM EPS share terms (QUANT-NOTES M03b).

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
