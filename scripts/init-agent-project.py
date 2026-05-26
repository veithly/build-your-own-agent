#!/usr/bin/env python3
"""Initialize a best-practice agent harness project."""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from string import Template


SKILL_DIR = Path(__file__).resolve().parents[1]
ASSETS_DIR = SKILL_DIR / "assets"
SCAFFOLD_DIR = ASSETS_DIR / "scaffold"
SCRIPT_DIR = SKILL_DIR / "scripts"


PROFILE_DEFAULTS = {
    "coding-cli": {
        "domain": "coding",
        "deployment": "local-CLI",
        "multi_tenant": "no",
        "user_installable_skills": "no (bundled only)",
        "long_running": "no",
        "loop": "Codex rollout per turn",
        "context": "Claude Code style layered prompt with an explicit cache boundary",
        "tools": "Claude Code parallel dispatch with per-tool permission gates",
        "verifier": "Codex hard + soft + give-up verifier chain",
        "memory": "Hermes frozen snapshot with append-only JSONL store",
        "skills": "Codex bundled allowlist in v1",
        "sandbox": "Codex per-OS sandbox wrapper; process-only fallback denied by default",
        "task_progress": "Codex update_plan-style session checklist; keep approval plans separate",
    },
    "ide-agent": {
        "domain": "IDE",
        "deployment": "local-CLI",
        "multi_tenant": "no",
        "user_installable_skills": "no (bundled only)",
        "long_running": "yes (resume sessions)",
        "loop": "Claude Code 7-transition loop with Codex rollout persistence",
        "context": "Claude Code 5-tier prompt priority",
        "tools": "Claude Code parallel dispatch for independent editor/tool calls",
        "verifier": "Claude Code TOKEN_BUDGET soft stop plus hard test command",
        "memory": "Claude Code user-driven memory with frozen prompt snapshots",
        "skills": "Claude Code admin-managed skills with scanner before execution",
        "sandbox": "Codex sandbox plus canUseTool approval gates",
        "task_progress": "Claude Code TodoWrite-style activeForm; durable task files only for team work",
    },
    "personal-long-runner": {
        "domain": "personal-assistant",
        "deployment": "always-on",
        "multi_tenant": "no",
        "user_installable_skills": "yes (need scanner before production)",
        "long_running": "yes (need resume + cron)",
        "loop": "Hermes iteration budget with Codex-style rollout writes",
        "context": "Hermes 10-layer dynamic context with cache boundary carved out",
        "tools": "serial by default; parallel only for read-only independent tools",
        "verifier": "Hermes spread-across-time plus hard domain validators",
        "memory": "Hermes in-turn explicit memory with frozen prompt snapshots",
        "skills": "OpenClaw + Hermes scanner and trust matrix before user installs",
        "sandbox": "OS sandbox plus deny-by-default network for shell-class tools",
        "task_progress": "Hermes todo store with unfinished-only compaction injection",
    },
}


ROOT_TEMPLATES = {
    ASSETS_DIR / "AGENTS.md.template": "AGENTS.md",
    ASSETS_DIR / "README.md.template": "README.md",
    ASSETS_DIR / "pyproject.toml.template": "pyproject.toml",
    ASSETS_DIR / ".gitignore.template": ".gitignore",
}


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "my-agent"


def build_context(args: argparse.Namespace, target: Path) -> dict[str, str]:
    profile = PROFILE_DEFAULTS[args.profile].copy()
    project_name = args.name or target.name
    project_slug = slugify(project_name)
    ctx = {
        **profile,
        "project_name": project_name,
        "project_slug": project_slug,
        "provider": args.provider,
        "platform": args.platform,
        "test_cmd": args.test_cmd,
        "test_cmd_display": args.test_cmd or "<set AGENT_TEST_CMD>",
    }
    for arg_name, ctx_name in [
        ("deployment", "deployment"),
        ("multi_tenant", "multi_tenant"),
        ("user_installable_skills", "user_installable_skills"),
        ("long_running", "long_running"),
    ]:
        value = getattr(args, arg_name)
        if value:
            ctx[ctx_name] = value
    return ctx


def render_template(path: Path, ctx: dict[str, str]) -> str:
    text = path.read_text(encoding="utf-8")
    return Template(text).safe_substitute(ctx)


