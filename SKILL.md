---
name: build-your-own-agent
description: Use when building or designing an agent harness; choosing between Codex, Claude Code, OpenClaw, or Hermes patterns; designing agent loop, subagents, todo/task progress surfaces, execution-state routing, memory, skills, cron, sandbox, or security; diagnosing slow, expensive, leaky, looping, or unsafe agents; or preparing for agent-infra interviews.
license: Complete terms in LICENSE.txt
---

# Build Your Own Agent · Engineering Playbook

A skill for two related jobs:

1. **Build**: design a production-grade agent harness from zero.
2. **Diagnose & Optimize**: audit an existing agent against the same rules and fix what's wrong.

Both jobs share the same vocabulary — the 10 Iron Laws + 8 spectrum axes — distilled from Codex, Claude Code (2.1.88 expanded build), OpenClaw, and Hermes.

## When to load this skill

Load when the user asks any of:

- "I want to build my own agent / harness / coding agent" → go to **Build flow**.
- "My agent is slow / expensive / leaking / looping / unsafe" → go to **Diagnose flow**.
- "Should I copy Codex's approach or Claude Code's for X?" → go to `references/picking-from-spectrum.md`.
- "I'm interviewing for an agent infra role" → go to `references/interview-prep.md`.
- "Can my existing agent be refactored to follow these patterns?" → go to **Diagnose flow** then `references/migration-guide.md`.

Do NOT load for: simple agent questions (e.g. "what is an LLM agent"), library questions (langchain / llamaindex specific), or non-agent code review.

## File map (load on demand, not all at once)

| File | Purpose | Load when |
|------|---------|-----------|
| `references/build-agent-workflow.md` | 5-phase end-to-end build flow + per-step source-backed picks | user wants to build from scratch |
| `references/diagnose-agent.md` | 4 diagnosis flows + anti-pattern → fix map | user has an existing agent to audit/improve |
| `references/picking-from-spectrum.md` | 8-axis decision tree for design choices | user needs to pick between Codex / Claude Code / OpenClaw / Hermes patterns |
| `references/agent-scaffold.md` | standard Python scaffold and smoke-test checklist | user starts implementing or needs file-level rationale |
| `references/migration-guide.md` | 10-stage refactor for legacy agents (1-3 days each) | user has a working agent that breaks rules |
| `references/security-checklist.md` | 5-layer defense stack | before any production deploy |
| `references/production-deployment.md` | 7-phase deploy + observability/cost/lifecycle | when scaffold passes lint and team wants to ship |
| `references/interview-prep.md` | 20 highest-value interview questions, mapped to book §11 | candidates and architects |
| `references/skill-interop.md` | how this skill chains with mcp-builder / frontend-design / dev-planner | composing with other skills |
| `scripts/init-agent-project.py` | golden-path initializer: scaffold, templates, CI, local gates | every new Python agent project |
| `scripts/lint-agent-design.py` | static lint: 10 Iron Laws check + task-progress advisory, exits 0/1 | every CI run + during refactor |
| `scripts/diagnose-agent.py` | runtime diagnosis: read rollout.jsonl + flag 9 anti-patterns | weekly during dev, daily in production |
| `assets/AGENTS.md.template` | drop-in `AGENTS.md` for new agent projects | first commit of a new agent repo |
| `assets/pyproject.toml.template` | scaffold-aligned dependencies + lint config | first commit of a new agent repo |
| `assets/scaffold/` | single source for generated project files | every update to the generated Python scaffold |

## The 10 Iron Laws

Every law is enforced in all four reference systems. If you violate one, you lose a property you'll wish you had. The lint script (`scripts/lint-agent-design.py`) checks all 10.

| # | Law | Why it matters | Counter-example (don't do) |
|---|-----|-----------------|----------------------------|
| 1 | **Turn is the source of truth** | rollback, retry, audit all key off the turn boundary | one giant `while True:` with implicit boundaries |
| 2 | **Context has a cache boundary** | misplaced boundary = 10× API bill | timestamp glued to identity in the same string |
| 3 | **Prompt is data, never instructions** | external content is the #1 injection vector | concatenating web-fetch result directly into user message |
| 4 | **Three verifier tiers always** | knowing when to stop = product quality | stop only when model emits no tool call |
| 5 | **Sandbox first, then trust** | LLM-layer trust is decoration; OS sandbox is the real defense | `subprocess.run(cmd)` in a "trusted" env |
| 6 | **Redact at import time, not at log time** | LLM can `export REDACT=false` mid-turn | `if config.redact:` checked inside the log call |
| 7 | **fail_open beats fail_closed at default** | strict default → users disable safety wholesale | scanner crash kills the whole agent |
| 8 | **Memory writes need a frozen snapshot** | mid-turn writes invalidate cache + cause nondeterminism | reading live memory inside prompt assembly |
| 9 | **Skills are content; loadable code is supply chain** | a "skill" that runs code is a binary, not a doc | accepting `skill_path` from CLI without scanner |
| 10 | **Audit trail is the last mile** | "we don't know why" = no fix | only logging final assistant message |

