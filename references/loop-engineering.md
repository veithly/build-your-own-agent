# Loop engineering · the method behind Laws 1 & 4

How to make one agent loop production-grade. This is the method layer above the Iron Laws: Law 1 (turn is the source of truth) and Law 4 (three verifier tiers) are checkpoints; this file is the route between them.

Grounded in first-hand source reading (repos cloned to `research/` in the AgentStudy workspace; commits pinned below), not paraphrased blog posts.

## The five components

A bare `while True:` loop dies four ways in production: it won't stop, it repeats one error forever, its context blows up, or a crash loses everything. Five components cover all four. Wire them in this order.

| # | Component | Solves | Best readable implementation |
|---|-----------|--------|------------------------------|
| 1 | Stop conditions (multi-signal) | won't stop | smolagents `final_answer` tool + `final_answer_checks` |
| 2 | Budgets (3 dimensions) + grace call | runaway cost/time | mini-swe-agent `AgentConfig`; smolagents `_handle_max_steps_reached` |
| 3 | Error taxonomy + circuit breaker | one error forever | smolagents error split; mini-swe-agent consecutive counter |
| 4 | Trajectory persistence | crash loses all | mini-swe-agent `finally: save()`; Codex rollout JSONL |
| 5 | Verifier tiers | fake completion | Codex 4-chain (hard); smolagents checks (soft) |

## Component contracts (copy these, not vibes)

### 1 · Stop conditions

- "Done" must be a **structured action**, not free text. smolagents force-registers a `final_answer` tool; the loop condition is literally `while not returned_final_answer and step_number <= max_steps` (`agents.py`, commit `e3a5b89`).
- After the model claims done, run **completion checks** (`final_answer_checks` pattern: list of callbacks, any failure bounces the run back with feedback). The definition of done stays in your code.
- Never trust provider `stop_reason`. Claude Code counts tool_use blocks itself because `stop_reason === 'tool_use'` is sometimes wrong. The scaffold's `verify_giveup` already encodes this.
- Keep the hard cap (`max_turns`) as the last gate, not the only gate.

### 2 · Budgets

mini-swe-agent's `AgentConfig` (commit `a83fcae`) is the checklist — 4 of its 7 fields are safety nets:

```python
step_limit: int = 0                     # steps — stops spinning
cost_limit: float = 3.0                 # DOLLARS — stops wallet fires
wall_time_limit_seconds: int = 0        # wall clock — stops hangs on slow tools
max_consecutive_format_errors: int = 3  # circuit breaker
```

Rules:

- **All three dimensions.** Steps alone won't stop a hang on a slow tool; cost alone won't stop a free-tier infinite loop.
- **Check before the model call**, not after (mini-swe-agent puts all three checks at the top of `query()`).
- **Exhaustion gets a grace call.** smolagents' `_handle_max_steps_reached` makes one final `provide_final_answer(task)` call so the user gets "here's what I did and what's missing" instead of silence. Hermes calls this a grace call. The scaffold implements this as a `grace` turn before `budget_exceeded`.
- **Long tasks get periodic re-planning.** smolagents' `planning_interval` inserts a plan-only step every N steps — the anti-drift alarm clock. Optional for short loops.

### 3 · Error taxonomy

Two classes, two treatments (smolagents `_run_stream`):

```python
except AgentGenerationError as e:   # implementation bug → raise, exit
    raise e
except AgentError as e:             # model's mistake → record, feed back, continue
    action_step.error = e
```

- Your bugs raise; the model's mistakes feed back. Unclassified retry systems retry their most expensive bug until the budget dies.
- The breaker counts **consecutive** same-class failures (mini-swe-agent: 3 in a row exits; any clean step resets). It measures "stuck in one hole", not "total errors".
- What goes back into context is compacted: what failed, what was tried, what remains (12-Factor Factor 9). The Reflexion pattern (arXiv:2303.11366) goes further — a verbal reflection per failure, kept in a separate buffer, injected on retries; it took HumanEval pass@1 from 80% to 91% with no weight updates.

### 4 · Trajectory persistence

- Save **every step in a `finally`**, failures included (mini-swe-agent). After a crash the disk holds the complete last scene.
- **Exit is a message, not an escaping exception.** Every exit path appends a `role="exit"` record with an `exit_status` (`Submitted` / `LimitsExceeded` / `RepeatedFormatError`); exceptions are just transport. The exit reason lands in the trajectory automatically.
- Version the trajectory format (`trajectory_format: "mini-swe-agent-1.1"` — even the format string is versioned).
- The scaffold's rollout JSONL + `transition_reason` per turn is the same pattern; Codex's rollout is the maximal version (state rebuilt from the file after restart).

### 5 · Verifier tiers

Already Law 4. The loop-engineering addition: **verifier hardness sets the autonomy budget**. Hard verifiers (test exit codes, patch syntax) → let the loop run dozens of steps. Soft-only (LLM-as-judge, completion checks) → keep `max_turns` low and route to a human earlier. Don't give a research agent a coding agent's budget.

## Anti-patterns

| Anti-pattern | Why it kills you | Fix |
|--------------|------------------|-----|
| Budget = `max_turns` only | slow tool hangs forever, free-tier loops forever | 3 dimensions, checked pre-call |
| Silent budget exhaustion | user gets nothing after 90 steps of work | grace call before `budget_exceeded` |
| Retrying every error alike | most expensive bug retried until budget dies | taxonomy + consecutive breaker |
| Exit as escaping exception | exit reason lost in a stack trace | exit is a message with `exit_status` |
| Verifier only at the end | step 3 was wrong, steps 4-40 wasted | verify at every completion claim |
| Compression before persistence | you optimized a loop you can't debug | mini-swe-agent has 0 compression in 191 lines |

## Research sources

| Source | Version | What was read |
|--------|---------|---------------|
| [SWE-agent/mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent) | `a83fcae` | `src/minisweagent/agents/default.py` — all 191 lines |
| [huggingface/smolagents](https://github.com/huggingface/smolagents) | `e3a5b89` | `src/smolagents/agents.py` — `_run_stream`, `_handle_max_steps_reached`, `final_answer_checks`, `planning_interval` |
| [openai/codex](https://github.com/openai/codex) | `fa1d4c4` | `codex-rs/core/` rollout + loop modules |
| ReAct | [arXiv:2210.03629](https://arxiv.org/abs/2210.03629) | thought-action-observation structure |
| Reflexion | [arXiv:2303.11366](https://arxiv.org/abs/2303.11366) | verbal-feedback retries |
| 12-Factor Agents | [repo](https://github.com/humanlayer/12-factor-agents) | Factors 6/8/9/12 |

Long-form treatment with the same sources: docs-site `concepts/loop-engineering`. Four-harness comparison: book §2.
