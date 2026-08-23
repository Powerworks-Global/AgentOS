import asyncio
import json

import pytest

from agentos_pilot import worker
from agentos_pilot.pipeline import PilotError
from agentos_pilot.tasks import TaskStore


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def inbox(tmp_path, monkeypatch):
    inbox_dir = tmp_path / "inbox"
    monkeypatch.setenv("PILOT_INBOX_DIR", str(inbox_dir))
    return TaskStore(inbox_dir)


def test_run_once_on_empty_inbox_is_a_noop(inbox, monkeypatch):
    monkeypatch.setenv("PILOT_REPO_ROOT", "/irrelevant")
    exit_code = _run(worker.run_once())
    assert exit_code == 0


def test_run_once_claims_task_and_marks_done_on_success(inbox, monkeypatch, tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    task = inbox.add("add a feature")

    async def fake_run_pipeline(config):
        assert config.repo_root == repo_root
        assert config.task == "add a feature"
        return 0

    monkeypatch.setattr(worker, "run_pipeline", fake_run_pipeline)
    monkeypatch.setenv("PILOT_REPO_ROOT", str(repo_root))

    exit_code = _run(worker.run_once())

    assert exit_code == 0
    assert (inbox.done / f"{task.id}.json").exists()
    assert not (inbox.processing / f"{task.id}.json").exists()


def test_run_once_marks_failed_on_nonzero_exit(inbox, monkeypatch, tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    task = inbox.add("add a feature")

    async def fake_run_pipeline(config):
        return 1

    monkeypatch.setattr(worker, "run_pipeline", fake_run_pipeline)
    monkeypatch.setenv("PILOT_REPO_ROOT", str(repo_root))

    exit_code = _run(worker.run_once())

    assert exit_code == 1
    assert (inbox.failed / f"{task.id}.json").exists()


def test_run_once_marks_failed_on_pilot_error(inbox, monkeypatch, tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    task = inbox.add("add a feature")

    async def fake_run_pipeline(config):
        raise PilotError("dirty working tree")

    monkeypatch.setattr(worker, "run_pipeline", fake_run_pipeline)
    monkeypatch.setenv("PILOT_REPO_ROOT", str(repo_root))

    exit_code = _run(worker.run_once())

    assert exit_code == 1
    failed_file = inbox.failed / f"{task.id}.json"
    assert failed_file.exists()
    record = json.loads(failed_file.read_text())
    assert "dirty working tree" in record["result"]["error"]


def test_run_once_uses_task_repo_override_over_env(inbox, monkeypatch, tmp_path):
    task_repo = tmp_path / "task-repo"
    task_repo.mkdir()
    env_repo = tmp_path / "env-repo"
    env_repo.mkdir()

    inbox.add("scoped task", repo_root=str(task_repo))

    async def fake_run_pipeline(config):
        assert config.repo_root == task_repo
        return 0

    monkeypatch.setattr(worker, "run_pipeline", fake_run_pipeline)
    monkeypatch.setenv("PILOT_REPO_ROOT", str(env_repo))

    exit_code = _run(worker.run_once())
    assert exit_code == 0


def test_run_once_fails_cleanly_with_no_repo_root_available(inbox, monkeypatch):
    monkeypatch.delenv("PILOT_REPO_ROOT", raising=False)
    task = inbox.add("no repo configured anywhere")

    exit_code = _run(worker.run_once())

    assert exit_code == 2
    assert (inbox.failed / f"{task.id}.json").exists()
