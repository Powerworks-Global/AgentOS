"""Phase-1 pilot pipeline: branch -> implement -> test -> PR, headless.

One Claude Agent SDK `query()` call drives the whole thing — the model
decides the sequence of tool calls, our can_use_tool policy (permissions.py)
decides what it's allowed to actually do. This mirrors the article's skill
pattern (sequential setup, then agent-driven execution) without a second
framework: no tmux, nobody watching for a permission prompt.
"""

from __future__ import annotations

import asyncio
import subprocess
from dataclasses import dataclass
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    query,
)

from agentos_pilot.permissions import make_can_use_tool


class PilotError(RuntimeError):
    pass


@dataclass
class PilotConfig:
    repo_root: Path
    branch_prefix: str
    audit_log: Path
    task: str


def _run_git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise PilotError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _check_preconditions(repo_root: Path) -> None:
    if not repo_root.is_dir():
        raise PilotError(f"repo root does not exist: {repo_root}")
    if not (repo_root / ".git").exists():
        raise PilotError(f"not a git repo: {repo_root}")
    status = _run_git(repo_root, "status", "--porcelain")
    if status:
        raise PilotError(
            f"working tree at {repo_root} is not clean; refusing to start a pilot "
            f"run on top of uncommitted changes:\n{status}"
        )


def _build_prompt(task: str, branch_name: str) -> str:
    return (
        "You are running unattended, headless, with no human watching for "
        "approval prompts. Complete this task end to end:\n\n"
        f"1. Create and check out a new git branch named `{branch_name}`.\n"
        f"2. Implement: {task}\n"
        "3. Run the project's existing test suite (or the most obviously "
        "relevant subset) and make sure it passes before proceeding. If "
        "there is no test suite, say so explicitly rather than skipping "
        "verification silently.\n"
        "4. Commit your changes with a clear message.\n"
        "5. Push the branch and open a pull request with `gh pr create`, "
        "with a description summarizing what changed and why, and the test "
        "output you saw.\n\n"
        "You do not have permission to force-push, reset --hard, delete "
        "files outside normal edits, or run anything destructive — those "
        "calls will simply be denied. If you hit a denied call you believe "
        "is necessary, stop and report it in your final summary instead of "
        "working around it."
    )


async def run_pipeline(config: PilotConfig) -> int:
    _check_preconditions(config.repo_root)

    branch_name = f"{config.branch_prefix}{int(asyncio.get_event_loop().time())}"
    prompt = _build_prompt(config.task, branch_name)

    options = ClaudeAgentOptions(
        cwd=str(config.repo_root),
        can_use_tool=make_can_use_tool(config.repo_root, config.audit_log),
        permission_mode="default",
        allowed_tools=["Read", "Glob", "Grep", "Edit", "Write", "Bash", "TodoWrite"],
    )

    print(f"[pilot] repo={config.repo_root} branch={branch_name}")
    print(f"[pilot] audit log -> {config.audit_log}")
    print("[pilot] starting run\n")

    exit_code = 0
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    print(block.text)
                elif isinstance(block, ToolUseBlock):
                    print(f"[tool call] {block.name} {block.input}")
                elif isinstance(block, ToolResultBlock):
                    print(f"[tool result] {block.content}")
        elif isinstance(message, ResultMessage):
            print(f"\n[pilot] run finished: {message.subtype}")
            if message.is_error:
                exit_code = 1

    return exit_code
