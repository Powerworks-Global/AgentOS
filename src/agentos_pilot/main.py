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

from agentos_pilot.config import GotthardConfig
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

    # Gotthard tier dispatch (ADR-0027 ladder): load the control-plane
    # config and resolve which rung this task routes to, before the
    # pipeline decides whether that rung's runner is actually dispatchable
    # right now. Resolved again inside run_pipeline() off the same config
    # path for the real dispatch decision + metrics/audit recording - this
    # call is so the tier is visible here too, for a human watching.
    gotthard_config_path = Path(os.environ.get("GOTTHARD_CONFIG_PATH", "gotthard.toml"))
    gotthard_config = GotthardConfig.from_toml_file(gotthard_config_path)
    resolved_tier = gotthard_config.resolve_tier_for_task(task)
    print(f"[pilot] resolved tier for task: {resolved_tier.name} (model={resolved_tier.model})")

    # No notify= here deliberately: this entrypoint is a human watching the
    # terminal by hand. Telegram notification (see worker.py) matters for
    # the unattended/scheduled path, not this one - wiring it here too
    # would just be a duplicate ping for someone already watching.
    config = PilotConfig(
        repo_root=Path(repo_root),
        branch_prefix=os.environ.get("PILOT_BRANCH_PREFIX", "pilot/"),
        audit_log=Path(os.environ.get("PILOT_AUDIT_LOG", "./audit/decisions.jsonl")),
        metrics_log=Path(os.environ.get("PILOT_METRICS_LOG", "./audit/runs.jsonl")),
        gotthard_config_path=gotthard_config_path,
        task=task,
    )

    try:
        return asyncio.run(run_pipeline(config))
    except PilotError as e:
        print(f"[pilot] refusing to run: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
