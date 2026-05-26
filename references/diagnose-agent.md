# Diagnose & optimize agent · 4 flows + anti-pattern map

The "my agent already exists, what's wrong with it" path. Four diagnostic flows catch common production failures and map each one to a source-backed fix from the four reference systems.

## Table of contents

- When to use which flow
- Flow A · Static lint (2 minutes)
- Flow B · Runtime diagnosis (10-30 minutes)
- Flow C · Security audit (1-2 hours)
- Flow D · Cost / latency / quality (2-4 hours)
- Symptom → root-cause → source-backed fix map
- Triage matrix: priority × effort
- After-fix verification

## When to use which flow

| Symptom from user / monitoring | Start with |
|---------------------------------|-------------|
| "I just inherited this agent and don't know if it's safe" | A → C → B → D |
| "Cost went up 5× last week" | B → D |
| "Users report wrong / off-topic answers" | A (check verifier, memory snapshot) → B (transition_reason distribution) |
| "Latency p95 doubled" | D → B |
| "We had a security incident" | C immediately, then A to find structural causes |
| "Agent works in dev but fails in prod" | A → B (compare dev rollouts vs prod rollouts) |
| "We want to refactor toward 10 Iron Laws" | A → then `references/migration-guide.md` |

Run all four monthly even if nothing is on fire — the agents that don't get diagnosed are the ones that explode.

---

## Flow A · Static lint (2 minutes)

The cheapest, fastest, highest-signal step. Always run first.

### Command

```bash
python ~/.claude/skills/build-your-own-agent/scripts/lint-agent-design.py /path/to/agent
# or JSON for CI:
python ~/.claude/skills/build-your-own-agent/scripts/lint-agent-design.py /path/to/agent --format json
```

### What it checks

10 Iron Laws (static):

1. Turn dataclass + rollout writer exist.
2. `CACHE_BOUNDARY_LAYER` constant exists in prompt assembly.
3. External content wrap with `secrets.token_hex` nonce.
4. Three verifier functions: `verify_hard` + `verify_soft` + `verify_giveup`.
5. Shell-class tools route through `sandbox_exec`.
6. `_REDACT_ENABLED` snapshotted at module top of `security/redact.py`.
7. Scanner / verifier wrapped in try/except returning a value (fail_open).
8. `freeze_memory()` called once at loop start.
9. `skills/bundled/` allowlist directory + `list_bundled_skill_names()`.
10. `rollout/writer.py` produces `.jsonl`.

### What each failure means + source-backed fix

| Rule | Failure means | Source-backed fix |
|------|---------------|---------------------|
| R1 (turn) | Loop doesn't have explicit turn boundaries. State changes happen at random times. | Copy Codex `codex_thread.rs` turn structure. See `agent-scaffold.md` File 1. |
| R2 (cache) | Every turn pays full API price even when prefix is stable. | Insert `CACHE_BOUNDARY_LAYER` in `core/prompt.py`. Verify with cache-stability test (see `build-agent-workflow.md` Phase 4 Test 2). |
| R3 (external wrap) | Web-fetched content / tool output is concatenated into prompt as instructions. Injection risk. | Copy OpenClaw `external-content.ts`. Apply at every external-content entry point. |
| R4 (3 verifier tiers) | Agent stops too early or runs forever. | Add the missing tier. Most common: missing soft (TOKEN_BUDGET) or missing hard (test exit code). Pattern in `agent-scaffold.md` File 4. |
| R5 (sandbox) | Shell tool runs `subprocess.run` directly. RCE risk on injection. | Replace with `sandbox_exec`. Pattern in `agent-scaffold.md` File 5. Pick OS implementation matching deploy target. |
| R6 (redact import) | `if config.redact:` checked at log time. LLM can disable mid-turn. | Move to module top: `_REDACT_ENABLED = os.getenv(...)` at line 1-10 of `security/redact.py`. |
| R7 (fail_open) | Scanner crash crashes the agent. Users will disable safety wholesale. | Wrap scanner call in try/except, return "allow" on exception, log warning. |
| R8 (frozen memory) | Mid-turn memory writes affect the prompt → cache invalidation + nondeterminism. | Add `freeze_memory()` call at top of `run_loop`. Pass `memory_frozen` string through to `assemble_prompt`. |
| R9 (bundled allowlist) | Skills load from arbitrary file paths. Supply chain risk. | Move skills into `skills/bundled/`. Remove `skill_path` CLI args. For user-installable: add a scanner (OpenClaw + Hermes pattern). |
| R10 (audit) | No rollout writer. Production issues are uninvestigable. | Add `rollout/writer.py`. Wire `rollout.write(turn)` at every turn end. |

