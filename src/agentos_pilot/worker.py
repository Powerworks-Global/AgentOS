"""CLI entrypoint for the AgentOS pilot's inbox worker.

Run once per invocation: claim the oldest pending task (if any), run the
existing branch->implement->test->PR pipeline against it, file the result.
Meant to be invoked repeatedly by a scheduler (cron on the VM, or Cloud
Scheduler per the GCP Fleet Architecture design note) rather than looping
forever itself - same "no interactive tools, nothing long-running to
babysit" posture as the rest of the pilot. Wiring an actual cron/Cloud
Scheduler entry to call this is a separate, later infra step.

Usage:
    .venv/bin/python -m agentos_pilot.worker
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from agentos_pilot.env import load_dotenv
from agentos_pilot.pipeline import PilotConfig, PilotError, run_pipeline
from agentos_pilot.tasks import TaskStore


def _inbox_dir() -> Path:
    return Path(os.environ.get("PILOT_INBOX_DIR", "./inbox"))


async def run_once() -> int:
    store = TaskStore(_inbox_dir())

    task = store.claim_next()
    if task is None:
        print("[worker] inbox empty, nothing to do")
        return 0

    repo_root = task.repo_root or os.environ.get("PILOT_REPO_ROOT")
    if not repo_root:
        store.mark_failed(task, 2, error="no repo_root on task and PILOT_REPO_ROOT unset")
        print(f"[worker] task {task.id} failed: no repo_root available", file=sys.stderr)
        return 2

    config = PilotConfig(
        repo_root=Path(repo_root),
        branch_prefix=os.environ.get("PILOT_BRANCH_PREFIX", "pilot/"),
        audit_log=Path(os.environ.get("PILOT_AUDIT_LOG", "./audit/decisions.jsonl")),
        task=task.description,
    )

    print(f"[worker] claimed task {task.id}: {task.description!r}")
    try:
        exit_code = await run_pipeline(config)
    except PilotError as e:
        store.mark_failed(task, 1, error=str(e))
        print(f"[worker] task {task.id} refused to run: {e}", file=sys.stderr)
        return 1

    if exit_code == 0:
        store.mark_done(task, exit_code)
        print(f"[worker] task {task.id} done")
    else:
        store.mark_failed(task, exit_code)
        print(f"[worker] task {task.id} failed (exit {exit_code})", file=sys.stderr)

    return exit_code


def main() -> int:
    load_dotenv(Path(".env"))
    return asyncio.run(run_once())


if __name__ == "__main__":
    raise SystemExit(main())
