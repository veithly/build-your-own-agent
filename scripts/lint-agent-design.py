#!/usr/bin/env python3
"""Lint an agent scaffold against the 10 Iron Laws plus task-progress advice.

Walks the Python files under the target directory and checks for the structural
markers each rule requires. Output two channels:

  text (default): human-readable PASS/FAIL with per-rule fix hint.
  json: machine-readable for CI integration.

Usage:
    python lint-agent-design.py /path/to/my-agent/
    python lint-agent-design.py /path/to/my-agent/ --format json
    python lint-agent-design.py /path/to/my-agent/ --rules R1,R2,R3   # subset
    python lint-agent-design.py /path/to/my-agent/ --strict           # fail on rule warnings too

Exit code 0 = all pass; 1 = at least one rule fails; 2 = bad input.

See references/diagnose-agent.md Flow A for what each rule means and the best
reference fix for each failure.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path


# ---------------------------------------------------------------------------
# Rule catalog. Each rule maps to one Iron Law and one best-reference fix.
# ---------------------------------------------------------------------------


@dataclass
class Rule:
    id: str
    title: str
    description: str
    fix: str
    reference: str  # which references/ file or REF/ path to consult


RULES: list[Rule] = [
    Rule(
        id="R1",
        title="Turn is source of truth",
        description="Each iteration ends with rollout.write(turn) and starts with Turn dataclass instantiation.",
        fix="Define Turn dataclass; in run_loop, call rollout.write(turn) before turns.append(turn).",
        reference="references/agent-scaffold.md File 1 (core/loop.py); Codex codex_thread.rs",
    ),
    Rule(
        id="R2",
        title="Context has a cache boundary",
        description="Prompt assembly has an explicit CACHE_BOUNDARY_LAYER constant; cached layers above, ephemeral below.",
        fix="In core/prompt.py: define CACHE_BOUNDARY_LAYER = N; concat layers 0..N as system_text, N+1.. as rolling_text.",
        reference="references/agent-scaffold.md File 2; book §3 context-system",
    ),
    Rule(
        id="R3",
        title="External content wrapped with nonce",
        description="wrap_external_content() uses secrets.token_hex for per-call session-unique nonce.",
        fix="In security/external.py: nonce = secrets.token_hex(8); wrap = f'<external_content_{nonce}>...</external_content_{nonce}>'.",
        reference="references/agent-scaffold.md File 10; OpenClaw external-content.ts",
    ),
    Rule(
        id="R4",
        title="Three verifier tiers always",
        description="verify_hard, verify_soft, verify_giveup all exist as separate functions.",
        fix="In core/verifier.py: define all three. hard = external truth (test exit code). soft = TOKEN_BUDGET + diminishing returns. give-up = no tool_use + assistant text.",
        reference="references/agent-scaffold.md File 4; book §5 verifier",
    ),
    Rule(
        id="R5",
        title="Sandbox first, then trust",
        description="Tool files use sandbox_exec; subprocess.run only inside core/sandbox.py.",
        fix="Replace subprocess.run(...) in tool files with sandbox_exec(...); the OS-specific sandbox lives in core/sandbox.py.",
        reference="references/agent-scaffold.md File 5; Codex codex-rs/sandboxes/",
    ),
    Rule(
        id="R6",
        title="Redact at import time, not log time",
        description="_REDACT_ENABLED = os.getenv(...) at module top of security/redact.py (within first ~15 lines).",
        fix="Snapshot the toggle once at import. Compile regex list at module top. LLM can't disable mid-turn.",
        reference="references/agent-scaffold.md File 9; Hermes redact.py",
    ),
    Rule(
        id="R7",
        title="fail_open default for scanners",
        description="Scanner/verifier exceptions are caught and return a permissive default + warning, not raised.",
        fix="Wrap every scanner call in try/except, return 'allow' on exception, log warning, increment audit counter.",
        reference="book §20 Q3; Hermes tirith fail_open=True default",
    ),
    Rule(
        id="R8",
        title="Frozen memory snapshot",
        description="freeze_memory() is called once at loop start; memory string is passed to assemble_prompt; no live reads inside prompt assembly.",
        fix="Add memory_frozen = freeze_memory() before the for-loop; pass it into assemble_prompt(turns, memory_frozen, ...).",
        reference="references/agent-scaffold.md File 6; Hermes frozen-snapshot pattern",
    ),
    Rule(
        id="R9",
        title="Bundled skill allowlist",
        description="skills/ directory exists with a registry that lists only bundled skills; no CLI-provided skill paths.",
        fix="Move skills under skills/bundled/. In skills/registry.py expose list_bundled_skill_names() over that dir only.",
        reference="references/agent-scaffold.md File 8; Codex core-skills crate",
    ),
    Rule(
        id="R10",
        title="Audit trail (rollout JSONL)",
        description="rollout/writer.py (or equivalent) appends one JSON line per turn to ~/.agent-name/rollouts/<session>.jsonl.",
        fix="Add rollout/writer.py with RolloutWriter.write(turn) that json.dumps(asdict(turn)) and appends with newline.",
        reference="references/agent-scaffold.md File 11; Codex codex-rs/core/src/rollout/",
    ),
]


# ---------------------------------------------------------------------------
# Lint result model
# ---------------------------------------------------------------------------


@dataclass
class Outcome:
    rule_id: str
    title: str
    status: str          # pass | fail | warn | skip
    detail: str = ""     # short reason
    fix: str = ""        # how to fix
    reference: str = ""  # where to read more

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class LintReport:
    target: str
    outcomes: list[Outcome] = field(default_factory=list)

    def add(self, outcome: Outcome) -> None:
        self.outcomes.append(outcome)

    def rule_outcomes(self) -> list[Outcome]:
        return [o for o in self.outcomes if o.rule_id.startswith("R")]

    def passes(self) -> int:
        return sum(1 for o in self.rule_outcomes() if o.status == "pass")

    def fails(self) -> int:
        return sum(1 for o in self.rule_outcomes() if o.status == "fail")

    def warns(self) -> int:
        return sum(1 for o in self.rule_outcomes() if o.status == "warn")

    def advisories(self) -> int:
        return sum(1 for o in self.outcomes if o.status == "advice")

    def to_dict(self) -> dict:
        return {
            "target": self.target,
            "passes": self.passes(),
            "fails": self.fails(),
            "warns": self.warns(),
            "advisories": self.advisories(),
            "outcomes": [o.to_dict() for o in self.outcomes],
        }


# ---------------------------------------------------------------------------
# File collection
# ---------------------------------------------------------------------------


SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules", "build", "dist", "site-packages"}


def collect_files(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in root.rglob("*.py"):
        if any(part in SKIP_DIRS or part.startswith(".") for part in p.parts):
            continue
        try:
            out[str(p.relative_to(root)).replace("\\", "/")] = p.read_text(encoding="utf-8", errors="replace")
        except (OSError, PermissionError, UnicodeDecodeError):
            continue
    return out


def _rule(rid: str) -> Rule:
    for r in RULES:
        if r.id == rid:
            return r
    raise KeyError(rid)


# ---------------------------------------------------------------------------
# Individual rule checks. Each returns an Outcome.
# ---------------------------------------------------------------------------


def check_r1(files: dict[str, str], blob: str) -> Outcome:
    r = _rule("R1")
    has_writer = bool(re.search(r"class\s+\w*Rollout\w*\b", blob)) or bool(re.search(r"def\s+write\s*\(.*turn", blob))
    has_turn = bool(re.search(r"class\s+Turn\b|@dataclass\s+class\s+Turn", blob))
    if has_writer and has_turn:
        return Outcome(r.id, r.title, "pass", "Turn class + rollout writer found")
    missing = []
    if not has_writer:
        missing.append("rollout writer")
    if not has_turn:
        missing.append("Turn dataclass")
    return Outcome(r.id, r.title, "fail", f"missing: {', '.join(missing)}", r.fix, r.reference)


def check_r2(blob: str) -> Outcome:
    r = _rule("R2")
    has_const = bool(re.search(r"\bCACHE_BOUNDARY(_LAYER)?\b", blob))
    if has_const:
        boundary_match = re.search(r"\bCACHE_BOUNDARY(?:_LAYER)?\s*=\s*(\d+)", blob)
        layer_names = re.findall(r"\(\s*[\"']([a-zA-Z0-9_ -]+)[\"']\s*,", blob)
        if boundary_match and "timestamp" in layer_names and "memory_snapshot" in layer_names:
            boundary = int(boundary_match.group(1))
            timestamp_idx = layer_names.index("timestamp")
            if boundary >= timestamp_idx:
                return Outcome(
                    r.id,
                    r.title,
                    "fail",
                    "timestamp is at or above CACHE_BOUNDARY; volatile state would break prefix cache",
                    "Move CACHE_BOUNDARY_LAYER below stable identity/tool/skills/memory layers and above timestamp/transcript.",
                    r.reference,
                )
        return Outcome(r.id, r.title, "pass", "CACHE_BOUNDARY constant found")
    has_concept = bool(re.search(r"cache.*boundary|cached.*ephemeral|prefix.*cache", blob, re.IGNORECASE))
    if has_concept:
        return Outcome(r.id, r.title, "warn", "cache-boundary mentioned but no explicit constant", r.fix, r.reference)
    return Outcome(r.id, r.title, "fail", "no CACHE_BOUNDARY constant nor prefix-cache references", r.fix, r.reference)


def check_r3(blob: str) -> Outcome:
    r = _rule("R3")
    has_helper = "wrap_external_content" in blob or "wrap_external" in blob
    has_nonce = "token_hex" in blob and "external_content_" in blob
    if has_helper and has_nonce:
        return Outcome(r.id, r.title, "pass", "wrap_external_content with token_hex nonce found")
    if has_helper:
        return Outcome(r.id, r.title, "warn", "wrap helper found but no token_hex nonce", r.fix, r.reference)
    return Outcome(r.id, r.title, "fail", "no external-content wrap with nonce", r.fix, r.reference)


def check_r4(blob: str) -> Outcome:
    r = _rule("R4")
    has_hard = "verify_hard" in blob
    has_soft = "verify_soft" in blob or "TOKEN_BUDGET" in blob
    has_giveup = "verify_giveup" in blob or "no_more_tools" in blob or "give_up" in blob
    if has_hard and has_soft and has_giveup:
        return Outcome(r.id, r.title, "pass", "hard + soft + give-up tiers present")
    missing = [n for n, v in [("hard", has_hard), ("soft", has_soft), ("give-up", has_giveup)] if not v]
    return Outcome(r.id, r.title, "fail", f"missing tiers: {', '.join(missing)}", r.fix, r.reference)


def check_r5(files: dict[str, str], blob: str) -> Outcome:
    r = _rule("R5")
    has_sandbox = "sandbox_exec" in blob
    if not has_sandbox:
        return Outcome(r.id, r.title, "fail", "no sandbox_exec wrapper found", r.fix, r.reference)
    leaked: list[str] = []
    for path, content in files.items():
        if path.endswith("core/sandbox.py") or path.endswith("sandbox.py") and "/core/" in path:
            continue
        if "subprocess.run" in content and "sandbox_exec" not in content:
            if "tools" in path.lower() or "shell" in path.lower() or "exec" in path.lower():
                leaked.append(path)
    if leaked:
        return Outcome(r.id, r.title, "fail", f"subprocess.run outside sandbox in: {', '.join(leaked[:3])}", r.fix, r.reference)
    return Outcome(r.id, r.title, "pass", "sandbox_exec routed; no leaks detected in tool files")


def check_r6(files: dict[str, str]) -> Outcome:
    r = _rule("R6")
    for path, content in files.items():
        if path.endswith("redact.py") or "/redact" in path:
            head = "\n".join(content.splitlines()[:25])
            if re.search(r"^_?REDACT_ENABLED\s*=\s*os\.getenv", head, re.MULTILINE):
                return Outcome(r.id, r.title, "pass", f"REDACT_ENABLED snapshotted at top of {path}")
            return Outcome(r.id, r.title, "fail", f"redact module {path} doesn't snapshot REDACT_ENABLED at top", r.fix, r.reference)
    return Outcome(r.id, r.title, "fail", "no redact module found", r.fix, r.reference)


def check_r7(files: dict[str, str], blob: str) -> Outcome:
    r = _rule("R7")
    scanner_text = "\n".join(
        content for path, content in files.items()
        if "scanner" in path.lower() or "scan" in path.lower()
    )
    if not scanner_text:
        return Outcome(r.id, r.title, "fail", "no scanner module found", r.fix, r.reference)
    has_fail_open = "fail_open" in scanner_text.lower() or "fail-open" in scanner_text.lower()
    has_exception_guard = bool(re.search(r"except\s+Exception\b[\s\S]{0,300}return\s+\w+\(\s*True", scanner_text))
    has_audit = "audit_event" in scanner_text or "audit" in scanner_text.lower()
    if has_fail_open and has_exception_guard and has_audit:
        return Outcome(r.id, r.title, "pass", "scanner has fail_open exception path and audit event")
    missing = []
    if not has_fail_open:
        missing.append("fail_open marker")
    if not has_exception_guard:
        missing.append("exception returns permissive result")
    if not has_audit:
        missing.append("audit on scanner decisions/errors")
    return Outcome(r.id, r.title, "fail", f"scanner incomplete: {', '.join(missing)}", r.fix, r.reference)


def check_r8(blob: str) -> Outcome:
    r = _rule("R8")
    has_freeze = "freeze_memory" in blob
    has_snapshot = "memory_snapshot" in blob or "memory_frozen" in blob or "frozen" in blob
    if has_freeze or has_snapshot:
        return Outcome(r.id, r.title, "pass", "freeze_memory / snapshot pattern found")
    return Outcome(r.id, r.title, "fail", "no freeze_memory() / snapshot pattern", r.fix, r.reference)


def check_r9(root: Path, blob: str) -> Outcome:
    r = _rule("R9")
    skills_dir = root / "skills"
    bundled_dir = skills_dir / "bundled"
    has_dir = skills_dir.exists()
    has_bundled = bundled_dir.exists()
    has_registry = "list_bundled" in blob or "bundled_skill" in blob.lower()
    if has_dir and has_registry and has_bundled:
        return Outcome(r.id, r.title, "pass", "skills/bundled + list_bundled_* registry found")
    if has_dir and has_registry:
        return Outcome(r.id, r.title, "warn", "skills/ + registry but no skills/bundled/ subdir", r.fix, r.reference)
    return Outcome(r.id, r.title, "fail", "no skills/ allowlist registry", r.fix, r.reference)


def check_r10(root: Path) -> Outcome:
    r = _rule("R10")
    writers = list(root.rglob("rollout/writer.py")) + list(root.rglob("rollout.py"))
    has_rollout = False
    for f in writers:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except (OSError, PermissionError):
            continue
        if ".jsonl" in text:
            has_rollout = True
            break
    if not has_rollout:
        return Outcome(r.id, r.title, "fail", "no rollout writer producing .jsonl", r.fix, r.reference)
    audit_files = list(root.rglob("security/audit.py")) + list(root.rglob("audit.py"))
    has_audit = False
    for f in audit_files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except (OSError, PermissionError):
            continue
        if ".jsonl" in text and "audit_event" in text:
            has_audit = True
            break
    if has_audit:
        return Outcome(r.id, r.title, "pass", "rollout JSONL + security audit JSONL found")
    return Outcome(
        r.id,
        r.title,
        "warn",
        "rollout JSONL found, but no security audit JSONL writer",
        "Add security/audit.py and log denials, scanner rejects, sandbox denials, and redaction hits.",
        r.reference,
    )


def check_p1(root: Path, files: dict[str, str], blob: str) -> Outcome:
    title = "Task progress surface"
    has_progress_module = any(path.endswith("progress/todo.py") for path in files)
    has_todo_store = "TodoStore" in blob or "todo_updates" in blob or "task_progress" in blob
    has_single_active_guard = (
        "in_progress_count" in blob
        or "at most one in_progress" in blob
        or "single in_progress" in blob
    )
    has_statuses = all(status in blob for status in ("pending", "in_progress", "completed"))
    has_injection = "format_for_injection" in blob or "Task Progress" in blob

    if has_progress_module and has_todo_store and has_single_active_guard and has_statuses and has_injection:
        return Outcome(
            "P1",
            title,
            "pass",
            "progress/todo.py with status machine, single-active guard, and prompt injection found",
        )

    missing = []
    if not (has_progress_module or has_todo_store):
        missing.append("progress store")
    if not has_statuses:
        missing.append("pending/in_progress/completed statuses")
    if not has_single_active_guard:
        missing.append("single in_progress guard")
    if not has_injection:
        missing.append("unfinished-work prompt injection")

    detail = "missing: " + ", ".join(missing) if missing else "task-progress surface is incomplete"
    return Outcome(
        "P1",
        title,
        "advice",
        detail,
        "Add progress/todo.py or an equivalent current-focus checklist; keep approval plans and long-term memory separate.",
        "references/agent-scaffold.md File 12; book §21 todo-list; book §22 execution-state surfaces",
    )


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def lint(root: Path, only: set[str] | None = None) -> LintReport:
    report = LintReport(target=str(root))
    files = collect_files(root)
    if not files:
        for r in RULES:
            if only and r.id not in only:
                continue
            report.add(Outcome(r.id, r.title, "skip", "no Python files under target"))
        return report
    blob = "\n".join(files.values())

    runners = [
        ("R1", lambda: check_r1(files, blob)),
        ("R2", lambda: check_r2(blob)),
        ("R3", lambda: check_r3(blob)),
        ("R4", lambda: check_r4(blob)),
        ("R5", lambda: check_r5(files, blob)),
        ("R6", lambda: check_r6(files)),
        ("R7", lambda: check_r7(files, blob)),
        ("R8", lambda: check_r8(blob)),
        ("R9", lambda: check_r9(root, blob)),
        ("R10", lambda: check_r10(root)),
        ("P1", lambda: check_p1(root, files, blob)),
    ]
    for rid, runner in runners:
        if only and rid not in only:
            continue
        try:
            outcome = runner()
        except Exception as e:  # pragma: no cover — defensive
            if rid.startswith("R"):
                r = _rule(rid)
                outcome = Outcome(rid, r.title, "fail", f"linter internal error: {e!r}", r.fix, r.reference)
            else:
                outcome = Outcome(rid, "Task progress surface", "advice", f"advisory internal error: {e!r}")
        report.add(outcome)
    return report


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


STATUS_TAG = {
    "pass": "PASS",
    "fail": "FAIL",
    "warn": "WARN",
    "skip": "SKIP",
    "advice": "ADVICE",
}


def render_text(report: LintReport) -> str:
    lines: list[str] = []
    lines.append(f"Lint target: {report.target}")
    lines.append("")
    for o in report.outcomes:
        tag = STATUS_TAG.get(o.status, o.status.upper())
        lines.append(f"{tag} · {o.rule_id} {o.title}")
        if o.detail:
            lines.append(f"     {o.detail}")
        if o.status in ("fail", "warn", "advice") and o.fix:
            lines.append(f"     fix: {o.fix}")
        if o.status in ("fail", "warn", "advice") and o.reference:
            lines.append(f"     read: {o.reference}")
    lines.append("")
    total_rules = len(report.rule_outcomes())
    lines.append(f"{report.passes()}/{total_rules} rules passing.")
    if report.fails():
        lines.append(f"{report.fails()} fail(s).")
    if report.warns():
        lines.append(f"{report.warns()} warning(s).")
    if report.advisories():
        lines.append(f"{report.advisories()} advisory finding(s).")
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description="Lint an agent scaffold against the 10 Iron Laws plus task-progress advice")
    p.add_argument("path", help="path to agent root directory")
    p.add_argument("--format", choices=["text", "json"], default="text")
    p.add_argument("--rules", default=None, help="comma-separated subset, e.g. R1,R2,R5")
    p.add_argument("--strict", action="store_true", help="treat warnings as failures")
    args = p.parse_args()

    root = Path(args.path).expanduser().resolve()
    if not root.exists():
        print(f"ERROR: {root} does not exist", file=sys.stderr)
        return 2

    only: set[str] | None = None
    if args.rules:
        only = {r.strip().upper() for r in args.rules.split(",") if r.strip()}

    report = lint(root, only=only)

    if args.format == "json":
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(render_text(report))

    bad = report.fails()
    if args.strict:
        bad += report.warns()
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
