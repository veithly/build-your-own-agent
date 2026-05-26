from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path

from security.audit import audit_event


PROJECT_ROOT = Path(os.getenv("AGENT_PROJECT_ROOT", os.getcwd())).resolve()
ALLOW_PROCESS_ONLY = os.getenv("AGENT_ALLOW_PROCESS_ONLY_SANDBOX", "false").lower() == "true"


def sandbox_exec(cmd: list[str], timeout: int = 30) -> dict:
    system = platform.system()
    if system == "Darwin":
        return _seatbelt(cmd, timeout)
    if system == "Linux":
        return _bwrap(cmd, timeout)
    return _process_only(cmd, timeout)


def _seatbelt(cmd: list[str], timeout: int) -> dict:
    project_root = str(PROJECT_ROOT).replace('"', '\\"')
    profile = f"""
(version 1)
(deny default)
(allow process-exec process-fork)
(allow file-read*)
(allow file-write* (subpath "{project_root}"))
"""
    return _run(["sandbox-exec", "-p", profile, "--", *cmd], timeout)


def _bwrap(cmd: list[str], timeout: int) -> dict:
    wrapped = [
        "bwrap",
        "--ro-bind",
        "/",
        "/",
        "--bind",
        str(PROJECT_ROOT),
        str(PROJECT_ROOT),
        "--unshare-net",
        "--die-with-parent",
        "--",
        *cmd,
    ]
    return _run(wrapped, timeout)


def _process_only(cmd: list[str], timeout: int) -> dict:
    audit_event("sandbox.process_only", {"platform": platform.system()}, "warn")
    if not ALLOW_PROCESS_ONLY:
        return {
            "content": "DENIED: no OS sandbox backend available. Set AGENT_ALLOW_PROCESS_ONLY_SANDBOX=true for local development only.",
            "error": True,
            "exit_code": 126,
        }
    result = _run(cmd, timeout)
    result["content"] = "WARNING: process-only fallback is not a production sandbox.\n" + result["content"]
    return result


def _run(cmd: list[str], timeout: int) -> dict:
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout,
            text=True,
            cwd=PROJECT_ROOT,
        )
        if result.returncode != 0:
            audit_event("sandbox.denial_or_error", {"exit_code": result.returncode}, "warn")
        return {
            "content": (result.stdout + result.stderr)[:8000],
            "error": result.returncode != 0,
            "exit_code": result.returncode,
        }
    except subprocess.TimeoutExpired:
        audit_event("sandbox.timeout", {"timeout": timeout}, "warn")
        return {"content": "TIMEOUT", "error": True, "exit_code": -1}
    except FileNotFoundError as exc:
        audit_event("sandbox.exec_not_found", {"error": str(exc)}, "warn")
        return {"content": f"EXEC_NOT_FOUND: {exc}", "error": True, "exit_code": 127}
