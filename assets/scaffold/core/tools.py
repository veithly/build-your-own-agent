from __future__ import annotations

import concurrent.futures
from typing import Any, Callable

from core.sandbox import sandbox_exec
from security.audit import audit_event


TOOL_REGISTRY: dict[str, Callable[[dict], dict]] = {}


def register_tool(name: str):
    def decorator(fn):
        TOOL_REGISTRY[name] = fn
        return fn

    return decorator


def can_use_tool(name: str, args: dict) -> tuple[bool, str]:
    default_deny = {"shell.rm_rf", "fs.delete_recursive"}
    if name in default_deny:
        return False, "tool is in default-deny list"
    return True, ""


def dispatch_tool_uses(tool_uses: list[dict]) -> list[dict]:
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = {}
        for tool_use in tool_uses:
            name = tool_use.get("name", "")
            args = tool_use.get("args", {})
            ok, reason = can_use_tool(name, args)
            if not ok:
                audit_event("tool.denied", {"name": name, "reason": reason}, "warn")
                results.append({"tool_use_id": tool_use.get("id"), "content": f"DENIED: {reason}", "error": True})
                continue
            fn = TOOL_REGISTRY.get(name)
            if fn is None:
                audit_event("tool.unknown", {"name": name}, "warn")
                results.append({"tool_use_id": tool_use.get("id"), "content": f"UNKNOWN_TOOL: {name}", "error": True})
                continue
            futures[executor.submit(fn, args)] = tool_use
        for future, tool_use in futures.items():
            try:
                result = future.result(timeout=30)
            except Exception as exc:
                audit_event("tool.error", {"name": tool_use.get("name", ""), "error": repr(exc)}, "warn")
                result = {"content": f"ERROR: {exc!r}", "error": True}
            results.append({"tool_use_id": tool_use.get("id"), **result})
    return results


def count_tool_uses(turn: Any) -> int:
    return len(turn.tool_uses)


@register_tool("shell.exec")
def shell_exec(args: dict) -> dict:
    return sandbox_exec(args.get("cmd", []), timeout=args.get("timeout_s", 30))
