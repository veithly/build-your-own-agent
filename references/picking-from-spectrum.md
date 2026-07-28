# Picking from the spectrum · per-axis decision tree

Each section maps one design axis to a decision tree. Pick a leaf and copy the corresponding system's implementation.

## Table of contents

- Axis 1 · Loop shape (replay-friendly / observable / extensible / simple)
- Axis 2 · Context shape (static / 5-tier priority / PromptMode / 10-layer dynamic)
- Axis 3 · Tool dispatch (parallel / serial / event-bridged)
- Axis 4 · Verifier strategy (hard / soft / spread-across-time / plugin hook)
- Axis 5 · Memory architecture (user-driven / 2-phase auto / in-turn explicit / passive)
- Axis 6 · Skill system (bundled / admin-managed / scanner+trust-matrix)
- Axis 7 · Sandbox / runtime defense (per-OS / network-deny / fs-restricted)
- Axis 8 · Task progress surface and execution-state routing (checklist / task board / runtime events / compaction focus / multi-surface router)
- Axis 9 · Delegation topology (single loop / pipeline / orchestrator-workers / review loop)
- Worked examples (Codex-like coding agent / Cursor-like IDE agent / personal long-running)

## Axis 1 · Loop shape

> Reference chapters: §2 (Agent loop), §5 (Verifier), §11 (Session lifecycle)

```
Is your loop replay-friendly required (i.e. crash recovery from a saved file)?
├── Yes → copy Codex (turn = one LLM call, rollout.jsonl on every event)
│           - cost: disk IO per turn
│           - benefit: full replay via `resume_agent_from_rollout`
└── No → does the loop need fine-grained observability for external tooling?
          ├── Yes → copy Claude Code (7 transition.reason tags)
          │           - cost: every retry/stop must be tagged
          │           - benefit: dashboards can read tags directly
          └── No → does the loop have extension hooks (plugin chain)?
                   ├── Yes → copy OpenClaw (before/after_tool_call + lifecycle events)
                   │           - cost: long debug chain
                   │           - benefit: third-party can attach without forking
                   └── No → copy Hermes (iteration_budget 90 + grace call)
                              - cost: no hard verifier integration
                              - benefit: simplest, easiest to reason about
```

## Axis 2 · Context shape

> Reference chapters: §2 (prompt assembly), §3 (Context system), §16 (Memory)

```
How often does your prompt need to change runtime (per turn / per user / per skill)?
├── Almost never (release-pinned prompt) → copy Codex (one static template file)
│      → prompt change requires git commit; cache is rock-solid
├── Per-session (user-installed skill / project-specific config) → copy Claude Code (5-tier priority)
│      → CLAUDE.md → project AGENTS.md → skills index → user → ephemeral
│      → explicit cache boundary
├── Per-mode (main agent vs subagent vs minimal) → copy OpenClaw (PromptMode 3-preset)
│      → enum-driven assembly
└── Per-turn (user can overwrite identity, memory grows live) → copy Hermes (10-layer dynamic)
       → SOUL.md as identity source
       → memory snapshot frozen at turn start (rule 8)
```

## Axis 3 · Tool dispatch

> Reference chapters: §4 (Tool system), §7 (Shell), §10 (Subagent)

```
Does your model support multiple tool_use blocks per turn?
├── Yes (Anthropic-compatible) → copy Claude Code (count blocks yourself, dispatchToolUseBlocks parallel)
│      → biggest latency win
│      → requires permission gate per tool
└── No (one tool call per turn) → copy Codex (Responses API function_tool, serial)
       → simpler reasoning
       → subagent spawn if parallelism needed

Do you need plugin extensibility (third parties add their own tools)?
├── Yes → copy OpenClaw event-bridged middleware
│      → tool stream is observable
│      → before/after hook chain
└── No → use simple registry pattern (decorator + dict lookup)

Do tools need permission gating?
├── Always (production) → copy Codex execpolicy + Claude Code canUseTool
└── Bundled-only (v1) → static allowlist in registry
```

## Axis 4 · Verifier strategy

> Reference chapters: §5 (Verifier), §6 (apply_patch)

```
What's your domain?
├── Coding (test exit code available) → copy Codex (4-chain hard verifier)
│      → apply_patch validates → run tests checks → execpolicy + goals.rs
│      → loop won't stop until external truth says ok
├── General assistant / chat → copy Claude Code (TOKEN_BUDGET 90% + diminishing returns)
│      → no hard external signal
│      → diminishing returns = 3 turns × < 500 new tokens
├── Long-running daemon / memory-accumulating → copy Hermes (spread-across-time)
│      → grace call at iteration_budget exhaustion
│      → memory commit for next-time-around learning
└── Library you ship → leave as plugin hook (OpenClaw style)
       → user attaches their own verifier
```

