"""Tool-permission policy for the AgentOS phase-1 pilot.

Design goal (see the vault note "GCP Fleet Architecture (Hermes-inspired
design)"): the pipeline must run headless, with no human watching for
approval prompts, while still refusing anything destructive. Read/edit/git
operations inside the target repo are auto-approved; everything else is
default-deny. There is no interactive fallback here on purpose — a pilot
run either completes within this policy or stops and logs why, the same
way the article's cron jobs have no interactive tools available at all.
Phase 3 (Discord) is what turns a "deny" into a request a human can approve;
until then, deny is final for the run.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from claude_agent_sdk import (
    PermissionResultAllow,
    PermissionResultDeny,
    ToolPermissionContext,
)

SAFE_READ_TOOLS = {"Read", "Glob", "Grep", "TodoWrite"}
REPO_WRITE_TOOLS = {"Edit", "Write"}

# Matched against the full command string with re.match (i.e. anchored at
# the start). Order doesn't matter — deny patterns are checked first and
# win regardless of position.
ALLOWED_BASH_PATTERNS = [
    r"git status\b",
    r"git diff\b",
    r"git log\b",
    r"git branch\b",
    r"git checkout -b [\w./-]+$",
    r"git add\b",
    r"git commit\b",
    r"git push(?!.*(--force|-f\b))",
    r"(pytest|python -m pytest)\b",
    r"npm (test|run test)\b",
    r"gh pr create\b",
    r"gh auth status\b",
]

# Checked before the allow-list; a hit here denies even if an allow pattern
# would otherwise match (e.g. "git push --force" contains "git push").
DENY_BASH_PATTERNS = [
    r"\brm\s+-rf\b",
    r"\bsudo\b",
    r"--force\b",
    r"\s-f\b",
    r"git reset\s+--hard",
    r"git clean\s+-[a-z]*f",
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r"chmod\s+777",
    r"curl[^|]*\|\s*(sh|bash)\b",
    r">\s*/dev/sd",
    r"\bshutdown\b|\breboot\b",
]


def _bash_decision(command: str) -> tuple[bool, str]:
    for pat in DENY_BASH_PATTERNS:
        if re.search(pat, command):
            return False, f"blocked: command matches destructive pattern /{pat}/"
    for pat in ALLOWED_BASH_PATTERNS:
        if re.search(pat, command):
            return True, f"allowed: command matches allowlist pattern /{pat}/"
    return False, "blocked: command is not on the bash allowlist (default-deny)"


def _append_audit(audit_log: Path, tool_name: str, tool_input: dict, decision: str, reason: str) -> None:
    audit_log.parent.mkdir(parents=True, exist_ok=True)
    with audit_log.open("a") as f:
        f.write(
            json.dumps(
                {
                    "ts": time.time(),
                    "tool": tool_name,
                    "input": tool_input,
                    "decision": decision,
                    "reason": reason,
                }
            )
            + "\n"
        )


def make_can_use_tool(repo_root: Path, audit_log: Path):
    """Build the can_use_tool callback for ClaudeAgentOptions.

    repo_root scopes Edit/Write so the pilot can't touch files outside the
    target repo; audit_log records every allow/deny decision for review.
    """

    repo_root = repo_root.resolve()

    async def can_use_tool(
        tool_name: str, tool_input: dict, context: ToolPermissionContext
    ):
        def deny(reason: str):
            _append_audit(audit_log, tool_name, tool_input, "deny", reason)
            return PermissionResultDeny(message=reason)

        def allow(reason: str):
            _append_audit(audit_log, tool_name, tool_input, "allow", reason)
            return PermissionResultAllow()

        if tool_name in SAFE_READ_TOOLS:
            return allow("read-only tool")

        if tool_name in REPO_WRITE_TOOLS:
            raw_path = tool_input.get("file_path")
            if not raw_path:
                return deny(f"{tool_name} call had no file_path")
            file_path = Path(raw_path).resolve()
            try:
                file_path.relative_to(repo_root)
            except ValueError:
                return deny(f"{tool_name} path {file_path} is outside repo root {repo_root}")
            return allow("write inside repo root")

        if tool_name == "Bash":
            command = tool_input.get("command", "")
            ok, reason = _bash_decision(command)
            return allow(reason) if ok else deny(reason)

        return deny(f"tool {tool_name!r} not covered by pilot policy (default-deny)")

    return can_use_tool
