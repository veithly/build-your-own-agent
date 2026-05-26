from __future__ import annotations

import json
import os
from pathlib import Path

from security.audit import audit_event
from security.scanner import scan_persistent_text


MEMORY_FILE = Path(os.getenv("AGENT_MEMORY_FILE", "~/.my-agent/memory.jsonl")).expanduser()


def read_all_memories() -> list[dict]:
    if not MEMORY_FILE.exists():
        return []
    out = []
    with MEMORY_FILE.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def write_memory(key: str, value: str) -> None:
    result = scan_persistent_text(key, value)
    if not result.allowed:
        audit_event("memory.reject", {"key": key[:80], "reason": result.reason}, "warn")
        raise ValueError(f"memory write rejected: {result.reason}")
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    record = {"key": key[:200], "value": value[:2200]}
    with MEMORY_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    audit_event("memory.write", {"key": record["key"][:80]}, "info")