### Acting on lint output

A lint failure is structural, not stylistic. Fix it; don't suppress it. If you genuinely don't need a rule (e.g. R3 because your agent has no external content at all), document the deviation in your project's `AGENTS.md` under "Deviations from 10 Iron Laws".

---

## Flow B · Runtime diagnosis (10-30 minutes)

The agent runs fine in tests but does weird things in production. The rollout JSONL holds the answer.

### Command

```bash
python ~/.claude/skills/build-your-own-agent/scripts/diagnose-agent.py /path/to/rollouts/ --allow-empty
# Optional: focus on a single session
python ~/.claude/skills/build-your-own-agent/scripts/diagnose-agent.py /path/to/rollouts/ --session=abc12345
# Optional: JSON output
python ~/.claude/skills/build-your-own-agent/scripts/diagnose-agent.py /path/to/rollouts/ --format json
```

### The 9 runtime anti-patterns

The script reads all rollout JSONLs in the directory and flags these. Each finding has a symptom signature, a typical cause, and a source-backed fix.

#### AP-1 · Tool loop

**Symptom**: same tool called > 3 times with the same args within 5 turns.

**Cause**: model has no fresh info to act on; verifier doesn't recognize the loop.

**Best fix**:
- Add a "diminishing returns" branch in `verify_soft`: if last 3 turns each added < 500 tokens, stop. (Claude Code pattern, see `agent-scaffold.md` File 4.)
- Inject a "this tool was just called with these args; results were: ..." reminder into the next turn's user message. Force the model to either change args or move on.

**Source pointer**: Claude Code TOKEN_BUDGET diminishing-returns logic (book §5).

#### AP-2 · Cache miss / cost spike

**Symptom**: per-turn token-in count grows with session length, even when transcript is short.

**Cause**: timestamp, memory snapshot, or skill index is positioned BELOW the cache boundary, so prefix changes every turn.

**Best fix**:
- Re-read `core/prompt.py`. Verify `CACHE_BOUNDARY_LAYER` is set such that ONLY transcript and per-turn ephemeral state are below it.
- Run the cache-stability test (`build-agent-workflow.md` Phase 4 Test 2).
- Provider-side: check the API response for `cache_creation_input_tokens` vs `cache_read_input_tokens`. If you never see `cache_read`, your boundary is in the wrong place.

**Source pointer**: Codex `core/src/context_manager/` for the static template; Claude Code 5-tier priority logic.

#### AP-3 · Verifier silent failure

**Symptom**: agent loops to `max_turns` without `transition_reason == 'verified'`. `verify_hard` always returns True (or always returns False).

**Cause**:
- True always: no test command configured (`AGENT_TEST_CMD` env var empty), so `verify_hard` defaults to "no signal → pass".
- False always: test command points at the wrong path / has unmet dependencies.

**Best fix**:
- For coding agent: wire `AGENT_TEST_CMD="pytest -x"` or your project's lint+test command. The exit code IS the verdict.
- For non-coding agent: define a domain-specific check. Examples: ticket validator (returns 0 if ticket fields valid), API contract validator, schema-conformance checker.
- Log `verify_hard` invocations with their result. Silent verifiers are useless.

**Source pointer**: Codex `goals.rs` + `apply_patch_tests.rs` — verifier-as-process pattern.

#### AP-4 · No external-content wrap

**Symptom**: tool result of a web-fetch / file-read tool contains text that looks instructional. Agent follows it.

**Cause**: that tool's result path doesn't go through `wrap_external_content`.

**Best fix**:
- Grep for `tool_result` construction. Each path that builds one with external content MUST call `wrap_external_content(...)`.
- Add a unit test per external-content tool: feed `IGNORE PREVIOUS...` as the tool result, assert the model treats it as data.

