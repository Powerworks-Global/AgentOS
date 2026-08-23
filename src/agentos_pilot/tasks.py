"""File-based task queue: the inbox scaffolding for the AgentOS pilot.

Directory layout under PILOT_INBOX_DIR (default ./inbox):
    pending/<task_id>.json     - waiting to be claimed
    processing/<task_id>.json  - claimed by a worker, run in progress
    done/<task_id>.json        - finished successfully
    failed/<task_id>.json      - finished with a non-zero exit code or refusal

Claiming is an os.rename from pending/ to processing/, atomic on a single
filesystem - the mechanism that makes it safe for more than one worker to
poll the same inbox later without double-processing a task, even though
phase 1 only ever runs one worker at a time.

Deliberately the smallest thing that gives AgentOS's stated "task
orchestration" goal a real queue: no database, no message broker, just
files a human (or later a Discord bot / webhook handler) can drop into
pending/ and a worker can pick up. Mirrors the audit log's own JSONL
philosophy and the file-based agent-identity pattern referenced in the GCP
Fleet Architecture design note.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Task:
    id: str
    description: str
    created_at: float
    source: str = "manual"
    repo_root: str | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def new(cls, description: str, source: str = "manual", repo_root: str | None = None) -> "Task":
        return cls(
            id=f"{int(time.time())}-{uuid.uuid4().hex[:8]}",
            description=description,
            created_at=time.time(),
            source=source,
            repo_root=repo_root,
        )

    @classmethod
    def from_json(cls, raw: str) -> "Task":
        return cls(**json.loads(raw))


class TaskStore:
    """A single inbox directory, split into pending/processing/done/failed."""

    def __init__(self, root: Path):
        self.root = root
        self.pending = root / "pending"
        self.processing = root / "processing"
        self.done = root / "done"
        self.failed = root / "failed"
        for d in (self.pending, self.processing, self.done, self.failed):
            d.mkdir(parents=True, exist_ok=True)

    def add(self, description: str, source: str = "manual", repo_root: str | None = None) -> Task:
        task = Task.new(description, source=source, repo_root=repo_root)
        (self.pending / f"{task.id}.json").write_text(task.to_json())
        return task

    def list_pending(self) -> list[Task]:
        return sorted(
            (Task.from_json(p.read_text()) for p in self.pending.glob("*.json")),
            key=lambda t: t.created_at,
        )

    def claim_next(self) -> Task | None:
        """Atomically move the oldest pending task into processing/.

        Returns None on an empty inbox - callers (the worker CLI) treat that
        as a normal, quiet no-op rather than an error, since this is meant
        to be invoked repeatedly by a scheduler.
        """

        for task in self.list_pending():
            src = self.pending / f"{task.id}.json"
            dst = self.processing / f"{task.id}.json"
            try:
                src.rename(dst)
            except FileNotFoundError:
                # Another worker claimed it first between list() and rename().
                continue
            return task
        return None

    def _finish(self, task: Task, target_dir: Path, result: dict) -> None:
        src = self.processing / f"{task.id}.json"
        dst = target_dir / f"{task.id}.json"
        record = {**asdict(task), "result": result}
        dst.write_text(json.dumps(record, indent=2))
        if src.exists():
            src.unlink()

    def mark_done(self, task: Task, exit_code: int) -> None:
        self._finish(task, self.done, {"exit_code": exit_code, "finished_at": time.time()})

    def mark_failed(self, task: Task, exit_code: int, error: str | None = None) -> None:
        self._finish(
            task,
            self.failed,
            {"exit_code": exit_code, "finished_at": time.time(), "error": error},
        )
