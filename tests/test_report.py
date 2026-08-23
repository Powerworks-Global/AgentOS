from agentos_pilot import report
from agentos_pilot.metrics import RunMetrics, append_metrics


def test_report_on_empty_log(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PILOT_METRICS_LOG", str(tmp_path / "runs.jsonl"))

    exit_code = report.main()

    assert exit_code == 0
    assert "no runs recorded yet" in capsys.readouterr().out


def test_report_prints_baseline_stats(tmp_path, monkeypatch, capsys):
    path = tmp_path / "runs.jsonl"
    append_metrics(
        path,
        RunMetrics(
            task="x",
            branch_name="pilot/1",
            started_at=1.0,
            finished_at=2.0,
            exit_code=0,
            success=True,
            total_cost_usd=0.10,
            num_turns=3,
            permission_denials=0,
        ),
    )
    monkeypatch.setenv("PILOT_METRICS_LOG", str(path))

    exit_code = report.main()
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "success rate" in out
    assert "100%" in out
    assert "$0.1" in out
