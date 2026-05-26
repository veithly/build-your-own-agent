# Interview prep · 20 highest-value questions

Curated from the 220 questions in the source book. Each question links back to its source chapter §11 for the full worked answer.

## Table of contents

- Tier 1 · Must-answer (10 questions) — foundational design vocabulary
- Tier 2 · Stronger candidates answer these (10 questions) — implementation depth
- Recommended reading order (4h / 8h / 16h schedules)
- Quick self-test procedure

Use this list as:
- A self-audit of your agent design (can you answer every Q with concrete code?)
- Interview prep for senior agent engineer roles
- A reading order for the source book's §11 sections

## Tier 1 · Must-answer (10 questions)

If you can't answer these, you don't yet have a working mental model of agent harness design.

### 1. What is a "turn" in an agent loop?

**Where to read**: Chapter 02 §11 Q1.
**Why critical**: every other rule (rollout, retry, memory snapshot, audit) hangs off the turn boundary. If your team disagrees on what a turn is, you have no system.
**Quick answer**: a turn is one LLM call + the tool dispatches it produced + the user message that started it. It's physical (one network round trip) AND logical (one unit of replay).

### 2. Why is the prefix cache boundary important?

**Where to read**: Chapter 03 §11.
**Why critical**: misplaced cache boundary = 10× the API cost.
**Quick answer**: layers above the boundary are cached (same bytes every turn = cache hit). Below the boundary is recomputed. Memory snapshot and skill index belong above; timestamp and turn-specific state below.

### 3. How do you handle three concurrent tool calls in one turn?

