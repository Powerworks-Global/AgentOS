from agentos_pilot.tasks import TaskStore


def test_add_writes_pending_file(tmp_path):
    store = TaskStore(tmp_path / "inbox")
    task = store.add("do the thing")
    assert (store.pending / f"{task.id}.json").exists()
    assert task.description == "do the thing"
    assert task.source == "manual"
    assert task.repo_root is None


def test_add_with_repo_override(tmp_path):
    store = TaskStore(tmp_path / "inbox")
    task = store.add("do the thing", repo_root="/some/repo")
    assert task.repo_root == "/some/repo"


def test_list_pending_orders_by_creation(tmp_path):
    store = TaskStore(tmp_path / "inbox")
    first = store.add("first")
    second = store.add("second")
    pending = store.list_pending()
    assert [t.id for t in pending] == [first.id, second.id]


def test_claim_next_moves_pending_to_processing(tmp_path):
    store = TaskStore(tmp_path / "inbox")
    task = store.add("do the thing")

    claimed = store.claim_next()

    assert claimed is not None
    assert claimed.id == task.id
    assert not (store.pending / f"{task.id}.json").exists()
    assert (store.processing / f"{task.id}.json").exists()


def test_claim_next_returns_none_on_empty_inbox(tmp_path):
    store = TaskStore(tmp_path / "inbox")
    assert store.claim_next() is None


def test_claim_next_is_fifo(tmp_path):
    store = TaskStore(tmp_path / "inbox")
    first = store.add("first")
    store.add("second")

    claimed = store.claim_next()
    assert claimed.id == first.id


def test_mark_done_moves_to_done_with_result(tmp_path):
    store = TaskStore(tmp_path / "inbox")
    task = store.add("do the thing")
    store.claim_next()

    store.mark_done(task, 0)

    assert not (store.processing / f"{task.id}.json").exists()
    done_file = store.done / f"{task.id}.json"
    assert done_file.exists()
    import json

    record = json.loads(done_file.read_text())
    assert record["result"]["exit_code"] == 0


def test_mark_failed_moves_to_failed_with_error(tmp_path):
    store = TaskStore(tmp_path / "inbox")
    task = store.add("do the thing")
    store.claim_next()

    store.mark_failed(task, 1, error="boom")

    failed_file = store.failed / f"{task.id}.json"
    assert failed_file.exists()
    import json

    record = json.loads(failed_file.read_text())
    assert record["result"]["exit_code"] == 1
    assert record["result"]["error"] == "boom"


def test_double_claim_only_succeeds_once(tmp_path):
    store = TaskStore(tmp_path / "inbox")
    store.add("only task")

    first_claim = store.claim_next()
    second_claim = store.claim_next()

    assert first_claim is not None
    assert second_claim is None