## Axis 5 · Memory architecture

> Reference chapters: §16 (Memory), §19 (Self-improvement)

```
Should memory updates be automatic or user-driven?
├── User-driven (zero implicit writes) → copy Claude Code skillify
│      → 4-round AskUserQuestion before write
│      → disableModelInvocation flag
│      → fewest bugs
├── Automatic at session end (Phase 1 + Phase 2) → copy Codex
│      → Phase 1 writes raw rollout to stage1_outputs
│      → Phase 2 LLM consolidation (800-line prompt) on 6h cooldown
│      → hardest to get right
├── Automatic in-turn (explicit memory_tool) → copy Hermes
│      → 2200/1375 char limits
│      → 11 threat patterns + 10 invisible unicode checks
│      → balanced
└── Passive (no writes, just index files) → copy OpenClaw
       → FTS5 + sqlite-vec on existing files
       → temporal decay halfLifeDays=30
       → no risk of bad writes, but no learning either
```

## Axis 6 · Skill system

> Reference chapters: §17 (Skills)

```
Who can install skills?
├── Only bundled (release-pinned) → copy Codex (core-skills crate)
│      → core-skills tied to release; user gets what shipped
├── Bundled + admin-managed remote → copy Claude Code (remoteManagedSettings + signature)
│      → 17 bundled + admin config
├── User-installable from marketplace → copy OpenClaw skill-scanner + Hermes INSTALL_POLICY
│      → 3 severity + 8 extension scanner
│      → 12-cell trust × verdict matrix
│      → user prompt + audit log
└── Wild west (no scanner) → DON'T. This is how you get owned.
```

## Axis 7 · Sandbox / runtime defense

> Reference chapters: §13 (Sandbox), §20 (Security)

```
What's your target platform?
├── macOS only → seatbelt (`sandbox-exec`)
├── Linux only → bwrap + seccomp + landlock
├── Windows → windows-sandbox-rs (limited functionality)
├── Cross-platform → write three implementations like Codex
│      → fallback to bare process on unsupported OS (warn user)
└── Cloud / Docker container → use Docker as outer sandbox + OS sandbox inside
       → defense in depth

What's the default deny / allow?
├── Network: ALWAYS deny by default; allow specific hosts via approval
├── FS write: ALWAYS restrict to project root by default
├── FS read: usually allow (read-only is much less dangerous)
└── Process spawn: allow but log + audit
```

## Axis 8 · Task progress surface and execution-state routing

> Reference chapters: §21 (Todo List), §22 (Execution State Surfaces)

```
What has to own "what remains to do" while the agent is running?
├── Single-agent coding CLI → copy Codex update_plan
│      → tiny checklist: pending / in_progress / completed
│      → protocol event + TUI/status rendering
│      → keep it separate from Plan Mode
├── IDE / interactive assistant → copy Claude Code TodoWrite
│      → content + status + activeForm
│      → reminders when the list goes stale
│      → restore from transcript in noninteractive paths
├── Team / multi-agent / cross-process work → copy Claude Code Tasks V2
│      → file-backed tasks with owner, blocks, blockedBy, claim checks
│      → use only when you actually need durable coordination
├── Multi-channel operator UI → copy OpenClaw progress events
│      → project tool_call / tool_call_update / child-session progress
│      → runtime facts remain visible even if the model forgets a checklist
└── Long-context personal agent → copy Hermes todo
       → in-memory session list, replace or merge by id
       → after compaction inject only pending / in_progress
       → never promote active todos into long-term memory
```

Do not collapse approval plan, execution todo, and durable background task into one global planner. Approval plan is for user consent. Execution todo is for current focus. Durable task is for owner/blocker/retry semantics.

If progress has more than one audience, add an execution-state router from §22:

```
Do you need to show different progress to model context, users, operators, logs, terminal chrome, or resume cards?
├── No → keep Axis 8 as a todo/task choice only.
└── Yes → define source / audience / lifetime / context-policy per event
       → tool_progress and task_progress go to UI/logs first
       → only summarized, unfinished execution state re-enters model context
       → add per-platform display density: off / new / all / verbose
```

## Axis 9 · Delegation topology (single loop / pipeline / orchestrator-workers / review loop)

