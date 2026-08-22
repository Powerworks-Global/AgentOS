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

# Matched anywhere in the command via re.search (not anchored), after
# heredoc/quoted content is stripped out (see _strip_literal_text). Order
# doesn't matter — deny patterns are checked first and win regardless of
# position.
ALLOWED_BASH_PATTERNS = [
    r"git status\b",
    r"git diff\b",
    r"git log\b",
    r"git branch\b",
    r"git remote(\s+-v)?\b",
    r"git checkout -b [\w./-]+$",
    r"git add\b",
    r"git commit\b",
    r"git push(?!.*(--force|-f\b))",
    r"(pytest|python3? -m pytest)\b",
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


_HEREDOC_RE = re.compile(r"<<[-~]?\s*['\"]?(\w+)['\"]?\n.*?\n\1\b", re.DOTALL)
_SINGLE_QUOTED_RE = re.compile(r"'[^']*'")
_DOUBLE_QUOTED_RE = re.compile(r'"(?:[^"\\]|\\.)*"')


def _strip_literal_text(command: str) -> str:
    """Blank out heredoc bodies and quoted strings before pattern matching.

    A real pilot run produced a `gh pr create --body "$(cat <<'EOF' ... EOF)"`
    call whose heredoc PR-body text happened to contain the substring
    "npm test" - matching an allow pattern for the wrong reason. Matching
    patterns against arbitrary quoted/heredoc content means a commit message
    or PR body could accidentally (or deliberately) flip an allow/deny
    decision that has nothing to do with what the command actually runs.
    This doesn't give perfect shell parsing, but it removes the specific
    class of literal-text content that shouldn't influence the decision.
    """

    command = _HEREDOC_RE.sub("", command)
    command = _SINGLE_QUOTED_RE.sub("''", command)
    command = _DOUBLE_QUOTED_RE.sub('""', command)
    return command


def _bash_decision(command: str) -> tuple[bool, str]:
    structural = _strip_literal_text(command)
    for pat in DENY_BASH_PATTERNS:
        if re.search(pat, structural):
            return False, f"blocked: command matches destructive pattern /{pat}/"
    for pat in ALLOWED_BASH_PATTERNS:
        if re.search(pat, structural):
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


def _decide(repo_root: Path, tool_name: str, tool_input: dict) -> tuple[bool, str]:
    """Core allow/deny decision, independent of which SDK hook calls it.

    repo_root scopes Edit/Write so the pilot can't touch files outside the
    target repo.
    """

    if tool_name in SAFE_READ_TOOLS:
        return True, "read-only tool"

    if tool_name in REPO_WRITE_TOOLS:
        raw_path = tool_input.get("file_path")
        if not raw_path:
            return False, f"{tool_name} call had no file_path"
        file_path = Path(raw_path).resolve()
        try:
            file_path.relative_to(repo_root)
        except ValueError:
            return False, f"{tool_name} path {file_path} is outside repo root {repo_root}"
        return True, "write inside repo root"

    if tool_name == "Bash":
        command = tool_input.get("command", "")
        return _bash_decision(command)

    return False, f"tool {tool_name!r} not covered by pilot policy (default-deny)"


def make_can_use_tool(repo_root: Path, audit_log: Path):
    """Build the can_use_tool callback for ClaudeAgentOptions.

    Kept as defense-in-depth alongside the PreToolUse hook below (see
    make_pre_tool_use_hook) - but on its own this is NOT a reliable gate.
    A real pilot run showed the Claude Code CLI's own bwrap sandbox executes
    most Bash calls directly and only consults can_use_tool when a call
    needs to escape the sandbox (e.g. network access, or a command the
    sandbox itself can't run) - so a destructive command the sandbox is
    willing to run locally would never reach this callback at all. The
    PreToolUse hook fires before that sandboxing decision is made and is
    the actual enforcement point; this stays only because plugin/tool code
    that checks can_use_tool directly should still see the same answer.
    """

    repo_root = repo_root.resolve()

    async def can_use_tool(
        tool_name: str, tool_input: dict, context: ToolPermissionContext
    ):
        ok, reason = _decide(repo_root, tool_name, tool_input)
        _append_audit(audit_log, tool_name, tool_input, "allow" if ok else "deny", reason)
        return PermissionResultAllow() if ok else PermissionResultDeny(message=reason)

    return can_use_tool


def make_pre_tool_use_hook(repo_root: Path, audit_log: Path):
    """Build the PreToolUse hook - the actual enforcement point.

    Unlike can_use_tool, a PreToolUse hook runs before the SDK decides
    whether a call can be satisfied inside its sandbox, so it sees and can
    block every tool call regardless of sandbox status. Returns the
    permissionDecision shape PreToolUse hooks expect.
    """

    repo_root = repo_root.resolve()

    async def pre_tool_use(input_data, tool_use_id, context):
        tool_name = input_data.get("tool_name", "")
        tool_input = input_data.get("tool_input", {}) or {}
        ok, reason = _decide(repo_root, tool_name, tool_input)
        _append_audit(audit_log, tool_name, tool_input, "allow" if ok else "deny", reason)
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow" if ok else "deny",
                "permissionDecisionReason": reason,
            }
        }

    return pre_tool_use
