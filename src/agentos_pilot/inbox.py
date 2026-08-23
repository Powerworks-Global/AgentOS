"""CLI for adding/listing tasks in the AgentOS pilot's inbox.

Usage:
    .venv/bin/python -m agentos_pilot.inbox add "task description" [--repo /path/to/repo]
    .venv/bin/python -m agentos_pilot.inbox list

This is the phase-1 "trigger" surface: a human runs `add` by hand. Nothing
here assumes that stays true - a future Discord bot or webhook handler is
just another caller of TaskStore.add(), not a different queue.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from agentos_pilot.env import load_dotenv
from agentos_pilot.tasks import Task, TaskStore


def _inbox_dir() -> Path:
    return Path(os.environ.get("PILOT_INBOX_DIR", "./inbox"))


def _cmd_add(args: argparse.Namespace, store: TaskStore) -> int:
    task: Task = store.add(args.description, source="manual", repo_root=args.repo)
    print(f"[inbox] queued {task.id}: {task.description!r}")
    return 0


def _cmd_list(_args: argparse.Namespace, store: TaskStore) -> int:
    pending = store.list_pending()
    if not pending:
        print("[inbox] pending: (empty)")
        return 0
    for task in pending:
        target = task.repo_root or "(default PILOT_REPO_ROOT)"
        print(f"  {task.id}  [{target}]  {task.description}")
    return 0


def main(argv: list[str] | None = None) -> int:
    load_dotenv(Path(".env"))

    parser = argparse.ArgumentParser(prog="agentos_pilot.inbox")
    sub = parser.add_subparsers(dest="command", required=True)

    add_p = sub.add_parser("add", help="queue a new task")
    add_p.add_argument("description")
    add_p.add_argument("--repo", default=None, help="override PILOT_REPO_ROOT for this task")

    sub.add_parser("list", help="show pending tasks")

    args = parser.parse_args(argv)
    store = TaskStore(_inbox_dir())

    if args.command == "add":
        return _cmd_add(args, store)
    if args.command == "list":
        return _cmd_list(args, store)

    parser.print_help(file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
