# Agent scaffold · canonical generated project map

The generated Python scaffold is sourced from `assets/scaffold/`. Do not copy
large code blocks into this reference; that creates drift. Edit the files under
`assets/scaffold/`, then verify with `scripts/init-agent-project.py`.

## Golden path

```bash
python /path/to/build-your-own-agent/scripts/init-agent-project.py ./my-agent \
  --profile coding-cli \
  --test-cmd "python -m pytest -ra"
cd ./my-agent
python scripts/lint-agent-design.py .
python -m pytest -ra
python scripts/diagnose-agent.py ~/.$(basename "$PWD")/rollouts/ --allow-empty
```

## Generated layout

| Path | Purpose | Rule / axis |
|------|---------|-------------|
| `AGENTS.md` | architecture contract: 8 axes, tool catalog, verifier, out-of-scope | Phase 1 |
| `.gitignore` | keeps rollouts, audit, metrics, memory, env files, caches out of git | repo hygiene |
| `.github/workflows/agent-lint-and-diagnose.yml` | CI lint/test/diagnose skeleton | Phase 4/5 |
| `core/loop.py` | turn loop; one LLM call per turn; writes final transition before rollout append | R1, R4 |
| `core/prompt.py` | layered prompt; explicit `CACHE_BOUNDARY_LAYER`; timestamp/progress/transcript below boundary | R2, R8 |
| `core/tools.py` | registry, permission gate, parallel dispatch, audit on denies/errors | R5, R10 |
| `core/verifier.py` | `verify_hard`, `verify_soft`, `verify_giveup` | R4 |
| `core/sandbox.py` | seatbelt/bwrap wrapper; process-only fallback denied by default | R5 |
| `memory/snapshot.py` | freezes memory into a string once per run loop | R8 |
| `memory/store.py` | append-only JSONL memory; scanner before write; audit on write/reject | R7, R8, R10 |
| `security/scanner.py` | fail-open scanner for persistent text: invisible chars, injection, shell payloads, large base64 | R7 |
| `security/audit.py` | append-only audit JSONL for safety-relevant events | R10 |
| `security/redact.py` | import-time redaction toggle; audit on redaction hits | R6, R10 |
| `security/external.py` | nonce-wrapped external content | R3 |
| `observability/metrics.py` | append-only metrics JSONL for diagnose cost/latency analysis | Phase 5 |
| `progress/todo.py` | execution todo surface with statuses and single `in_progress` guard | Axis 8 |
| `skills/registry.py` | bundled-skill allowlist only | R9 |
| `rollout/writer.py` | one JSONL per session; emits turn metrics | R10 |
| `tests/test_smoke.py` | generated regression tests for lint, cache, scanner, audit, rollout, metrics, progress, sandbox | Phase 4 |

## Phase gates

Run these before adapting provider or domain tools:

```bash
python scripts/lint-agent-design.py .
python -m pytest -ra
python scripts/diagnose-agent.py ~/.my-agent/rollouts/ --allow-empty --format json
```

Expected on a fresh Windows checkout:

- lint: `10/10 rules passing` plus `P1 Task progress surface` pass
- tests: all generated tests pass except real OS sandbox escape may skip on Windows
- diagnose: empty JSON report is valid when `--allow-empty` is used

## Adaptation order

1. Fill `AGENTS.md` with the actual domain and axis choices.
2. Replace `cli.py::fake_llm` with a provider adapter.
3. Set a narrow `AGENT_TEST_CMD`; do not run full test suites every turn unless the repo is tiny.
4. Add tools through `core/tools.py`; every shell-class tool must route through `sandbox_exec`.
5. Add bundled skills under `skills/bundled/`; user-installable skills require a scanner before production.
6. Extend `security/scanner.py` with domain-specific persistence threats.
7. Extend `observability/metrics.py` only by appending fields, not changing existing JSON keys.

## Do not drift

- Do not paste scaffold source back into this reference. The code source is `assets/scaffold/`.
- Do not edit generated files in a temp project and forget to port the change back to `assets/scaffold/`.
- After any scaffold change, run an init smoke:

```bash
python scripts/init-agent-project.py /tmp/agent-smoke --profile coding-cli --test-cmd "python -m pytest -ra"
cd /tmp/agent-smoke
python -m pytest -ra
```
