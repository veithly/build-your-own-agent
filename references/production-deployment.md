# Production deployment · operating an agent in the wild

Once the scaffold works locally, production needs more. This reference covers what to add and in what order.

## Table of contents

- Deployment shape (CLI / containerized / always-on / edge)
- Phase 0 · pre-production checklist
- Phase 1 · observability (chapter 15 patterns)
- Phase 2 · rate limit + cost cap
- Phase 3 · session lifecycle (chapter 11)
- Phase 4 · cron / background tasks (chapter 18)
- Phase 5 · supply chain hardening
- Phase 6 · multi-tenancy concerns
- Phase 7 · upgrade / rollback
- Anti-patterns in production
- Reading order for production teams

## Deployment shape · pick one

| Shape | When to pick | Required components |
|-------|--------------|---------------------|
| Local CLI (single user) | dev tools, personal agents | scaffold + sandbox + memory file |
| Per-user containerized | SaaS / multi-tenant | scaffold + container sandbox + per-user volume + rate limit |
| Long-running server (always-on) | scheduled tasks, daemons | scaffold + supervisor + cron + isolated agent per job |
| Edge / browser extension | inline IDE agent | minimal scaffold + IPC + no skill marketplace |

## Phase 0 · pre-production checklist

Before any deploy, every box must be checked:

- [ ] Lint script passes (`python scripts/lint-agent-design.py .`)
- [ ] All 5 security layers implemented (see security-checklist.md)
- [ ] Rollout JSONL writes work + can be replayed (`load_rollout()` round-trips)
- [ ] At least one hard verifier wired (test exit code OR a real external signal)
- [ ] Soft verifier with TOKEN_BUDGET wired with sensible default
- [ ] Task progress persists in rollout and enforces at most one `in_progress` item
- [ ] Sandbox tested on target OS (deny-default network + restricted fs_write verified by attempting both)
- [ ] Redact tested: log an API key, confirm it's `[REDACTED_SECRET]` in output
- [ ] Memory file format is forward-compatible (versioned, or simple enough that bumps are trivial)
- [ ] Cost monitoring: `cost_per_turn` tracked, threshold alerts wired

## Phase 1 · observability (chapter 15 patterns)

Without observability you have no production. Required signals:

1. **Per-turn metrics**: tokens (in/out), latency, transition_reason, tool_count, tool_errors, progress_update_age
2. **Per-session aggregates**: total cost, total turns, ended-with state (verified / give-up / max-turn)
3. **Tool loop detection**: same tool called > 3 times with same args in 5 turns → emit warning
4. **Error rates**: sandbox failures / verifier failures / API errors broken out separately
5. **Progress health**: sessions with no progress updates, stale progress > 10 turns, or multiple `in_progress` items

Minimum implementation:

```python
# observability/metrics.py
import time, json
from pathlib import Path

METRICS_FILE = Path("~/.my-agent/metrics.jsonl").expanduser()

def emit(event: str, **fields):
    METRICS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with METRICS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": time.time(), "event": event, **fields}, ensure_ascii=False) + "\n")
```

Wire emit() at: turn start, turn end, progress update, tool start, tool error, sandbox denial, verifier result.

Periodic aggregation (cron daily):
- Top 10 most expensive sessions
- p50/p95 latency by tool
- Error rate by tool
- Tool loop detection report
- Stale task-progress sessions

## Phase 2 · rate limit + cost cap

LLMs are billed per token; an agent that loops can cost hundreds of dollars per session if unchecked.

Required limits:

| Limit | Default | Source pattern |
|-------|---------|----------------|
| max_turns_per_session | 50 | Hermes iteration_budget |
| max_tokens_per_session | 200,000 | Claude Code TOKEN_BUDGET |
| max_cost_per_session_usd | 5.00 | track tokens × price |
| max_concurrent_sessions_per_user | 3 | session lane / queue |
| max_tool_calls_per_turn | 10 | OpenClaw safety-timeout |
| max_subagent_depth | 2 | prevent infinite spawn |

