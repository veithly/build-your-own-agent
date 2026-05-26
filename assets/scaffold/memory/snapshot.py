from __future__ import annotations

from memory.store import read_all_memories


def freeze_memory() -> str:
    memories = read_all_memories()
    if not memories:
        return "## Persistent Memory\n(empty)"
    lines = ["## Persistent Memory"]
    for memory in memories:
        lines.append(f"- {memory['key']}: {memory['value'][:300]}")
    return "\n".join(lines)
