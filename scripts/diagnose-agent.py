#!/usr/bin/env python3
"""Diagnose an agent at runtime by reading rollout JSONLs.

Detects the 9 anti-patterns documented in references/diagnose-agent.md:

  AP-1  Tool loop (same tool + args called >= 3 times in 5 turns)
  AP-2  Cache miss / cost spike (per-turn tokens grow within a session)
  AP-3  Verifier silent failure (no 'verified' transition, only 'model_done')
  AP-4  No external-content wrap (tool result text without nonce marker)
  AP-5  Memory thrash (memory write events dominate a session)
  AP-6  Sandbox bypass attempt (sandbox EXIT != 0 with permission-error patterns)
  AP-7  Transition reason missing / always-same-value
  AP-8  subprocess.run outside sandbox (static cross-check on the agent dir)
  AP-9  Task progress stale / malformed (missing updates or multiple in_progress items)

Usage:
    python diagnose-agent.py /path/to/rollouts/ --allow-empty
    python diagnose-agent.py /path/to/rollouts/ --session=<id>
    python diagnose-agent.py /path/to/rollouts/ --format=json
    python diagnose-agent.py /path/to/rollouts/ --metrics=/path/to/metrics.jsonl
    python diagnose-agent.py /path/to/rollouts/ --agent-src=/path/to/agent_repo  # enables AP-8
    python diagnose-agent.py /path/to/rollouts/ --allow-empty                  # CI bootstrap

Exit code 0 = no findings; 1 = one or more findings; 2 = bad input.

Output structure:

  text (default): one section per anti-pattern triggered, with: severity,
    affected sessions, evidence, and best-reference fix pointer.
  json: machine-readable for CI integration.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterable


# ---------------------------------------------------------------------------
# Anti-pattern catalog. Kept in sync with references/diagnose-agent.md.
# ---------------------------------------------------------------------------

ANTI_PATTERNS: dict[str, dict[str, str]] = {
    "AP-1": {
        "name": "Tool loop",
        "severity": "high",
        "fix": "Add diminishing-returns branch in verify_soft (Claude Code TOKEN_BUDGET pattern). See agent-scaffold.md File 4.",
    },
    "AP-2": {
        "name": "Cache miss / cost spike",
        "severity": "high",
        "fix": "Re-check CACHE_BOUNDARY_LAYER position. Timestamp + ephemeral state must be BELOW the boundary. See build-agent-workflow.md Phase 4 Test 2.",
    },
    "AP-3": {
        "name": "Verifier silent failure",
        "severity": "medium",
        "fix": "Wire a real verify_hard signal (test exit code for coding agent; domain validator otherwise). See diagnose-agent.md Flow B AP-3.",
    },
    "AP-4": {
        "name": "No external-content wrap",
        "severity": "high",
        "fix": "Apply wrap_external_content() at every external-content entry. See agent-scaffold.md File 10 (security/external.py).",
    },
    "AP-5": {
        "name": "Memory thrash",
        "severity": "medium",
        "fix": "Tighten memory write criteria + add temporal decay (OpenClaw halfLifeDays=30). See diagnose-agent.md AP-5.",
    },
    "AP-6": {
        "name": "Sandbox bypass attempt",
        "severity": "high",
        "fix": "Investigate denied calls. Categorize legit vs malicious; allowlist legit in AGENTS.md, alert on suspicious. See diagnose-agent.md AP-6.",
    },
    "AP-7": {
        "name": "Transition reason missing or always-same",
        "severity": "medium",
        "fix": "Assert turn.transition_reason set before rollout.write. Healthy distribution: verified 40-60%, model_done 30-40%, others <10% each.",
    },
    "AP-8": {
        "name": "subprocess.run outside sandbox",
        "severity": "high",
        "fix": "Replace subprocess.run() with sandbox_exec() in tool files. Add pre-commit hook to enforce. See agent-scaffold.md File 5.",
    },
    "AP-9": {
        "name": "Task progress stale or malformed",
        "severity": "medium",
        "fix": "Add a current-focus todo/progress surface. Enforce at most one in_progress item and refresh it during long work. See agent-scaffold.md File 12, book §21, and §22 for multi-surface routing.",
    },
}


# Wrap marker from the scaffold (security/external.py). The nonce is hex; the
# prefix is stable so we can detect "wrapped" vs "raw" tool results.
EXTERNAL_WRAP_RE = re.compile(r"<external_content_[0-9a-f]{8,}>")

# Sandbox permission-error fingerprints (multiple OS).
SANDBOX_DENIAL_RE = re.compile(
    r"(Operation not permitted|sandbox-exec|EACCES|EPERM|seatbelt|bwrap|landlock)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class Turn:
    """Minimal view of a rollout turn record. Tolerant of missing fields."""

    idx: int
    transition_reason: str | None = None
    assistant_msg: str | None = None
    tool_uses: list[dict] = field(default_factory=list)
    tool_results: list[dict] = field(default_factory=list)
    elapsed_ms: int = 0
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_record(cls, rec: dict) -> "Turn":
        return cls(
            idx=int(rec.get("idx", -1)),
            transition_reason=rec.get("transition_reason"),
            assistant_msg=rec.get("assistant_msg"),
            tool_uses=rec.get("tool_uses") or [],
            tool_results=rec.get("tool_results") or [],
            elapsed_ms=int(rec.get("elapsed_ms", 0)),
            raw=rec,
        )


@dataclass
class Session:
    session_id: str
    turns: list[Turn] = field(default_factory=list)
    path: Path | None = None

    def final_reason(self) -> str:
        for t in reversed(self.turns):
            if t.transition_reason and t.transition_reason != "start":
                return t.transition_reason
        return "unknown"


@dataclass
class Finding:
    ap: str
    name: str
    severity: str
    session_ids: list[str]
    evidence: list[str]
    fix: str

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Rollout loading
# ---------------------------------------------------------------------------


def load_sessions(rollout_dir: Path, session_filter: str | None = None) -> list[Session]:
    sessions: list[Session] = []
    if not rollout_dir.exists():
        print(f"ERROR: rollouts dir not found: {rollout_dir}", file=sys.stderr)
        sys.exit(2)
    for f in sorted(rollout_dir.rglob("*.jsonl")):
        sid = f.stem
        if session_filter and session_filter not in sid:
            continue
        turns: list[Turn] = []
        try:
            for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                turns.append(Turn.from_record(rec))
        except (OSError, PermissionError):
            continue
        if not turns:
            continue
        sessions.append(Session(session_id=sid, turns=turns, path=f))
    return sessions


def load_metrics(metrics_path: Path | None) -> list[dict]:
    if not metrics_path or not metrics_path.exists():
        return []
    out: list[dict] = []
    for line in metrics_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


# ---------------------------------------------------------------------------
# Detectors. Each returns (sessions_hit, evidence_lines).
# ---------------------------------------------------------------------------


def detect_tool_loop(sessions: Iterable[Session]) -> Finding | None:
    """AP-1: same tool name+args called >=3 times within any 5-turn sliding window."""
    hits: list[str] = []
    evidence: list[str] = []
    for s in sessions:
        window: collections.deque[tuple[str, str]] = collections.deque(maxlen=5)
        for t in s.turns:
            for tu in t.tool_uses:
                name = tu.get("name", "")
                args_key = json.dumps(tu.get("args") or tu.get("input") or {}, sort_keys=True)[:200]
                window.append((name, args_key))
            counts = collections.Counter(window)
            for (n, k), c in counts.items():
                if c >= 3 and not n.startswith("_"):
                    hits.append(s.session_id)
                    evidence.append(f"{s.session_id} turn {t.idx}: tool '{n}' called {c}x in 5-turn window")
                    break
            else:
                continue
            break
    if not hits:
        return None
    return _finding("AP-1", hits, evidence[:10])


def detect_cache_spike(sessions: Iterable[Session], metrics: list[dict]) -> Finding | None:
    """AP-2: per-turn tokens_in grows monotonically beyond expected transcript growth.

    Heuristic: within a session, if the LAST turn's tokens_in is > 3x the FIRST
    turn's, and the session has >= 6 turns, flag it. (Healthy cache keeps the
    common prefix flat; only the rolling transcript grows.)
    """
    if not metrics:
        return None
    per_session_tokens: dict[str, list[int]] = collections.defaultdict(list)
    for e in metrics:
        if e.get("event") == "turn_end" and "tokens_in" in e and "session_id" in e:
            per_session_tokens[e["session_id"]].append(int(e["tokens_in"]))
    hits: list[str] = []
    evidence: list[str] = []
    for sid, toks in per_session_tokens.items():
        if len(toks) < 6:
            continue
        first, last = toks[0], toks[-1]
        if first > 0 and last > first * 3:
            hits.append(sid)
            evidence.append(f"{sid}: tokens_in grew {first} → {last} over {len(toks)} turns (>3x)")
    if not hits:
        return None
    return _finding("AP-2", hits, evidence[:10])


def detect_verifier_silent(sessions: list[Session]) -> Finding | None:
    """AP-3: across sessions, no session ends with transition_reason == 'verified'.

    Or: 'verified' rate is < 5% of completed sessions. Indicates verify_hard
    is either disabled or always returns True (and then soft picks up).
    """
    if not sessions:
        return None
    reasons = collections.Counter(s.final_reason() for s in sessions)
    total = sum(reasons.values())
    if total < 5:
        return None
    verified = reasons.get("verified", 0)
    rate = verified / total if total else 0
    if rate >= 0.05:
        return None
    hits = [s.session_id for s in sessions if s.final_reason() != "verified"][:10]
    evidence = [f"verified={verified}/{total} ({rate:.1%}). Distribution: {dict(reasons)}"]
    return _finding("AP-3", hits, evidence)


def detect_no_external_wrap(sessions: Iterable[Session]) -> Finding | None:
    """AP-4: tool_results contain text that looks instructional but isn't wrapped.

    Two-channel detector:
      Channel 1 (high confidence): ANY unwrapped tool_result containing an
        injection keyword. One hit is enough — that's an active attack signal.
      Channel 2 (low confidence): >=3 long (>=200 char) unwrapped tool_results
        in one session — indicates the wrap is missing on the path even if
        no injection has landed yet.
    """
    INSTRUCTIONAL = re.compile(
        r"\b(ignore previous|forget instructions|you are now|jailbroken|act as|system: |disregard|override)",
        re.IGNORECASE,
    )
    hits: list[str] = []
    evidence: list[str] = []
    for s in sessions:
        unwrapped_long = 0
        injection_example: str | None = None
        for t in s.turns:
            for tr in t.tool_results:
                content = tr.get("content") or ""
                if not isinstance(content, str):
                    continue
                if EXTERNAL_WRAP_RE.search(content):
                    continue
                if INSTRUCTIONAL.search(content):
                    if injection_example is None:
                        injection_example = content[:120]
                if len(content) >= 200:
                    unwrapped_long += 1
        if injection_example is not None:
            hits.append(s.session_id)
            evidence.append(f"{s.session_id}: unwrapped tool_result contains injection-keyword; example: {injection_example!r}")
        elif unwrapped_long >= 3:
            hits.append(s.session_id)
            evidence.append(f"{s.session_id}: {unwrapped_long} long unwrapped tool_results (no wrap on external-content path)")
    if not hits:
        return None
    return _finding("AP-4", hits, evidence[:10])


def detect_memory_thrash(sessions: Iterable[Session]) -> Finding | None:
    """AP-5: memory write events dominate a session (> 30% of tool calls)."""
    hits: list[str] = []
    evidence: list[str] = []
    for s in sessions:
        total = 0
        memory_writes = 0
        for t in s.turns:
            for tu in t.tool_uses:
                total += 1
                name = (tu.get("name") or "").lower()
                if "memory" in name and any(k in name for k in ("write", "save", "store", "remember", "update")):
                    memory_writes += 1
        if total >= 10 and memory_writes / total > 0.3:
            hits.append(s.session_id)
            evidence.append(f"{s.session_id}: {memory_writes}/{total} tool calls are memory writes ({memory_writes/total:.0%})")
    if not hits:
        return None
    return _finding("AP-5", hits, evidence[:10])


def detect_sandbox_denial(sessions: Iterable[Session]) -> Finding | None:
    """AP-6: tool_result content matches sandbox-denial fingerprints.

    Not all denials are bad (legit attempts also fail). We flag the session
    list for human review; the user decides whether each is benign or attack.
    """
    hits: list[str] = []
    evidence: list[str] = []
    for s in sessions:
        denials_in_session = 0
        first_example: str | None = None
        for t in s.turns:
            for tr in t.tool_results:
                content = tr.get("content") or ""
                if not isinstance(content, str):
                    continue
                if SANDBOX_DENIAL_RE.search(content):
                    denials_in_session += 1
                    if first_example is None:
                        first_example = content[:140]
        if denials_in_session >= 1:
            hits.append(s.session_id)
            evidence.append(f"{s.session_id}: {denials_in_session} sandbox denial(s); example: {first_example!r}")
    if not hits:
        return None
    return _finding("AP-6", hits, evidence[:10])


def detect_transition_reason_anomaly(sessions: list[Session]) -> Finding | None:
    """AP-7: transition_reason missing or one value dominates > 95%."""
    if not sessions:
        return None
    final_reasons = [s.final_reason() for s in sessions]
    if not final_reasons:
        return None
    counts = collections.Counter(final_reasons)
    total = sum(counts.values())
    most_common, n = counts.most_common(1)[0]
    if most_common == "unknown" and n / total >= 0.5:
        evidence = [f"{n}/{total} sessions have no transition_reason at all"]
        hits = [s.session_id for s in sessions if s.final_reason() == "unknown"][:10]
        return _finding("AP-7", hits, evidence)
    if n / total > 0.95 and total >= 10:
        evidence = [f"{n}/{total} ({n/total:.0%}) sessions all end with transition_reason={most_common!r}. Healthy: at least 3 distinct values."]
        hits = [s.session_id for s in sessions[:10]]
        return _finding("AP-7", hits, evidence)
    return None


def detect_subprocess_outside_sandbox(agent_src: Path | None) -> Finding | None:
    """AP-8: static cross-check. Skipped if --agent-src not provided."""
    if not agent_src or not agent_src.exists():
        return None
    hits: list[str] = []
    evidence: list[str] = []
    SUBPROC_RE = re.compile(r"subprocess\.run\s*\(")
    SANDBOX_RE = re.compile(r"sandbox_exec\s*\(")
    for f in agent_src.rglob("*.py"):
        if any(part in (".venv", "__pycache__", ".git", "node_modules", "build", "dist") for part in f.parts):
            continue
        rel = str(f.relative_to(agent_src))
        if rel.replace("\\", "/").endswith("core/sandbox.py"):
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except (OSError, PermissionError):
            continue
        if SUBPROC_RE.search(text) and not SANDBOX_RE.search(text):
            hits.append(rel)
            evidence.append(f"{rel}: subprocess.run() without sandbox_exec()")
    if not hits:
        return None
    return _finding("AP-8", hits, evidence[:20])


def detect_task_progress_stale(sessions: Iterable[Session]) -> Finding | None:
    """AP-9: long sessions with no progress updates, stale updates, or malformed active state."""
    hits: list[str] = []
    evidence: list[str] = []
    for s in sessions:
        progress_turns: list[int] = []
        malformed = False
        for t in s.turns:
            items = _extract_progress_items(t.raw)
            if items or _has_progress_tool_use(t):
                progress_turns.append(t.idx)

            in_progress = [
                item for item in items
                if str(item.get("status") or item.get("state") or "").lower() == "in_progress"
            ]
            if len(in_progress) > 1:
                malformed = True
                hits.append(s.session_id)
                evidence.append(f"{s.session_id} turn {t.idx}: {len(in_progress)} in_progress items")
                break

        if malformed:
            continue

        tool_turns = sum(1 for t in s.turns if t.tool_uses or t.tool_results)
        if len(s.turns) >= 8 and tool_turns >= 4 and not progress_turns:
            hits.append(s.session_id)
            evidence.append(f"{s.session_id}: {len(s.turns)} turns and {tool_turns} tool-active turns, but no structured progress updates")
            continue

        if progress_turns:
            final_idx = max(t.idx for t in s.turns)
            stale_gap = final_idx - max(progress_turns)
            if stale_gap >= 10:
                hits.append(s.session_id)
                evidence.append(f"{s.session_id}: last progress update at turn {max(progress_turns)}, final turn {final_idx} (gap {stale_gap})")

    if not hits:
        return None
    return _finding("AP-9", hits, evidence[:20])


def _has_progress_tool_use(turn: Turn) -> bool:
    progress_re = re.compile(r"(update_plan|todowrite|todo|task_progress|progress\.update|taskupdate)", re.IGNORECASE)
    for tool_use in turn.tool_uses:
        name = str(tool_use.get("name") or tool_use.get("tool") or "")
        if progress_re.search(name):
            return True
    return False


def _extract_progress_items(value: Any, depth: int = 0) -> list[dict]:
    if depth > 3:
        return []
    if isinstance(value, list):
        items: list[dict] = []
        for item in value:
            items.extend(_extract_progress_items(item, depth + 1))
        return items
    if not isinstance(value, dict):
        return []

    if _looks_like_progress_item(value):
        return [value]

    items: list[dict] = []
    for key in ("todos", "todo", "items", "plan", "task_progress", "tasks", "todo_updates", "tool_uses", "tool_results"):
        if key in value:
            items.extend(_extract_progress_items(value[key], depth + 1))
    for key in ("args", "input", "params", "payload"):
        nested = value.get(key)
        if isinstance(nested, (dict, list)):
            items.extend(_extract_progress_items(nested, depth + 1))
    return items


def _looks_like_progress_item(value: dict) -> bool:
    has_status = "status" in value or "state" in value
    has_text = any(k in value for k in ("content", "step", "subject", "title", "activeForm", "active_form"))
    return has_status and has_text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _finding(ap: str, hits: list[str], evidence: list[str]) -> Finding:
    meta = ANTI_PATTERNS[ap]
    seen: set[str] = set()
    deduped = []
    for h in hits:
        if h not in seen:
            seen.add(h)
            deduped.append(h)
    return Finding(
        ap=ap,
        name=meta["name"],
        severity=meta["severity"],
        session_ids=deduped[:50],
        evidence=evidence,
        fix=meta["fix"],
    )


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def render_text(findings: list[Finding], stats: dict, format_json: bool = False) -> str:
    if format_json:
        return json.dumps(
            {"stats": stats, "findings": [f.to_dict() for f in findings]},
            ensure_ascii=False,
            indent=2,
        )
    lines = []
    lines.append("Agent runtime diagnosis")
    lines.append("=" * 40)
    lines.append(f"Sessions analyzed: {stats.get('sessions', 0)}")
    lines.append(f"Turns analyzed: {stats.get('turns', 0)}")
    lines.append(f"Final-reason distribution: {stats.get('reasons', {})}")
    lines.append("")
    if not findings:
        lines.append("No anti-patterns detected. Re-run on a larger window or with --metrics for cost spike detection.")
        return "\n".join(lines)
    for f in findings:
        lines.append(f"[{f.ap} · {f.severity.upper()}] {f.name}")
        lines.append(f"  Affected sessions: {len(f.session_ids)} (first: {f.session_ids[:3]})")
        for e in f.evidence:
            lines.append(f"  - {e}")
        lines.append(f"  Fix: {f.fix}")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    p = argparse.ArgumentParser(description="Diagnose an agent at runtime via rollouts")
    p.add_argument("rollouts", help="path to rollouts directory (one .jsonl per session)")
    p.add_argument("--session", default=None, help="filter to a single session id substring")
    p.add_argument("--metrics", default=None, help="path to metrics.jsonl (enables AP-2)")
    p.add_argument("--agent-src", default=None, help="path to agent source dir (enables AP-8 static cross-check)")
    p.add_argument("--allow-empty", action="store_true", help="return success with an empty report when no rollout sessions exist")
    p.add_argument("--format", choices=["text", "json"], default="text")
    args = p.parse_args()

    rollouts_dir = Path(args.rollouts).expanduser().resolve()
    metrics = load_metrics(Path(args.metrics).expanduser().resolve()) if args.metrics else []
    agent_src = Path(args.agent_src).expanduser().resolve() if args.agent_src else None

    empty_stats = {"sessions": 0, "turns": 0, "reasons": {}}
    if not rollouts_dir.exists() and args.allow_empty:
        print(render_text([], empty_stats, format_json=(args.format == "json")))
        return 0

    sessions = load_sessions(rollouts_dir, args.session)
    if not sessions:
        if args.allow_empty:
            print(render_text([], empty_stats, format_json=(args.format == "json")))
            return 0
        print(f"No sessions loaded from {rollouts_dir}", file=sys.stderr)
        return 2

    detectors = [
        detect_tool_loop(sessions),
        detect_cache_spike(sessions, metrics),
        detect_verifier_silent(sessions),
        detect_no_external_wrap(sessions),
        detect_memory_thrash(sessions),
        detect_sandbox_denial(sessions),
        detect_transition_reason_anomaly(sessions),
        detect_subprocess_outside_sandbox(agent_src),
        detect_task_progress_stale(sessions),
    ]
    findings = [f for f in detectors if f is not None]

    stats = {
        "sessions": len(sessions),
        "turns": sum(len(s.turns) for s in sessions),
        "reasons": dict(collections.Counter(s.final_reason() for s in sessions)),
    }

    print(render_text(findings, stats, format_json=(args.format == "json")))
    return 0 if not findings else 1


if __name__ == "__main__":
    sys.exit(main())