**Where to read**: Chapter 04 §11.
**Why critical**: latency win or correctness disaster, depending on implementation.
**Quick answer**: count `tool_use` blocks yourself (don't trust `stop_reason`). Run them in parallel via a thread pool. Each gets its own `tool_result`. Recombine into the next user message. Permission gate is per-call.

### 4. What's the difference between hard, soft, and give-up verifier?

**Where to read**: Chapter 05 §11.
**Why critical**: stopping at the right time = product quality.
**Quick answer**: hard = external truth (test exit code, lint pass). Soft = budget/heuristic (token budget, convergence). Give-up = model self-stops. Production wants at least hard + soft; give-up alone is unreliable.

### 5. Why does apply_patch use V4A diff format?

**Where to read**: Chapter 06 §11.
**Why critical**: file edits are the #1 source of agent bugs in coding.
**Quick answer**: V4A includes version info so two divergent edits can merge correctly. Plain unified diff fails when the file has changed since the agent read it.

### 6. How does Codex sandbox a shell command on macOS?

**Where to read**: Chapter 07 §11, Chapter 13 §11.
**Why critical**: the hard runtime boundary.
**Quick answer**: write a seatbelt profile (s-expression) declaring deny-default + allow specific operations. Invoke `sandbox-exec -p <profile> -- <cmd>`. Default: deny network, restrict fs_write to project root.

### 7. What does `disableModelInvocation` do in Claude Code skillify?

**Where to read**: Chapter 17 §11, Chapter 19 §11.
**Why critical**: it's the boundary between "agent learns" and "user controls learning".
**Quick answer**: when true, the agent cannot trigger memory/skill writes via tool. Only the user can. The 4-round `AskUserQuestion` flow surfaces a "do you want to remember this?" prompt and only writes on explicit yes.

### 8. Why is `fail_open=true` Hermes's default for tirith?

**Where to read**: Chapter 20 §11 Q3.
**Why critical**: counter-intuitive but correct.
**Quick answer**: strict-by-default = "scanner breaks → agent breaks → users disable safety entirely". `fail_open` keeps the system running while flagging warnings, and lets production opt into fail_closed explicitly.

### 9. How does OpenClaw wrap external content?

**Where to read**: Chapter 20 §11 Q1.
**Why critical**: prompt injection from external sources is the most common attack vector.
**Quick answer**: each wrap uses a session-unique 8-byte hex nonce. Attackers can't forge a matching closing tag because they can't predict the nonce.

### 10. What's the 5-layer security defense stack?

**Where to read**: Chapter 20 §11 Q10.
**Why critical**: agent security is layered or it's nothing.
**Quick answer**: (1) supply chain (allowlist + scanner + provenance); (2) input boundary (wrap external content); (3) runtime (sandbox + approval); (4) persistence (memory threat scan); (5) egress (redact at import time). Plus audit trail as last mile.

## Tier 2 · Stronger candidates answer these (10 questions)

### 11. Why doesn't Codex use Anthropic's parallel tool_use?

**Where**: Chapter 02, 04 §11.
**Quick answer**: Codex targets Responses API (OpenAI). The model is trained to emit one tool_call per turn. Parallel dispatch would require multi-agent subagent spawning, which Codex implements via `agent/control.rs`.

### 12. How does Codex's memory consolidation Phase 1 + Phase 2 work?

**Where**: Chapter 19 §11 Q1, Q2.
**Quick answer**: Phase 1 writes raw `stage1_outputs` to disk every turn. Phase 2 runs asynchronously on a 6-hour cooldown, executing an 800-line LLM prompt that consolidates raw memories into MEMORY.md. Two phases separate "capture" from "reflect", avoiding LLM cost per turn.

### 13. What's OpenClaw's halfLifeDays=30 and how is it derived?

**Where**: Chapter 19 §11 Q3.
**Quick answer**: temporal decay weight for passive memory index. `weight = 2^(-age_days / 30)`. 30 days is empirically tuned: longer = stale memory pollutes search; shorter = recent work disappears too fast. Decay is applied at query time, not write time.

### 14. Why does Hermes use char limits (2200/1375) instead of token limits?

**Where**: Chapter 16 §11, Chapter 19 §11 Q4.
**Quick answer**: char limits are deterministic across providers. Token counting requires loading the tokenizer (latency + dependency). 2200 chars ≈ 700 tokens for English, ≈ 1100 for CJK — a safe upper bound that doesn't require runtime computation.

### 15. How does Hermes's `_REDACT_ENABLED` get snapshotted?

**Where**: Chapter 20 §11 Q4.
**Quick answer**: `_REDACT_ENABLED = os.getenv("HERMES_REDACT_SECRETS", "true").lower() == "true"` at module top. Read once at import. LLM cannot `export` mid-turn to bypass. Disabling requires process restart.

### 16. Why is Hermes's tirith verdict based on exit code, not JSON stdout?

**Where**: Chapter 20 §11 Q2.
**Quick answer**: stdout is attacker-writable (a scanned command can `echo '{"verdict":"allow"}'`). Exit code is delivered by OS, immune to text-stream injection. JSON stdout only enriches findings; never decides verdict.

### 17. What's the OpenClaw `DEFAULT_GATEWAY_HTTP_TOOL_DENY` vs `DANGEROUS_ACP_TOOL_NAMES` split?

**Where**: Chapter 20 §11 Q7.
**Quick answer**: same tool has different risk by transport. Local ACP = user explicit operation (ask). Remote HTTP = untrusted network (deny). Two lists = two threat models = two defaults.

### 18. How does Codex achieve "rollback after crash"?

**Where**: Chapter 02 §11, Chapter 11 §11.
**Quick answer**: every turn writes events to `~/.codex/sessions/<thread_id>.jsonl`. On resume, `resume_agent_from_rollout` replays the JSONL to reconstruct full state (subagent status, tool history, goal progress). Disk IO per turn is the cost.

### 19. What's Hermes's `frozen` snapshot pattern for memory?

**Where**: Chapter 16 §11, Chapter 19 §11.
**Quick answer**: at turn start, `freeze_memory()` returns a stable string. The prompt embeds that string. Mid-turn memory writes don't change the active turn's prompt. Next turn starts with a fresh freeze. This protects prefix cache + prevents mid-turn mutation.

### 20. How does Claude Code's `TOKEN_BUDGET` soft verifier detect diminishing returns?

**Where**: Chapter 02 §11, Chapter 05 §11.
**Quick answer**: if `total_tokens > budget * 0.9` → soft-stop. If last 3 consecutive turns each produced < 500 new tokens → diminishing returns soft-stop. Both signal "agent is spinning, not progressing".

## Recommended reading order

If you have 4 hours: read Tier 1 questions in their full §11 sources. That's the spine.

If you have 8 hours: add Tier 2.

If you have 16 hours: also read each chapter's §1-§10 once, scanning the SVG diagrams.

## Quick self-test

Pick any 5 questions at random from Tier 1. Write down your answer in 3-5 sentences. Compare against the §11 worked answer. If your answer is missing the source pointer, the follow-up, or the trade-off discussion, you're not done yet.
