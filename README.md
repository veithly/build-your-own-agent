# build-your-own-agent

`build-your-own-agent` is a source-grounded skill for designing, building, and diagnosing agent harnesses. It distills the engineering patterns from Codex, Claude Code, OpenClaw, and Hermes into a loadable skill plus scripts and references.

Public book site: <https://veithly.github.io>

## What It Covers

- Agent loop, turn boundaries, rollout, and recovery
- Context layout and cache boundaries
- Tool dispatch, permissions, file editing, shell execution, and sandboxing
- Hard / soft / give-up verifiers
- Memory, skills, cron, self-improvement, and security
- Todo/task progress surfaces and execution-state routing
- Production deployment and diagnosis workflows

## Install

### Claude Code

```bash
mkdir -p ~/.claude/skills
git clone https://github.com/veithly/build-your-own-agent.git ~/.claude/skills/build-your-own-agent
```

Restart Claude Code and load the skill when designing or auditing an agent.

### Project-local install

```bash
mkdir -p ./skills
git clone https://github.com/veithly/build-your-own-agent.git ./skills/build-your-own-agent
```

Then reference it from your repo instructions:

```md
When designing an agent harness, load ./skills/build-your-own-agent/SKILL.md.
```

## Quick Start

Create a Python agent scaffold:

```bash
python ~/.claude/skills/build-your-own-agent/scripts/init-agent-project.py ./my-agent \
  --profile coding-cli \
  --provider OpenAI \
  --test-cmd "python -m pytest -ra"
```

Audit an existing agent:

```bash
python ~/.claude/skills/build-your-own-agent/scripts/lint-agent-design.py /path/to/agent
python ~/.claude/skills/build-your-own-agent/scripts/diagnose-agent.py /path/to/rollouts --allow-empty
```

## Repository Layout

```text
SKILL.md                 # entry point and trigger map
references/              # build, diagnose, security, deployment, migration, interview prep
scripts/                 # init, lint, runtime diagnosis
assets/                  # templates and generated scaffold source
```

## Validation

```bash
python scripts/init-agent-project.py tmp-smoke-agent --profile coding-cli --test-cmd "python -m pytest -ra"
python tmp-smoke-agent/scripts/lint-agent-design.py tmp-smoke-agent
mkdir -p tmp-empty-rollouts
python scripts/diagnose-agent.py tmp-empty-rollouts --allow-empty
```

## License

MIT. See [LICENSE.txt](./LICENSE.txt).
