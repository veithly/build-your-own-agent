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


def run_loop(
    session_id: str,
    user_msg: str,
    llm: Callable[[list[dict]], dict],
    max_turns: int = 50,
) -> list[Turn]:
    turns: list[Turn] = []
    rollout = RolloutWriter(session_id)
    memory_frozen = freeze_memory()
    todo_store = TodoStore()

    for i in range(max_turns):
        t0 = time.monotonic()
        msgs = assemble_prompt(
            turns,
            memory_frozen,
            user_msg if i == 0 else None,
            todo_store.format_for_injection(),
        )
        resp = llm(msgs)
        todo_updates = resp.get("todo_updates") or resp.get("todos")
        if todo_updates is not None:
            todo_store.replace(todo_updates)

        turn = Turn(
            idx=i,
            user_msg=user_msg if i == 0 else None,
            assistant_msg=resp.get("text"),
            tool_uses=resp.get("tool_uses", []),
            task_progress=todo_store.items(),
            elapsed_ms=int((time.monotonic() - t0) * 1000),
        )

        if turn.tool_uses:
            turn.tool_results = dispatch_tool_uses(turn.tool_uses)

        candidate_turns = [*turns, turn]
        if verify_hard(turn) and verify_soft(candidate_turns):
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

    return turns
