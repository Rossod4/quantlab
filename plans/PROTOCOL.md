# QuantLab Agent-Loop Protocol

**Actors:** orchestrator = the main Claude Code session (human-supervised). Subagents:
`developer` (sonnet), `code-reviewer` (sonnet), `quant-gate` (opus) — defined in `.claude/agents/`.

## Per milestone M0X
1. Orchestrator ensures work packet `plans/M0X-*.md` exists and creates branch `m0x-<slug>`.
2. **Develop:** invoke `developer` with the packet path + (iteration ≥ 2) the latest
   REVIEW/VERDICT paths. Nothing else — no repo tour.
3. **Code review:** invoke `code-reviewer` with packet + HANDOFF path. Output REVIEW.md.
   - REVISE → step 2. Max **3** develop↔review iterations, then escalate to human.
4. **Quant gate:** on APPROVE, invoke `quant-gate` with packet + HANDOFF + REVIEW paths.
   Output VERDICT.md.
   - REJECT → step 2 (quant findings are the revision items). Max **2** quant cycles,
     then escalate.
   - ACCEPT → orchestrator commits, merges to main, marks the milestone done, proceeds.
5. **Escalation:** stop; present the human a one-screen summary (iteration count,
   unresolved findings, options).

## Artifacts
Everything flows through `plans/state/M0X/`: `HANDOFF.md`, `REVIEW.md`, `VERDICT.md`
(iteration suffixes `.2`, `.3`). Agents never converse directly; files are the only
channel — scoped context, auditable in git.

## Token economics
- developer/code-reviewer = sonnet (high volume); quant-gate = opus (once per cycle,
  smallest input, highest leverage).
- Packets carry explicit file lists; no agent greps the whole tree.
- Ported code is referenced by absolute path into `..\MomentumValueStrategy`, never
  pasted into prompts.

## Work packet template
```
# M0X — <title>
Goal: <2 sentences>
In scope / Out of scope: <explicit file list to create/modify>
Context (read these, nothing else): specs / port sources / existing quantlab files
Interfaces to honor: <signatures frozen by earlier milestones>
Acceptance criteria: <numbered, testable>
Verification commands: <exact invocations + expected outcomes>
Parity fixtures: <known numbers from the old repo, where applicable>
```