Each law maps to one chapter §11 in the book at `docs-site/src/content/docs/patterns/`. The `references/agent-scaffold.md` cross-references which file embodies each law.

## Build flow (use when starting from scratch)

5 phases. Each has a single owner reference file. Don't skip Phase 1 — picking wrong axes early costs weeks later.

```
Phase 1 · Pick architecture        →  references/picking-from-spectrum.md
   ↓     (answer 8 axes: loop / context / dispatch / verifier / memory / skill / sandbox / task progress; use execution-state routing when progress has multiple audiences)
Phase 2 · Initialize scaffold      →  scripts/init-agent-project.py + references/agent-scaffold.md
   ↓     (generate standard files, including progress/todo.py, then adapt with file-level rationale)
Phase 3 · Wire 5-layer defense     →  references/security-checklist.md
   ↓     (supply chain / input / runtime / persistence / egress)
Phase 4 · Verify before deploy     →  scripts/lint-agent-design.py + smoke tests
   ↓     (lint passes + injection test + sandbox escape test)
Phase 5 · Ship + operate           →  references/production-deployment.md
         (observability / cost cap / lifecycle / multi-tenant)
```

Detailed checklist, expected outputs, and failure modes for each phase: `references/build-agent-workflow.md`.

**Anti-pattern**: do not start at Phase 2 (scaffold) before Phase 1 (axes). The scaffold encodes one specific set of choices; you'll either fight it or be unable to swap parts later.

## Diagnose flow (use when an agent already exists)

4 flows. Run in order — earlier flows catch issues that pollute the data later flows depend on.

```
Flow A · Static lint               →  python scripts/lint-agent-design.py /path/to/agent
   ↓     (10 Iron Laws check; 0/1 exit code; --format json for CI)
Flow B · Runtime diagnosis         →  python scripts/diagnose-agent.py /path/to/rollouts/ --allow-empty
   ↓     (9 anti-patterns: tool loop / cache miss / cost spike / verifier silent / stale progress / etc.)
Flow C · Security audit            →  walk references/security-checklist.md by hand
   ↓     (5 layers × concrete tests)
Flow D · Cost / latency / quality  →  cross-reference metrics.jsonl with rollout.jsonl
         (per-tool p95, per-session cost, transition_reason distribution)
```

Detailed playbook for each flow + a symptom → root-cause → source-backed fix map: `references/diagnose-agent.md`.

**Anti-pattern**: do not start with Flow D ("the agent feels slow") before Flow A. Many symptoms have static root causes (missing cache boundary, missing verifier) that runtime data alone won't surface.

## Source-backed picks at a glance

For each design dimension, start from the source system with the clearest implementation.

