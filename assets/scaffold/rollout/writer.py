from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from observability.metrics import emit_metric


ROLLOUT_DIR = Path(os.getenv("AGENT_ROLLOUT_DIR", "~/.my-agent/rollouts")).expanduser()


class RolloutWriter:
    def __init__(self, session_id: str):
        ROLLOUT_DIR.mkdir(parents=True, exist_ok=True)
        self.session_id = session_id
        self.path = ROLLOUT_DIR / f"{session_id}.jsonl"

    def write(self, turn: Any) -> None:
        record = asdict(turn)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        emit_metric(
            "turn_end",
            {
                "session_id": self.session_id,
                "turn_idx": record.get("idx"),
                "transition_reason": record.get("transition_reason"),
                "elapsed_ms": record.get("elapsed_ms", 0),
                "tool_uses": len(record.get("tool_uses") or []),
            },
        )