**Source pointer**: OpenClaw `external-content.ts`.

#### AP-5 · Memory thrash

**Symptom**: memory file grows fast (> 100 entries / day). Or: memory consolidation Phase 2 never runs.

**Cause**:
- Too-loose write criteria. The agent decides everything is worth remembering.
- For Codex 2-phase: Phase 2 cooldown is too long (6h default) for high-throughput agents.

**Best fix**:
- Tighten the write criteria in your `memory_tool`. Hermes uses a 4-round AskUserQuestion gate before writing.
- For 2-phase: lower the cooldown to 1h, or trigger Phase 2 manually on memory-file-size > N.
- Add temporal decay (OpenClaw `halfLifeDays=30`) so stale memory naturally falls off search.

**Source pointer**: Hermes `memory_tool.py` write gates; OpenClaw temporal decay.

#### AP-6 · Sandbox bypass attempt

**Symptom**: `sandbox_exec` calls with `exit_code != 0` and an error string mentioning `sandbox-exec`, `bwrap`, `EPERM`, or `Operation not permitted`.

**Cause**:
- Could be benign (tool legitimately needs network or fs_write to a non-project path).
- Could be malicious (injection-induced exfiltration attempt).

**Best fix**:
- Audit the calls. Categorize:
  - Legitimate need → add to allowlist with explicit justification in `AGENTS.md`.
  - Suspicious → log + alert + investigate.
- Add a "sandbox denial rate" metric to your observability dashboard. Spikes correlate with injection attacks.

**Source pointer**: Codex `execpolicy` for the allowlist pattern.

#### AP-7 · Transition reason missing or always one value

**Symptom**: most turns have `transition_reason == None` OR all sessions end with the same reason (e.g. always `model_done`).

**Cause**:
- `None`: forgot to set `turn.transition_reason` before break.
- Always same value: one of the verifier tiers never fires.

**Best fix**:
- Add `assert turn.transition_reason != "start"` before `rollout.write(turn)` at loop end.
- Run a 100-session sample and aggregate by `transition_reason`. A healthy agent has at least 3 distinct values appearing, in rough proportion: `verified` 40-60%, `model_done` 30-40%, `no_more_tools` 5-10%, `budget_exceeded` 1-3%.

**Source pointer**: Claude Code 7-transition tag pattern (book §11 session-lifecycle).

#### AP-8 · Subprocess.run outside sandbox

**Symptom**: `diagnose-agent.py` static cross-check finds `subprocess.run(` in a tool implementation file without nearby `sandbox_exec`.

**Cause**: someone added a tool quickly during a hot-fix and bypassed the sandbox.

**Best fix**:
- Replace the `subprocess.run(...)` with `sandbox_exec(...)`.
- Add a unit test that runs the tool with a `rm -rf $HOME/test_escape` command. Must fail.
- Optional: add a pre-commit hook that greps for `subprocess.run` outside `core/sandbox.py` and fails the commit.

**Source pointer**: Codex sandbox pattern.

#### AP-9 · Task progress stale or malformed

**Symptom**: a long, tool-active session has no structured progress updates; the last update is 10+ turns stale; or a rollout contains multiple top-level `in_progress` items.

**Cause**:
- No todo/progress surface exists, so all task state lives in prose.
- The todo writer only appends and never replaces/merges correctly.
- Parallel work was represented as multiple active top-level tasks instead of one active task with parallel tool calls underneath.

**Best fix**:
- Add `progress/todo.py` from `agent-scaffold.md` File 12 or an equivalent `update_task_progress` tool.
- Enforce at most one `in_progress` item.
- Persist `task_progress` into rollout records and inject only `pending` / `in_progress` items after resume or compaction.
- Keep approval plans, execution todos, and durable background tasks separate.

**Source pointer**: book §21 todo-list and §22 execution-state surfaces; Codex `update_plan`; Claude Code `TodoWrite`; Hermes `todo_tool.py`.

### Best practices reading the rollouts