> Reference: `references/graph-engineering.md`; book §10 (Subagents), §12 (Permissions). Sources: crewAI `Process` (`f15844b`), Codex `codex_delegate.rs` (`fa1d4c4`), Anthropic multi-agent research system.

```
Can one loop + a good toolset finish the job without context poisoning?
├── Yes → NO delegation. Single loop. (Default answer. Every edge is a context
│         retelling; multi-agent multiplies token cost — Anthropic: token usage
│         explains 80% of multi-agent performance variance.)
└── No → which signal forced the split?
    ├── Steps are fixed and known in advance
    │      → pipeline + gates (crewAI Process.sequential)
    │      → freeze steps into code nodes; agent nodes only where paths vary
    ├── Subtasks unknowable until runtime (breadth-first research, multi-file refactor)
    │      → orchestrator-workers (crewAI Process.hierarchical + check_manager_llm)
    │      → orchestrator prompt carries the effort scale:
    │        simple = 1 agent / 3-10 tool calls; comparison = 2-4 workers;
    │        complex = 10+ workers with divided responsibilities
    ├── Output needs multi-pass quality with clear criteria
    │      → review loop (evaluator-optimizer) with a hard round cap
    └── A human must approve / decide mid-flow
           → human node via tool call (request_approval / ask_human)
           → parent session owns all approval UI; timeout + fallback required
```

Non-negotiable guardrails once you delegate (all in code, never in prompts):

- Every edge carries the 5-element contract: goal, context, permissions, budget, output format.
- Permissions only narrow across edges (Codex `inherited_exec_policy`, L130).
- Recursion ban: the delegation tool is not passed to children (Codex `MultiAgentVersion::Disabled`, L143; Hermes 5-tool hard block).
- Depth cap ≤ 2, concurrency cap, budget ceilings inherited from the parent.
- Return payload = conclusion + evidence (smolagents report + `summary_of_work` pattern).

## Worked example · "Build me a Codex-like coding agent"

Run the decision trees:

| Axis | Pick | Why |
|------|------|-----|
| Loop shape | Codex (rollout.jsonl) | crash recovery essential |
| Context shape | Codex (one static template) | release-pinned, no per-turn changes |
| Tool dispatch | Codex (serial, Responses API) | OpenAI model, simpler |
| Verifier | Codex (4-chain hard) | coding domain |
| Memory | Codex (Phase 1 + 2) OR start with Claude Code skillify | depends on team capacity |
| Skills | Codex (core-skills) | bundled allowlist, no marketplace |
| Sandbox | macOS+Linux (3 implementations) | full cross-platform |
| Task progress | Codex update_plan | lightweight current checklist, separate from Plan Mode |

This gives you a Codex-like agent. Read §2, §5, §6, §7, §13 in detail.

## Worked example · "Build me a Cursor-like IDE agent"

| Axis | Pick | Why |
|------|------|-----|
| Loop shape | Claude Code (7 transitions) | IDE wants to display state changes |
| Context shape | Claude Code (5-tier priority) | per-project AGENTS.md + user settings |
| Tool dispatch | Claude Code (parallel tool_use) | latency matters for IDE |
| Verifier | Claude Code (TOKEN_BUDGET) | general assistant |
| Memory | Claude Code (skillify, user-driven) | zero implicit writes |
| Skills | Claude Code (17 bundled + admin) | enterprise needs admin control |
| Sandbox | OS sandbox + canUseTool gate | per-action approval |
| Task progress | Claude Code TodoWrite + Tasks V2 | IDE wants activeForm, reminders, and durable task files when teams collaborate |

This gives you a Claude Code style agent. Read §2, §4, §11, §17.

## Worked example · "Build me a personal long-running agent"

| Axis | Pick | Why |
|------|------|-----|
| Loop shape | Hermes (iteration_budget + grace) | simple, no rollout overhead |
| Context shape | Hermes (10-layer) | SOUL.md = personality |
| Tool dispatch | OpenAI/Anthropic dual-protocol | works with multiple LLM providers |
| Verifier | Hermes (spread + memory) | personal use, accumulate over time |
| Memory | Hermes (in-turn memory_tool) | learn from each session |
| Skills | Hermes (INSTALL_POLICY 12-cell) | want to install third-party |
| Sandbox | Per-tool deny + tirith scan | content-layer defense |
| Task progress | Hermes todo + OpenClaw-style events | keep active work through compaction; project tool progress if multi-channel |

Read §3, §16, §17, §19, §20.
