# Skill interop · chaining build-your-own-agent with related skills

This skill is the architecture playbook. Building a real agent involves more than architecture. Use these adjacent skills together.

## Table of contents

- Skill chain for "build a complete agent harness" (5 phases)
  - Discovery / Implementation / Security review / Production / Operation
- Skill chain for "diagnose & optimize an existing agent" (4 flows)
- Skills that PAIR specifically well
  - + mcp-builder / + frontend-design / + dev-planner / + claude-skills-zh-cn
- Anti-pattern: skill stacking
- What this skill does NOT replace
- Calling the skill from a longer agent task
- How to extend this skill

## Skill chain for "build a complete agent harness"

### 1. Discovery phase

Skills to use first:

- **find-skills** — locate other relevant skills for sub-tasks
- **skill-creator** — when you decide to package your agent's domain logic as a skill
- **dev-planner** — break the agent project into a multi-phase plan

Pattern:

```
User: "I want to build my own agent"
→ build-your-own-agent (architecture decisions)
→ dev-planner (project plan based on the 3-phase recipe)
→ writing-plans (write an executable plan file)
```

### 2. Implementation phase

Per-component skills:

- **test-driven-development** — wrap each scaffold file with tests before changing it
- **using-git-worktrees** — keep agent versions isolated (each big change in its own worktree)
- **systematic-debugging** — when the agent loop misbehaves
- **frontend-design** — if your agent has a UI (TUI / web)

Pattern:

```
User: "Add the verifier tier 1 (hard verifier)"
→ build-your-own-agent (references/agent-scaffold.md > File 4)
→ test-driven-development (write failing test first)
→ implement
→ verification-before-completion (run the lint script)
```

### 3. Security review phase

Skills to chain:

- **security-review** (Codex skill) — full security audit
- **code-reviewer** — second-pair-of-eyes review
- **bugfix-verify** — independent verification of any security fix

Pattern:

```
After scaffold builds:
→ build-your-own-agent (references/security-checklist.md — manual walkthrough)
→ security-review (automated audit)
→ code-reviewer (review the changes)
→ verification-before-completion (re-run all tests + lint)
```

### 4. Production deployment phase

- **planning-with-files** — keep a deployment checklist file as you progress
- **workflow-automator** — CI/CD setup
- **dev-documentation** — write AGENT.md / README / runbook

Pattern:

```
Ready to deploy:
→ build-your-own-agent (references/production-deployment.md)
→ planning-with-files (open a deployment-plan.md, check items off)
→ workflow-automator (CI/CD scripts)
→ dev-documentation (operational docs)
```

### 5. Operation phase

- **paseo-loop** / **autopilot** / **ralph** — when you want an agent to self-iterate (be careful: these can rack up cost)
- **daily-review** — quality of agent improvements over time
- **paseo-handoff** — hand off long sessions between agent instances

## Skill chain for "diagnose & optimize an existing agent"

Different entrypoint, same destination. The diagnose flow has 4 sub-flows
(see `references/diagnose-agent.md`), each pairing with related skills:

### Flow A · Static lint

```
User: "Audit this agent for the 10 Iron Laws"
→ build-your-own-agent (SKILL.md → references/diagnose-agent.md Flow A)
→ scripts/lint-agent-design.py /path/to/agent
→ code-reviewer (cross-check findings against actual code)
→ verification-before-completion (confirm fixes pass lint)
```

### Flow B · Runtime diagnosis

```
User: "Why does my agent cost so much / loop / behave weird in prod?"
→ build-your-own-agent (references/diagnose-agent.md Flow B)
→ scripts/diagnose-agent.py /path/to/rollouts/ --allow-empty
→ systematic-debugging (root-cause one finding at a time)
→ bugfix + bugfix-verify (apply the source-backed fix from the AP map)
```

### Flow C · Security audit

```
User: "We had an incident; full audit"
→ build-your-own-agent (references/security-checklist.md by hand)
→ security-review (Codex skill — automated audit)
→ code-reviewer (second-pair-of-eyes review)
→ bugfix-verify (independent verification of every security fix)
```

### Flow D · Cost / latency / quality

```
User: "p95 latency doubled / cost up 5x / quality dropped"
→ build-your-own-agent (references/diagnose-agent.md Flow D)
→ optimize (performance optimization coordinator)
→ data-analysis (per-tool / per-session metrics analysis)
→ Apply fixes, then re-run diagnose-agent.py to confirm
```

### After every fix