- **Read the worst sessions first**. Top 10 most expensive sessions / longest sessions / most tool-error sessions. Bugs cluster at extremes, not averages.
- **Compare staging vs production**. Same agent, different `transition_reason` distribution = production has a class of inputs staging didn't.
- **Look at the second-to-last turn**, not the last. The last turn is the agent giving up; the second-to-last shows what it tried.
- **One rollout JSONL per session** = grep-friendly. `rg 'transition_reason.*budget_exceeded' /path/to/rollouts/` finds every budget-exceeded session in O(disk).

---

## Flow C · Security audit (1-2 hours)

Walk every box in `references/security-checklist.md` by hand. For each box, run a concrete test that proves the layer works.

### Quick scoring

After the audit, score yourself out of 25 (5 layers × 5 questions):

| Layer | 5 questions |
|-------|-------------|
| 1. Supply chain | bundled? scanner? sha256? signed? lockfile? |
| 2. Input boundary | wrap on web? wrap on tool? wrap on user paste? nonce? "data not instructions" string? |
| 3. Runtime | sandbox default-deny? approval gate? per-OS impl? subprocess for verify? deny list for remote? |
| 4. Persistence | threat scan? invisible-unicode scan? length cap? preview before save? trust × verdict matrix? |
| 5. Egress | redact at import? full vendor prefix list? env-var heuristic? bounded redact? config redact? |

Below 20 = not production-ready. Below 15 = security incident is months away, not years.

### Best references per layer

(Already covered in `security-checklist.md`; this section is a cross-pointer for the diagnose flow.)

| Layer | If missing, fix with |
|-------|-----------------------|
| 1 | Codex `core-skills/` + Hermes binary verification |
| 2 | OpenClaw `external-content.ts` (random nonce) |
| 3 | Codex 3-OS sandbox + execpolicy |
| 4 | Hermes `_MEMORY_THREAT_PATTERNS` + `_INVISIBLE_CHARS` |
| 5 | Hermes `redact.py` + OpenClaw `redact-bounded.ts` |

### Common audit findings

- **"We have a redactor but it doesn't redact env vars by name"**: extend Hermes pattern with heuristic `re.search(r'(KEY|TOKEN|SECRET|PASSWORD)=\S+', text)`.
- **"We wrap tool output but not user-pasted text"**: extend `wrap_external_content` to apply on any message-role content longer than 1KB.
- **"Sandbox exists but tests don't cover it"**: write 5 concrete tests — `rm`, `curl`, `cat /etc/shadow`, `ssh`, `python -c "..."`. Each must fail.
- **"We pinned skill versions but the scanner is disabled"**: pinned + scanner are AND, not OR. Both required.

---

## Flow D · Cost / latency / quality (2-4 hours)

When the lint passes, the rollouts look healthy, and security checks out, but something still feels off.

### Required data

- 7 days of `rollouts/*.jsonl`
- 7 days of `metrics.jsonl` (per-turn metrics from `observability/metrics.py`)
- Optional: provider API console (for cache hit telemetry)

### Step 1 · Per-tool latency

Aggregate by tool name:

```python
import json
from collections import defaultdict
import statistics

durations = defaultdict(list)
for line in open("metrics.jsonl"):
    e = json.loads(line)
    if e.get("event") == "tool_end":
        durations[e["tool"]].append(e["duration_ms"])

for tool, ds in durations.items():
    print(f"{tool}: n={len(ds)} p50={statistics.median(ds):.0f} p95={sorted(ds)[int(len(ds)*0.95)]:.0f}")
```

What good looks like:
- p50 < 500ms for most tools
- p95 < 5000ms
- No tool has p95 > 30000ms (timeout territory)

What bad looks like + fix:
- `shell.exec` p95 > 10s → either real tasks are slow (legit) or the sandbox setup has overhead (fix: cache sandbox profile generation).
- `web_fetch` p95 > 20s → no per-request timeout. Add `timeout=10` to all HTTP clients.
- A tool dominating total time → consider parallelizing if safe (Claude Code dispatch pattern).

### Step 2 · Per-session cost

```python
session_cost = defaultdict(float)
PRICE_IN = 3e-6   # $ per input token (Anthropic claude-3.5-sonnet 2024 baseline)
PRICE_OUT = 15e-6
for line in open("metrics.jsonl"):
    e = json.loads(line)
    if e.get("event") == "turn_end":
        session_cost[e["session_id"]] += e.get("tokens_in",0)*PRICE_IN + e.get("tokens_out",0)*PRICE_OUT

top = sorted(session_cost.items(), key=lambda x: -x[1])[:10]
for sid, c in top:
    print(f"{sid}: ${c:.2f}")
```

