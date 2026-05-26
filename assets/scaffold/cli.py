from __future__ import annotations

import sys
import uuid

from core.loop import run_loop


def fake_llm(msgs: list[dict]) -> dict:
    return {"text": "(placeholder)", "tool_uses": []}


def main() -> None:
    user_msg = " ".join(sys.argv[1:]) or "Hello agent"
    session_id = uuid.uuid4().hex[:8]
    turns = run_loop(session_id, user_msg, fake_llm)
    for turn in turns:
        print(f"Turn {turn.idx}: {turn.transition_reason} ({turn.elapsed_ms}ms)")


if __name__ == "__main__":
    main()
