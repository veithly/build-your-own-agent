from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


METRICS_FILE = Path(os.getenv("AGENT_METRICS_FILE", "~/.my-agent/metrics.jsonl")).expanduser()


def emit_metric(event: str, fields: dict[str, Any] | None = None) -> None:
    METRICS_FILE.parent.mkdir(parents=True, exist_ok=True)
    record = {"ts": time.time(), "event": event, **(fields or {})}
    with METRICS_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