If top 10 sessions are > $1 each, audit them. The script's AP-1 (tool loop) and AP-2 (cache miss) often live there.

### Step 3 · Verifier outcome distribution

```python
from collections import Counter
counts = Counter()
for f in rollouts_glob:
    last = list(open(f))[-1]
    rec = json.loads(last)
    counts[rec.get("transition_reason","unknown")] += 1

print(counts)
```

Healthy distribution (rough):
- `verified`: 40-60%
- `model_done`: 30-40%
- `no_more_tools`: 5-10%
- `budget_exceeded` / `interrupted`: 1-3% each

Skew patterns + fix:
- `verified` < 20% → your hard verifier isn't catching real completions. Tune the signal (lower test selectivity, add domain checks).
- `model_done` > 70% → your hard verifier is too strict; agent stops by give-up before verification kicks in.
- `budget_exceeded` > 5% → either real work needs more budget or there's a tool loop (run Flow B).

### Step 4 · Per-tool error rates

```python
errors = defaultdict(int)
calls = defaultdict(int)
for line in open("metrics.jsonl"):
    e = json.loads(line)
    if e.get("event") == "tool_end":
        calls[e["tool"]] += 1
        if e.get("error"):
            errors[e["tool"]] += 1
for tool in calls:
    rate = errors.get(tool,0) / calls[tool]
    print(f"{tool}: {rate:.1%} ({errors.get(tool,0)}/{calls[tool]})")
```

Per-tool error budget:
- > 20% → broken or misnamed; the LLM doesn't understand when to use it. Rewrite tool description, simplify signature.
- 5-20% → improve error messages so the LLM can recover.
- < 5% → healthy; errors are correctable mistakes.

### Step 5 · Tail outliers

For each metric (latency, cost, turn count, tool count), look at the 95th and 99th percentile sessions. They're almost always bugs. Either:
- The agent went into a tool loop (Flow B AP-1)
- Some specific input class triggers fallback behavior worth a code path
- The verifier silently failed (Flow B AP-3)

Add unit tests for any pathological input you find. Bugs that don't have tests come back.

### Best references for cost/quality work

- Codex `analytics/`, `otel/`, `rollout-trace/` — production-grade observability layer.
- OpenClaw `logging/` + `redact-bounded.ts` — log without leaking.
- Hermes `agent/usage_pricing.py` + `rate_limit_tracker.py` — per-provider pricing tables + budget tracker.

---

## Symptom → root-cause → source-backed fix map

A single table indexed by what the user reports.