```
→ regression test added (test-driven-development pattern)
→ scripts/lint-agent-design.py passes 10/10
→ scripts/diagnose-agent.py shows no recurrence on fresh rollouts
→ AGENTS.md updated if axis decision changed
→ dev-documentation (one-line CHANGELOG entry under "Diagnosis findings")
```

## Skills that PAIR specifically well

### build-your-own-agent + mcp-builder

Building an agent often means exposing your tools/data via MCP. Use both:

- This skill: agent loop, prompt, verifier, sandbox
- mcp-builder: the MCP server your agent connects to

Patten: build the MCP server first, test it standalone, then plug it into your agent.

### build-your-own-agent + frontend-design

If your agent has a UI:

- This skill: backend agent logic
- frontend-design: TUI / web UI for chat history, tool approvals, settings

Pattern: design UI mockup with frontend-design, plan API contract, implement agent first, then UI.

### build-your-own-agent + dev-planner

For multi-month projects, the dev-planner helps decompose:

- This skill: WHAT to build
- dev-planner: HOW to schedule it (sprints / milestones / dependencies)

Output: a multi-phase plan file aligned to the 10 architecture rules.

### build-your-own-agent + claude-skills-zh-cn

If your target user base is Chinese-speaking:

- This skill: architecture (English-primary)
- claude-skills-zh-cn: Chinese-language patterns

Both reference the same source book ([harness-architecture.pages.dev](https://harness-architecture.pages.dev)), which is bilingual.

## Anti-pattern: skill stacking

Don't load too many skills at once. Each skill takes ~10-15KB of context. Loading 10 skills = 100KB+ of system prompt = expensive + slow + risk of skill confusion.

Recommended:
- Load 2-3 skills max at once
- Use the orchestration pattern: parent skill calls child via `Task` tool, child skill is loaded in subagent context only

For this skill: load build-your-own-agent in main context. When implementing specific files, use TDD via subagent if you want test-driven workflow without bloating parent context.

## What this skill does NOT replace

- **The source book**. The 22 chapters have ~100k tokens of detail. This skill compresses to ~30k. Most concepts have nuance worth reading in full.
- **Hands-on experience**. Reading patterns doesn't replace building. Use this skill while building, not as a substitute for building.
- **The four source systems' actual source code**. When stuck, read the original (Codex / Claude Code expanded build / OpenClaw / Hermes). This skill points at chapters which point at file:line in those repos.
- **Your domain expertise**. The architecture patterns are general. Your tools, your verifier, your sandbox policy are domain-specific. Adapt, don't copy verbatim.

## Calling the skill from a longer agent task

If you're already deep in another task and need to consult this skill mid-flight:

```
You: I'm 3 hours into building a coding agent. Hit a wall on memory architecture.
→ Load build-your-own-agent
→ Read references/picking-from-spectrum.md > Axis 5 (Memory)
→ Make a decision, document it in AGENT.md, continue
```

The skill is designed to be loaded mid-task and consulted for specific axes, not just read top-to-bottom.

## How to extend this skill

If you discover a pattern not in the book or in these references:

1. Confirm it works in production, not just in theory
2. Trace which of the 10 rules it relates to
3. Add a section to the relevant reference file (or a new one)
4. If statically detectable: add a check to `scripts/lint-agent-design.py`
5. If runtime-detectable: add an anti-pattern to `scripts/diagnose-agent.py`
6. Update SKILL.md with a one-line mention only if a new top-level file is needed

PRs against the source book are welcome too. Each chapter §11 has an "open" Q where new patterns can land.

## Files in this skill (cross-reference)

| Audience | First read | Then read |
|----------|-------------|-----------|
| New agent builder | `SKILL.md` | `references/build-agent-workflow.md` → `references/agent-scaffold.md` |
| Existing agent owner | `SKILL.md` | `references/diagnose-agent.md` → `references/migration-guide.md` |
| Tech lead picking architecture | `SKILL.md` | `references/picking-from-spectrum.md` |
| Security reviewer | `SKILL.md` | `references/security-checklist.md` |
| Production launch | `SKILL.md` | `references/production-deployment.md` |
| Interview candidate | `SKILL.md` | `references/interview-prep.md` |
| CI engineer wiring lint | — | `scripts/lint-agent-design.py --help` + `assets/ci-lint-diagnose.yml.template` |
| Operator running diagnose weekly | — | `scripts/diagnose-agent.py --help` + `references/diagnose-agent.md` |
