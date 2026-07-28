from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from core.prompt import assemble_prompt
from core.tools import count_tool_uses, dispatch_tool_uses
from core.verifier import verify_giveup, verify_hard, verify_soft
from memory.snapshot import freeze_memory
from progress.todo import TodoStore
from rollout.writer import RolloutWriter


@dataclass
class Turn:
    idx: int
    user_msg: str | None
    assistant_msg: str | None = None
    tool_uses: list[dict] = field(default_factory=list)
    tool_results: list[dict] = field(default_factory=list)
    task_progress: list[dict] = field(default_factory=list)
    transition_reason: str = "start"
    elapsed_ms: int = 0
    cost_usd: float = 0.0


@dataclass
class LoopBudget:
    """Three budget dimensions, checked BEFORE each model call.

    Pattern: mini-swe-agent AgentConfig (commit a83fcae) — steps stop spinning,
    dollars stop wallet fires, wall-clock stops hangs on slow tools.
    0 disables a dimension (matching mini-swe-agent semantics).
    """

    max_turns: int = 50
    max_cost_usd: float = 3.0
    max_wall_seconds: int = 0
    max_consecutive_errors: int = 3

    def exhausted(self, turn_count: int, cost_usd: float, started_at: float) -> str | None:
        if 0 < self.max_turns <= turn_count:
            return "turns"
        if 0 < self.max_cost_usd <= cost_usd:
            return "cost"
        if 0 < self.max_wall_seconds <= time.monotonic() - started_at:
            return "wall_time"
        return None


GRACE_PROMPT = (
    "Budget is nearly exhausted. Do not start new work. "
    "Summarize what was accomplished, what remains, and the best next step."
)


def _consecutive_error_streak(results: list[dict]) -> int:
    streak = 0
    for r in reversed(results):
        if r.get("error"):
            streak += 1
        else:
            break
    return streak


def run_loop(
    session_id: str,
    user_msg: str,
    llm: Callable[[list[dict]], dict],
    max_turns: int = 50,
    budget: LoopBudget | None = None,
) -> list[Turn]:
    budget = budget or LoopBudget(max_turns=max_turns)
    turns: list[Turn] = []
    rollout = RolloutWriter(session_id)
    memory_frozen = freeze_memory()
    todo_store = TodoStore()
    started_at = time.monotonic()
    total_cost = 0.0
    error_streak = 0
    grace_pending = False

    i = 0
    while True:
        # Budget check BEFORE the model call (mini-swe-agent pattern).
        exhausted = budget.exhausted(i, total_cost, started_at)
        if exhausted and grace_pending:
            break  # grace turn already spent; stop for real
        grace_msg = None
        if exhausted:
            # One grace call: force a summary instead of a silent cutoff
            # (smolagents _handle_max_steps_reached / Hermes grace call).
            grace_msg = GRACE_PROMPT
            grace_pending = True

        t0 = time.monotonic()
        msgs = assemble_prompt(
            turns,
            memory_frozen,
            user_msg if i == 0 else grace_msg,
            todo_store.format_for_injection(),
        )
        resp = llm(msgs)
        todo_updates = resp.get("todo_updates") or resp.get("todos")
        if todo_updates is not None:
            todo_store.replace(todo_updates)

        turn = Turn(
            idx=i,
            user_msg=user_msg if i == 0 else grace_msg,
            assistant_msg=resp.get("text"),
            tool_uses=resp.get("tool_uses", []),
            task_progress=todo_store.items(),
            elapsed_ms=int((time.monotonic() - t0) * 1000),
            cost_usd=float(resp.get("cost_usd", 0.0)),
        )
        total_cost += turn.cost_usd

        if turn.tool_uses and not grace_pending:
            turn.tool_results = dispatch_tool_uses(turn.tool_uses)

        # Circuit breaker counts CONSECUTIVE failures; any clean dispatch resets
        # (mini-swe-agent max_consecutive_format_errors pattern).
        if turn.tool_results and all(r.get("error") for r in turn.tool_results):
            error_streak += _consecutive_error_streak(turn.tool_results)
        elif turn.tool_results:
            error_streak = 0

        candidate_turns = [*turns, turn]
        all_tools_errored = bool(turn.tool_results) and all(
            r.get("error") for r in turn.tool_results
        )
        if grace_pending:
            turn.transition_reason = "budget_exceeded"
        elif 0 < budget.max_consecutive_errors <= error_streak:
            turn.transition_reason = "repeated_errors"
        elif all_tools_errored:
            # A turn whose tool calls all failed is never "verified" — keep
            # looping so the model can recover (or the breaker can trip).
            turn.transition_reason = "continue"
        elif verify_hard(turn) and verify_soft(candidate_turns):
            turn.transition_reason = "verified"
        elif verify_giveup(turn):
            turn.transition_reason = "model_done"
        elif count_tool_uses(turn) == 0:
            turn.transition_reason = "no_more_tools"
        else:
            turn.transition_reason = "continue"

        rollout.write(turn)
        turns.append(turn)

        if turn.transition_reason != "continue":
            break
        i += 1

    return turns
