# Graph engineering · organizing work across nodes

When a job outgrows one loop, the question becomes: which piece goes to a model, which to deterministic code, which to a human, and what travels across each handoff. This is not about LangGraph or any graph framework — it's the design layer those frameworks implement.

Grounded in first-hand source reading (repos cloned to `research/`; commits pinned below) plus Anthropic's production numbers.

## Should you even split? (read this first)

Usually no. Every edge is a context retelling, and every retelling drops information. Anthropic's production data draws the boundary precisely:

- Their multi-agent research system (Opus 4 orchestrator + Sonnet 4 workers) beat single-agent Opus 4 by **90.2%** on internal research evals — but token usage alone explained **80% of the performance variance**. Multi-agent works because separate context windows buy more tokens per problem, not because of emergent teamwork.
- It pays only for **breadth-first tasks with parallelizable directions** whose value covers a multiplied token bill.

Split when you see one of three signals:

1. **Context poisoning** — two workstreams crowding one window (research vs code-writing).
2. **Permission layering** — part of the work must run locked-down; edges are natural permission boundaries.
3. **A human needs in** — model the approval point as a node, not a popup inside the loop.

## The four node types

| Node | Cost | Determinism | Use for |
|------|------|-------------|---------|
| Agent (loop inside) | high | improvises | paths unknowable in advance |
| Code | ~free | total | paths already known |
| Tool | ~free | total | code with a model-facing interface (ACI) |
| Human | highest | n/a | judgment, approvals, irreversible actions |

Every agent node is a standard loop — `references/loop-engineering.md` applies as-is inside each one.

## Edge contract: five elements

Three independent systems converged on what one delegation edge must carry:

- Hermes: `delegate_task(goal, context, toolset, max_iterations)`
- crewAI (`f15844b`, `tools/agent_tools/delegate_work_tool.py`): `DelegateWorkToolSchema(task, context, coworker)`
- Anthropic's orchestrator prompt: objective, output format, tool guidance, task boundaries

Union of the three = the contract: **goal, context, permissions, budget, output format**. Skip one and that one blows up at runtime. Anthropic's counterexample is on record: one-liner delegations ("research the semiconductor shortage") produced workers that duplicated each other and drifted off-topic.

**Return payload**: conclusion + evidence, never a bare conclusion. smolagents (`agents.py:868`) wraps the managed agent's answer in a report template plus optional `<summary_of_work>` — the parent can judge quality instead of trusting blindly.

**What the edge must NOT carry** — permissions only narrow. Codex `codex-rs/core/src/codex_delegate.rs` (commit `fa1d4c4`):

```rust
inherited_exec_policy: Some(Arc::clone(&parent_session.services.exec_policy)),  // L130
inherited_multi_agent_version: Some(MultiAgentVersion::Disabled),               // L143
```

L130: the child inherits the parent's exec policy — no bypass-by-spawning. L143: the child is born unable to spawn children. The recursion ban is a constructor argument, not a prompt plea. Hermes's version: 5 tools hard-removed from every child's toolset (delegate / clarify / memory-write / send_message / execute_code).

## Five topologies

| Topology | When | Readable implementation |
|----------|------|------------------------|
| Pipeline + gates | steps fixable in advance | crewAI `Process.sequential` |
| Triage routing | distinct task classes | cheap classifier node at the entrance |
| Parallel fan-out | independent subtasks | Anthropic: 3-5 subagents × 3+ parallel tools = 90% latency cut |
| Orchestrator-workers | subtasks unknowable in advance | crewAI `Process.hierarchical` (validator **requires** a manager: `check_manager_llm`) |
| Review loop | clear criteria, multi-pass quality | evaluator-optimizer; must carry a round cap |

Real systems compose: Anthropic's full flow is orchestrator-workers → synthesis → a deterministic CitationAgent as pipeline tail. Three shapes, one graph.

**Effort scale for the orchestrator** (steal this — Anthropic added it after early versions spawned 50 subagents for simple queries):