Hard caps trigger a clean shutdown, write a final rollout event "BUDGET_EXCEEDED", and report to the user.

## Phase 3 · session lifecycle (chapter 11)

For long-running services, sessions need explicit state:

```python
# core/session.py
from enum import Enum
class SessionState(str, Enum):
    INIT = "init"
    RUNNING = "running"
    INTERRUPTED = "interrupted"  # user pressed Ctrl-C
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"  # idle timeout
```

Required transitions: `init → running → (completed | failed | interrupted | expired)`. Each transition writes to rollout.

Resume support: `resume_session(session_id)` reads the JSONL rollout, reconstructs `turns`, frozen memory snapshot, latest unfinished `task_progress`, and continues from the last incomplete turn.

## Phase 4 · cron / background tasks (chapter 18)

If your agent supports scheduled tasks:

1. Use a scheduler lock (file lock or DB row lock) so two scheduler instances don't fire the same job
2. Each cron job runs as an **isolated agent** with its own session_id, sandbox, and memory snapshot
3. Cron job output gets written to its own rollout — never merged into a user's interactive session
4. Failed cron jobs auto-disable after N consecutive failures (3) — manual re-enable required
5. Cron threat patterns scanned: `_CRON_THREAT_PATTERNS` (10 rules from Hermes) before persisting any schedule

## Phase 5 · supply chain hardening

For production:

- [ ] Pin all skill versions to commit SHA (no `latest` tags)
- [ ] If supporting user-installable skills: scanner runs on every install
- [ ] If supporting binary tools: SHA-256 verification + optional cosign provenance
- [ ] CI/CD pipeline signs releases (cosign + OIDC)
- [ ] Dependency vulnerability scan (npm audit / pip-audit) on every build

## Phase 6 · multi-tenancy concerns

If multiple users share the agent server:

- [ ] Each user gets a separate memory file (don't share!)
- [ ] Each user gets a separate rollout dir
- [ ] Sandboxes are per-session (no cross-user fs access)
- [ ] Rate limits are per-user, not global
- [ ] Cost tracking is per-user (separate ledger)
- [ ] If skill marketplace exists: user-installed skills are user-scoped only

## Phase 7 · upgrade / rollback

Agents are stateful (memory, skills, rollouts). Upgrade carefully:

1. **Versioned memory format**: include `schema_version` in memory files; migrate on read
2. **Versioned rollout format**: same idea
3. **Skill compatibility window**: declare which agent versions a skill supports
4. **Graceful drain on upgrade**: scheduler stops new jobs; running jobs complete; then upgrade
5. **Rollback plan**: keep previous binary + previous memory backup for 7 days

## Anti-patterns in production

- ❌ Run agent as root / Administrator (sandbox escape becomes RCE)
- ❌ Log raw LLM I/O without redact (instant leak)
- ❌ Share memory across users (data leak + prompt cross-contamination)
- ❌ No cost cap (one buggy session can rack up $1000 in an hour)
- ❌ Todo state only in final-answer prose (resume, UI, and compaction can't consume it)
- ❌ Trust user-provided skill paths without scanner (full takeover)
- ❌ Run sandbox-less in "trusted" environments (the env stops being trusted)
- ❌ Ignore tool loop signals (your bill goes up, your agent's effectiveness goes down)

## Reading order for production teams

If your team is going from scaffold to production, read in this order:

1. Chapter 15 — observability and cost (build dashboards first)
2. Chapter 11 — session lifecycle (so sessions can be resumed/cleaned)
3. Chapter 13 — sandbox (so you can sleep at night)
4. Chapter 20 — security (the 5-layer defense)
5. Chapter 12 — permissions (AskForApproval / approval mode)
6. Chapter 18 — cron (if you have background tasks)
7. Chapter 21 — todo list / task progress (for long interactive work)
8. Chapter 22 — execution-state surfaces (for tool progress, subagent progress, terminal status, away summary, or operator-visible work)
8. Chapter 17 — skills (if you support user-installable)

Each chapter has a §11 interview drill that will surface gotchas your team hasn't considered.
