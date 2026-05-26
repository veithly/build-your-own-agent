from __future__ import annotations

import os
import subprocess
from typing import Any


def verify_hard(turn: Any) -> bool:
    test_cmd = os.getenv("AGENT_TEST_CMD", "")
    if not test_cmd:
        return True
    try:
        result = subprocess.run(test_cmd, shell=True, capture_output=True, timeout=120)
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return False


TOKEN_BUDGET = int(os.getenv("AGENT_TOKEN_BUDGET", "200000"))
TOKEN_SOFT_THRESHOLD = 0.9


def verify_soft(turns: list[Any]) -> bool:
    total_tokens = sum(len((turn.assistant_msg or "")) // 4 for turn in turns)
    if total_tokens > TOKEN_BUDGET * TOKEN_SOFT_THRESHOLD:
        return False
    if len(turns) >= 3:
        recent = [len(turn.assistant_msg or "") // 4 for turn in turns[-3:]]
        if all(tokens < 500 for tokens in recent):
            return False
    return True


def verify_giveup(turn: Any) -> bool:
    return len(turn.tool_uses) == 0 and bool(turn.assistant_msg)