- simple fact-finding → 1 agent, 3-10 tool calls
- direct comparison → 2-4 subagents, 10-15 calls each
- complex research → 10+ subagents, explicitly divided responsibilities

## State ownership

- **Blackboard** (shared plan / todo / working dir): for things that must outlive any single context window. Anthropic's lead agent saves its plan to Memory **before** spawning workers, because >200K contexts get truncated. Police write access — Hermes bans children from writing long-term memory (unverified conclusions poison the well).
- **Messages** (edge payloads): for execution details. Better isolation, every payload needs design.
- Unify execution state and business state (12-Factor Factor 5); an event log carries both — concatenated agent-node logs are the graph's execution history.

## Humans are nodes

Mechanism: 12-Factor Factor 7 — the model contacts humans via tool calls (`request_approval(action, reason)`, `ask_human(question)`), so human involvement lands in the trajectory, replayable and countable.

- **Routing**: approvals go to the parent session only; children never own UI (Codex). Three simultaneous popups from three children is a failure mode, not a feature.
- **Timeouts**: every human node has a fallback (conservative default / suspend). The graph can't hang on someone's vacation.
- **Granularity**: grade by irreversibility — reads pass, reversible writes report after, irreversible actions (outbound / delete / spend) approve before. This is the same scale as the security checklist's approval gates.

## Freezing: the evolution direction

Dynamic regions (model picks edges) should freeze into static regions (code picks edges) over time. The test: did this path's last 100 runs take the same route? Then rewrite that agent node as a code node — no tokens, no bad days, unit-testable. Anthropic's CitationAgent is the live example (fixed path → dedicated deterministic-ish tail node). The reverse holds: an if-else chain drowning in exception branches wants an agent node.

## Runaway protection (all in code, never in prompts)

- **Depth cap**: Hermes hardcodes MAX_DEPTH=2; Codex's `MultiAgentVersion::Disabled` is a depth cap of 1 enforced at construction.
- **Recursion ban**: the delegation tool is not passed down.
- **Concurrency cap + heartbeats**: cap active nodes; long runners heartbeat (Hermes: 30s) so "working" and "dead" are distinguishable.
- **Budgets travel down edges**: every edge carries max_iterations; the parent's budget ceilings the children's sum.

## Anti-patterns

| Anti-pattern | Why it kills you | Fix |
|--------------|------------------|-----|
| Graphs for the sake of graphs | 7 nodes = 7 rounds of handoff loss | node count is a cost, not maturity |
| One-line delegation | duplicated + drifting workers (Anthropic, on record) | all five edge elements, every time |
| Conclusions without evidence | parent can't judge, must trust or redo | report template + work summary |
| Guardrails in the prompt | forgotten in long contexts | constructor args and constants |
| Human node without timeout | graph hangs a week | timeout + fallback per human node |
| One model size everywhere | flagship router = waste; small decider = gamble | per-node model choice (Opus leads, Sonnet works) |

## Research sources

| Source | Version | What was read |
|--------|---------|---------------|
| [openai/codex](https://github.com/openai/codex) | `fa1d4c4` | `codex_delegate.rs` (L130 policy inheritance, L143 recursion ban), `protocol.rs` SubAgentSource (L2822) |
| [crewAIInc/crewAI](https://github.com/crewAIInc/crewAI) | `f15844b` | `process.py`, `crew.py` `check_manager_llm`, `delegate_work_tool.py` |
| [huggingface/smolagents](https://github.com/huggingface/smolagents) | `e3a5b89` | managed agents `__call__` (report template, summary_of_work) |
| [Anthropic multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system) | 2025 | 90.2% gain, 80% token variance, effort scales, 50-subagent incident, CitationAgent |
| [Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents) | Anthropic | workflow/agent distinction, five patterns |
| [12-Factor Agents](https://github.com/humanlayer/12-factor-agents) | repo | Factors 5/7/10 |

Long-form treatment: docs-site `concepts/graph-engineering`. Four-harness subagent comparison: book §10, §12.