def planned_files(target: Path, *, include_ci: bool) -> list[tuple[Path, Path, bool]]:
    plan: list[tuple[Path, Path, bool]] = []
    for src, rel in ROOT_TEMPLATES.items():
        plan.append((src, target / rel, True))
    if include_ci:
        plan.append((ASSETS_DIR / "ci-lint-diagnose.yml.template", target / ".github/workflows/agent-lint-and-diagnose.yml", True))
    for script_name in ("lint-agent-design.py", "diagnose-agent.py"):
        plan.append((SCRIPT_DIR / script_name, target / "scripts" / script_name, False))
    for src in sorted(SCAFFOLD_DIR.rglob("*")):
        if src.is_dir() or "__pycache__" in src.parts:
            continue
        rel = src.relative_to(SCAFFOLD_DIR)
        plan.append((src, target / rel, src.suffix == ".template"))
    return plan


def write_plan(plan: list[tuple[Path, Path, bool]], ctx: dict[str, str], *, force: bool) -> None:
    for src, dst, should_render in plan:
        if dst.exists() and not force:
            raise FileExistsError(f"{dst} already exists; pass --force to overwrite known scaffold files")
        dst.parent.mkdir(parents=True, exist_ok=True)
        if should_render:
            dst.write_text(render_template(src, ctx), encoding="utf-8", newline="\n")
        else:
            shutil.copy2(src, dst)


def run_lint(target: Path) -> int:
    result = subprocess.run(
        [sys.executable, str(target / "scripts/lint-agent-design.py"), str(target)],
        cwd=target,
        text=True,
        capture_output=True,
        check=False,
    )
    print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    return result.returncode


def init_project(args: argparse.Namespace) -> int:
    target = Path(args.path).expanduser().resolve()
    ctx = build_context(args, target)
    plan = planned_files(target, include_ci=not args.no_ci)

    if args.list_files or args.dry_run:
        for _src, dst, _render in plan:
            print(dst)
        if args.dry_run:
            return 0

    if target.exists() and any(target.iterdir()) and not args.force:
        print(f"ERROR: {target} is not empty. Pass --force to overwrite known scaffold files.", file=sys.stderr)
        return 2
    target.mkdir(parents=True, exist_ok=True)

    try:
        write_plan(plan, ctx, force=args.force)
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.test_cmd:
        env_example = target / ".env.example"
        if not env_example.exists() or args.force:
            env_example.write_text(f"AGENT_TEST_CMD={args.test_cmd}\n", encoding="utf-8", newline="\n")

    if not args.skip_lint:
        lint_exit = run_lint(target)
        if lint_exit != 0:
            return lint_exit

    print(f"Initialized {ctx['project_name']} at {target}")
    print("Next:")
    print(f"  cd {target}")
    print("  python -m pytest -ra")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Initialize a best-practice agent project")
    parser.add_argument("path", help="target project directory")
    parser.add_argument("--name", default=None, help="human-readable project name")
    parser.add_argument("--profile", choices=sorted(PROFILE_DEFAULTS), default="coding-cli")
    parser.add_argument("--provider", default="OpenAI", help="LLM provider label for AGENTS.md")
    parser.add_argument("--platform", default=os.name, help="target platform label for AGENTS.md")
    parser.add_argument("--deployment", default=None, help="override deployment shape")
    parser.add_argument("--multi-tenant", choices=["yes", "no"], default=None)
    parser.add_argument("--user-installable-skills", default=None)
    parser.add_argument("--long-running", choices=["yes", "no"], default=None)
    parser.add_argument("--test-cmd", default="", help="hard verifier command for AGENT_TEST_CMD")
    parser.add_argument("--force", action="store_true", help="overwrite known scaffold files")
    parser.add_argument("--skip-lint", action="store_true", help="do not run lint-agent-design after writing")
    parser.add_argument("--dry-run", action="store_true", help="print planned files without writing")
    parser.add_argument("--list-files", action="store_true", help="print planned files before writing")
    parser.add_argument("--no-ci", action="store_true", help="do not create GitHub Actions workflow")
    return parser


def main() -> int:
    return init_project(build_parser().parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
