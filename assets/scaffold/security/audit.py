from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


AUDIT_FILE = Path(os.getenv("AGENT_AUDIT_FILE", "~/.my-agent/audit.jsonl")).expanduser()


def audit_event(event: str, detail: dict[str, Any] | None = None, severity: str = "info") -> None:
    AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": time.time(),
        "event": event,
        "severity": severity,
        "detail": detail or {},
    }
    with AUDIT_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
