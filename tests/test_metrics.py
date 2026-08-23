from agentos_pilot.metrics import RunMetrics, append_metrics, read_all, summarize


def _metrics(**overrides):
    base = dict(
        task="do the thing",
        branch_name="pilot/123",
        started_at=1.0,
        finished_at=2.0,
        exit_code=0,
        success=True,
        total_cost_usd=0.05,
        num_turns=4,
        permission_denials=1,
    )
    base.update(overrides)
    return RunMetrics(**base)


def test_append_and_read_all_round_trips(tmp_path):
    path = tmp_path / "audit" / "runs.jsonl"
    append_metrics(path, _metrics())
    append_metrics(path, _metrics(exit_code=1, success=False, total_cost_usd=0.10))

    records = read_all(path)
    assert len(records) == 2
    assert records[0]["success"] is True
    assert records[1]["exit_code"] == 1


def test_read_all_on_missing_file_returns_empty(tmp_path):
    assert read_all(tmp_path / "nope.jsonl") == []


def test_summarize_on_empty_log(tmp_path):
    stats = summarize(tmp_path / "nope.jsonl")
    assert stats == {"runs": 0}


def test_summarize_computes_success_rate_and_cost(tmp_path):
    path = tmp_path / "runs.jsonl"
    append_metrics(path, _metrics(total_cost_usd=0.10, num_turns=2, permission_denials=0))
    append_metrics(path, _metrics(total_cost_usd=0.20, num_turns=4, permission_denials=2))
    append_metrics(path, _metrics(exit_code=1, success=False, total_cost_usd=0.05, num_turns=1, permission_denials=1))

    stats = summarize(path)

    assert stats["runs"] == 3
    assert stats["successes"] == 2
    assert stats["success_rate"] == 2 / 3
    assert stats["total_cost_usd"] == 0.35
    assert stats["avg_cost_usd"] == round(0.35 / 3, 4)
    assert stats["avg_turns"] == round((2 + 4 + 1) / 3, 2)
    assert stats["avg_permission_denials"] == round((0 + 2 + 1) / 3, 2)


def test_summarize_handles_missing_cost_gracefully(tmp_path):
    path = tmp_path / "runs.jsonl"
    append_metrics(path, _metrics(total_cost_usd=None, num_turns=None))

    stats = summarize(path)

    assert stats["runs"] == 1
    assert stats["total_cost_usd"] is None
    assert stats["avg_cost_usd"] is None
    assert stats["avg_turns"] is None