| Dimension | Reference | Where to read |
|-----------|----------------|---------------|
| Replay-friendly loop | Codex (rollout per turn) | `REF/codex/codex-rs/core/src/rollout/` |
| Per-session prompt with cache | Claude Code (5-tier priority) | docs-site §3 + sourcemap analysis |
| Parallel tool dispatch | Claude Code (`dispatchToolUseBlocks`) | docs-site §4 |
| Hard + soft verifier | Codex (4-chain) + Claude Code (TOKEN_BUDGET) | docs-site §5 |
| `apply_patch` V4A diff | Codex | `REF/codex/codex-rs/core/src/apply_patch.rs` |
| Cross-platform sandbox | Codex (seatbelt + bwrap + windows) | `REF/codex/codex-rs/{sandboxes,linux-sandbox,bwrap,windows-sandbox-rs}/` |
| External content wrap | OpenClaw (random nonce) | `REF/openclaw/src/security/external-content.ts` |
| Memory consolidation (auto) | Codex (Phase 1 stage1 + Phase 2 LLM) | `REF/codex/codex-rs/memories/` |
| In-turn explicit memory | Hermes (`memory_tool` + threat scan) | `REF/hermes-agent/tools/memory_tool.py` |
| User-driven memory | Claude Code (skillify + 4-round AskUserQuestion) | docs-site §17 |
| Skill scanner | OpenClaw + Hermes INSTALL_POLICY | `REF/openclaw/src/security/skill-scanner.ts` + `REF/hermes-agent/tools/tirith_security.py` |
| Redact (import-time) | Hermes `agent/redact.py` | `REF/hermes-agent/agent/redact.py` |
| Bounded log redact | OpenClaw `redact-bounded.ts` | `REF/openclaw/src/logging/` |
| Audit trail | Codex `rollout/` | `REF/codex/codex-rs/core/src/rollout/` |
| Cron lock + threat scan | Hermes `cron/` + `_CRON_THREAT_PATTERNS` | `REF/hermes-agent/cron/` |
| Task progress surface | Codex `update_plan` + Claude Code `TodoWrite` / Tasks V2 + Hermes `todo` | docs-site §21 + `REF/codex/codex-rs/protocol/src/plan_tool.rs` + `REF/claude-code-2.1.88-expanded/src/tools/TodoWriteTool/` + `REF/hermes-agent/tools/todo_tool.py` |
| Execution state routing | Codex MCP progress + Claude Code SDK progress events + OpenClaw projector + Hermes `tool_progress` modes | docs-site §22 + `REF/codex/codex-rs/app-server-protocol/src/protocol/v2/mcp.rs` + `REF/claude-code-2.1.88-expanded/src/entrypoints/sdk/coreSchemas.ts` + `REF/openclaw/src/auto-reply/reply/acp-projector.ts` + `REF/hermes-agent/gateway/display_config.py` |
| MCP integration | Codex `mcp.rs` + `mcp_tool_*.rs` | `REF/codex/codex-rs/core/src/mcp*.rs` |

Decision trees per dimension: `references/picking-from-spectrum.md`. The pattern is always: **pick the simplest one that meets your constraint, copy verbatim, adapt only what doesn't fit**.

## Quick-start commands

After cloning a new agent repo or auditing an existing one:

```bash
# 0. New project golden path
python ~/.claude/skills/build-your-own-agent/scripts/init-agent-project.py ./my-agent --profile coding-cli --test-cmd "python -m pytest -ra"

# 1. Static lint (10 Iron Laws)
python ~/.claude/skills/build-your-own-agent/scripts/lint-agent-design.py /path/to/agent

# 2. Runtime diagnosis (point at the rollout dir)
python ~/.claude/skills/build-your-own-agent/scripts/diagnose-agent.py /path/to/rollouts/ --allow-empty

# 3. Both as CI gate (JSON output)
python ~/.claude/skills/build-your-own-agent/scripts/lint-agent-design.py /path/to/agent --format json
```

Exit code 0 = pass; non-zero = at least one rule fails. JSON output is stable enough to wire into GitHub Actions / CI.

## Writing style (anti-AI-slop)

This skill and its references are written to be read by an engineer who already knows what an LLM is. Conventions when extending:

- One concrete pointer per claim (file:line, chapter §, or REF/ path). No uncited architecture advice.
- Tables and numbered steps. Avoid the "First, ... Second, ... Finally, ..." filler.
- Show counter-examples. "Don't do X because Y" beats "Do A, B, C".
- Code blocks > prose for anything that has a single correct shape (sandbox profile, regex, JSON schema).
- Use English for code/identifiers. Use the user's language for prose.

If you find yourself writing "in this rapidly evolving landscape", delete the paragraph.

## What this skill does NOT replace

- The 22-chapter book at `docs-site/src/content/docs/patterns/`. Skill ≈ 30k tokens; book ≈ 100k tokens. Read the book when nuance matters.
- Hands-on building. The lint script catches structural violations, not domain mistakes (wrong tool design, bad prompt, weak verifier signal).
- The four source systems' actual source. When stuck, open `REF/{codex,claude-code-2.1.88-expanded,openclaw,hermes-agent}/` and read.
- Your judgment. The patterns are general; your tools and verifier are domain-specific. Adapt; don't transliterate.

## How to extend

If you discover a new pattern not covered:

1. Confirm it survives repeated production use, not a one-off win.
2. Map it to one of the 10 Iron Laws, or propose an 11th with rigorous justification.
3. Add a section to the relevant `references/*.md`, with: symptom, mechanism, fix, source pointer.
4. If it's testable by static analysis, add a check to `scripts/lint-agent-design.py`.
5. If it's runtime-detectable, add a check to `scripts/diagnose-agent.py`.
6. Update this `SKILL.md` index only if a new top-level file is needed.

Reading order for first-time skill users: this file → `references/build-agent-workflow.md` (if building) or `references/diagnose-agent.md` (if diagnosing) → `references/picking-from-spectrum.md` (when stuck on a decision).
