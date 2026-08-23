"""CLI entrypoint for the AgentOS phase-1 pilot.

Usage:
    .venv/bin/python -m agentos_pilot.main "add input validation to the signup form"

Reads PILOT_REPO_ROOT / PILOT_BRANCH_PREFIX / PILOT_AUDIT_LOG from the
environment (or a .env file in the current directory) so this can be
invoked identically by hand or from a scheduler later, with no code change.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from agentos_pilot.env import load_dotenv
from agentos_pilot.pipeline import PilotConfig, PilotError, run_pipeline


def main() -> int:
    load_dotenv(Path(".env"))

    if len(sys.argv) < 2:
        print("usage: python -m agentos_pilot.main <task description>", file=sys.stderr)
        return 2
    task = " ".join(sys.argv[1:])

    repo_root = os.environ.get("PILOT_REPO_ROOT")
    if not repo_root:
        print("PILOT_REPO_ROOT is not set (see .env.example)", file=sys.stderr)
        return 2

    config = PilotConfig(
        repo_root=Path(repo_root),
        branch_prefix=os.environ.get("PILOT_BRANCH_PREFIX", "pilot/"),
        audit_log=Path(os.environ.get("PILOT_AUDIT_LOG", "./audit/decisions.jsonl")),
        task=task,
    )

    try:
        return asyncio.run(run_pipeline(config))
    except PilotError as e:
        print(f"[pilot] refusing to run: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
