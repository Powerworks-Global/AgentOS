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
    HookMatcher,
    ProcessError,
    ResultError,
    ResultMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    query,
)

from agentos_pilot.permissions import make_can_use_tool, make_pre_tool_use_hook


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

    # Deliberately no `allowed_tools` here: naming a tool there auto-approves every
    # call to it before can_use_tool is ever consulted (the SDK warns about this
    # directly as CanUseToolShadowedWarning). A real pilot run demonstrated the
    # gap concretely - only 3 of the run's ~15 Bash calls actually reached the
    # policy below, because an early `allowed_tools=[...]` list shadowed the rest.
    #
    # can_use_tool alone isn't enough either: a follow-up test showed the CLI's
    # own bwrap sandbox executes most Bash calls directly and only consults
    # can_use_tool when a call needs to escape that sandbox - so a destructive
    # command the sandbox is willing to run locally would never reach it. The
    # PreToolUse hook fires before that sandboxing decision and is the actual
    # enforcement point (verified: a bare `rm -f` in the target repo was
    # correctly denied by it). can_use_tool is kept anyway as defense-in-depth.
    options = ClaudeAgentOptions(
        cwd=str(config.repo_root),
        can_use_tool=make_can_use_tool(config.repo_root, config.audit_log),
        hooks={
            "PreToolUse": [
                HookMatcher(hooks=[make_pre_tool_use_hook(config.repo_root, config.audit_log)])
            ]
        },
        permission_mode="default",
    )

    print(f"[pilot] repo={config.repo_root} branch={branch_name}")
    print(f"[pilot] audit log -> {config.audit_log}")
    print("[pilot] starting run\n")

    # exit_code starts at 1 (failed) and is only cleared to 0 once we see a
    # ResultMessage that both reports success AND wasn't preceded by an
    # AssistantMessage-level error. A real VM run showed why this matters:
    # an invalid API key surfaced as an AssistantMessage with
    # error="authentication_failed" (only reachable via message.error, not
    # its content blocks), and the SDK still emitted a final ResultMessage
    # with subtype "success" and is_error unset - a naive
    # "started at 0, flip to 1 on is_error" check silently reported total
    # failure as success. Default-failed and require explicit success is the
    # safer posture for something meant to run unattended.
    exit_code = 1
    saw_assistant_error = False
    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                if message.error:
                    saw_assistant_error = True
                    print(f"[pilot] assistant-level error: {message.error}")
                for block in message.content:
                    if isinstance(block, TextBlock):
                        print(block.text)
                    elif isinstance(block, ToolUseBlock):
                        print(f"[tool call] {block.name} {block.input}")
                    elif isinstance(block, ToolResultBlock):
                        print(f"[tool result] {block.content}")
            elif isinstance(message, ResultMessage):
                print(f"\n[pilot] run finished: {message.subtype}")
                if message.is_error or saw_assistant_error or message.subtype != "success":
                    exit_code = 1
                else:
                    exit_code = 0
    except (ProcessError, ResultError) as e:
        print(f"[pilot] SDK/CLI process failure: {e}")
        exit_code = 1

    return exit_code
