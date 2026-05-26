from __future__ import annotations

import datetime
from typing import Any

from security.external import wrap_external_content
from skills.registry import list_bundled_skill_names


CACHE_BOUNDARY_LAYER = 3
CACHE_BOUNDARY_MARKER = "\n\n## Rolling Context\n"


def assemble_prompt(
    turns: list[Any],
    memory_frozen: str,
    user_msg: str | None,
    todo_snapshot: str | None = None,
) -> list[dict]:
    layers = [
        ("identity", "You are a coding agent. Take actions through tools."),
        ("tool_behavior", "Persist durable facts via memory tool. Read before write."),
        ("skills_index", _render_skills_index()),
        ("memory_snapshot", memory_frozen),
        ("timestamp", f"Current time: {datetime.datetime.now(datetime.UTC).isoformat()}"),
        ("task_progress", todo_snapshot or "## Task Progress\n(no active todo)"),
        ("transcript", _render_transcript(turns)),
    ]

    system_text = "\n\n".join(text for _, text in layers[: CACHE_BOUNDARY_LAYER + 1])
    rolling_text = "\n\n".join(text for _, text in layers[CACHE_BOUNDARY_LAYER + 1 :])
    msgs = [{"role": "system", "content": system_text + CACHE_BOUNDARY_MARKER + rolling_text}]
    if user_msg:
        msgs.append({"role": "user", "content": user_msg})
    return msgs


def _render_skills_index() -> str:
    names = list_bundled_skill_names()
    return "## Skills (bundled, allowlist only)\n" + "\n".join(f"- {name}" for name in names)


def _render_transcript(turns: list[Any]) -> str:
    if not turns:
        return "## Transcript (last 10 turns)\n(empty)"
    lines = []
    for turn in turns[-10:]:
        if turn.assistant_msg:
            lines.append(f"assistant: {turn.assistant_msg[:200]}")
        for result in turn.tool_results:
            wrapped = wrap_external_content(result.get("content", ""))
            lines.append(f"tool_result: {wrapped[:500]}")
    return "## Transcript (last 10 turns)\n" + "\n".join(lines)