| Symptom | Most likely root cause | First check | Best fix | Source |
|---------|------------------------|--------------|----------|--------|
| "Agent loops forever" | Verifier give-up alone; no soft / hard tier | Flow A R4 + Flow B AP-1 | Add `verify_soft` with TOKEN_BUDGET + diminishing returns | Claude Code |
| "Cost shot up 5×" | Cache boundary misplaced | Flow B AP-2; check provider cache telemetry | Move timestamp + ephemeral state below `CACHE_BOUNDARY_LAYER` | Codex / Claude Code |
| "Agent does what an external URL says" | No external-content wrap | Flow A R3 + Flow B AP-4 | `wrap_external_content` at every external entry point | OpenClaw |
| "Tool ran `rm` and deleted things" | No sandbox | Flow A R5 + Flow B AP-8 | Wire `sandbox_exec` for shell-class tools | Codex |
| "API key leaked into logs" | Redact toggled off mid-run | Flow A R6 + Flow C Layer 5 | Module-import snapshot of `_REDACT_ENABLED` | Hermes |
| "Memory grew 10MB / day" | Loose write criteria + no decay | Flow B AP-5 | Tighten write gate + add temporal decay | Hermes + OpenClaw |
| "Sessions don't resume after crash" | No rollout writer or wrong format | Flow A R10 + Flow B (try resume) | Wire `RolloutWriter`; round-trip test | Codex |
| "Agent works in dev, breaks in prod" | Memory or skill differences | Flow B; compare rollouts | Pin memory format version; reseed prod from dev fixture | various |
| "Users get cross-contaminated answers" | Shared memory file in multi-tenant | Flow C Layer 4; check file paths | Per-user memory file; per-user rollout dir | OpenClaw multi-channel |
| "Verifier passes but answer is wrong" | Hard verifier weak; checks structure not semantics | Flow D Step 3 | Add domain-specific check (validator + ground truth) | Codex `goals.rs` |
| "Latency p95 doubled" | Tool timeout missing OR sandbox profile regen each call | Flow D Step 1 | Add `timeout` to HTTP clients; cache sandbox profile | various |
| "Tool dispatcher hangs" | Async / sync mixed; thread pool deadlock | code review | One concurrency model. Either all async or all sync + threads | Claude Code (threads) |
| "Subagent never completes" | No depth limit; infinite spawn | Flow B (count subagent_depth) | Max `subagent_depth=2` + budget per subagent | OpenClaw |
| "Sandbox exit_code is 0 but the action didn't happen" | Profile permits the action but a downstream fs check rejects | shell debug | Standardize: sandbox exit_code is THE verdict. Use post-conditions to verify side-effects | Codex |
| "Cron job double-fires" | No scheduler lock | Flow C Layer 4 | File lock or DB row lock before fire | Hermes cron |
| "Skill marketplace install bricked the agent" | No scanner | Flow A R9 | Add OpenClaw skill-scanner + Hermes INSTALL_POLICY | OpenClaw + Hermes |
| "Same question, different answers each run" | Memory mid-turn mutation | Flow A R8 | `freeze_memory()` at turn start, pass through | Hermes |
| "Audit log is missing" | No `rollout/writer.py` or no `audit.jsonl` | Flow A R10 | Add audit-only JSONL alongside rollout | Codex + OpenClaw |

---

## Triage matrix: priority × effort

When you have multiple findings, fix in this order.

| | Effort: < 1 day | Effort: 1-3 days | Effort: > 3 days |
|--|------------------|-------------------|-------------------|
| **Security risk: HIGH** | Fix immediately (e.g. enable redact, wrap external content) | Fix this sprint (e.g. wire sandbox) | Stop the world; allocate (e.g. add scanner for user-installable skills) |
| **Cost / latency: HIGH** | Fix immediately (e.g. tool timeout) | Fix this sprint (e.g. cache boundary) | Plan + measure (e.g. parallel tool dispatch refactor) |
| **Quality: MEDIUM** | Backlog top (e.g. transition_reason logging) | Next sprint (e.g. tighter verifier) | Roadmap (e.g. memory consolidation) |
| **Cosmetic / style** | Backlog bottom | Skip unless asked | Skip |

Rule of thumb: never let a HIGH-security finding wait for a sprint boundary. Fix or feature-flag it within 24h.

---

## After-fix verification

Every fix needs both static and runtime verification.

### Static: re-run lint

```bash
python scripts/lint-agent-design.py /path/to/agent
```

The previously-failing rule must now pass. If it doesn't, the fix didn't work or wasn't deployed.

### Runtime: re-run diagnosis on fresh rollouts

Generate at least 50 sessions on the fixed code, then:

```bash
python scripts/diagnose-agent.py /path/to/new_rollouts/
```

The previously-flagged anti-pattern must not appear in the new rollouts.

### Regression test

Whatever symptom triggered the diagnosis becomes a permanent test:

```python
# tests/regression/test_<symptom>.py
def test_no_tool_loop_after_fix():
    # Reproduce the input that triggered the loop
    # Run the agent
    # Assert max tool calls per tool < 3
```

### Documentation

Update `AGENTS.md` if the fix changed an architectural decision. Add a one-line entry to a `CHANGELOG.md` under "Diagnosis findings" so the next engineer sees the history.

## What to read next

- If lint failed: `references/migration-guide.md` for the structured 10-stage refactor.
- If specific rule unclear: corresponding chapter in `docs-site/src/content/docs/patterns/`.
- If security found gaps: `references/security-checklist.md` for full layer-by-layer.
- If multiple flows ran and you're picking what to fix first: the triage matrix above.
- If your axis decisions changed: `references/picking-from-spectrum.md` to re-derive.
