"""Tests for Gotthard tier-dispatch wiring in pipeline.py: resolving a tier
from gotthard.toml, dispatching to that tier's runner when its requirements
are satisfiable, falling back to the Claude SDK path (logging a
WOULD-NOT-RUN / fallback record) when they aren't, and recording the
resolved tier name + model + runner type in both RunMetrics and the audit
decisions log either way.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from agentos_pilot import pipeline
from agentos_pilot.metrics import read_all
from agentos_pilot.pipeline import PilotConfig, run_pipeline
from agentos_pilot.runner import AgyCliRunner


GOTTHARD_TOML = """
[runtime]
default_tier = "flash"

[tiers.flash]
description = "Antigravity CLI / Gemini Flash"
type = "cli_or_api"
engine = "agy"
model = "gemini-3.8-flash"
api_key_env = "GEMINI_API_KEY"
fallback_tier = "ifm"

[tiers.ifm]
description = "IFM"
type = "openai_compatible"
api_base = "https://api.ifm.ai/v1"
model = "IFM/K2-Horizon-375B-A23B"
api_key_env = "IFM_API_KEY"

[routing_rules]
"test,lint" = "flash"
"architecture" = "ifm"
"""


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def repo(tmp_path):
    import subprocess

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    subprocess.run(["git", "init"], cwd=repo_root, capture_output=True)
    subprocess.run(["git", "config", "user.email", "a@b.c"], cwd=repo_root, capture_output=True)
    subprocess.run(["git", "config", "user.name", "a"], cwd=repo_root, capture_output=True)
    (repo_root / "README.md").write_text("hi\n")
    subprocess.run(["git", "add", "."], cwd=repo_root, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_root, capture_output=True)
    return repo_root


@pytest.fixture
def gotthard_config_path(tmp_path):
    path = tmp_path / "gotthard.toml"
    path.write_text(GOTTHARD_TOML)
    return path


def _make_config(repo, tmp_path, gotthard_config_path, task):
    return PilotConfig(
        repo_root=repo,
        branch_prefix="pilot/",
        audit_log=tmp_path / "audit" / "decisions.jsonl",
        metrics_log=tmp_path / "audit" / "runs.jsonl",
        task=task,
        gotthard_config_path=gotthard_config_path,
    )


def test_dispatches_to_tier_runner_when_requirements_met(
    repo, tmp_path, gotthard_config_path, monkeypatch
):
    monkeypatch.setattr(AgyCliRunner, "is_available", lambda self: True)
    monkeypatch.setattr(AgyCliRunner, "run", lambda self, model, prompt: "ok from agy")

    config = _make_config(repo, tmp_path, gotthard_config_path, "run tests and lint")
    exit_code = _run(run_pipeline(config))

    assert exit_code == 0

    metrics = read_all(config.metrics_log)
    assert len(metrics) == 1
    assert metrics[0]["resolved_tier"] == "flash"
    assert metrics[0]["resolved_tier_model"] == "gemini-3.8-flash"
    assert metrics[0]["tier_runner_type"] == "agy_cli"
    assert metrics[0]["success"] is True

    audit = [json.loads(l) for l in config.audit_log.read_text().splitlines()]
    tier_records = [r for r in audit if r.get("tool") == "gotthard.tier_dispatch"]
    assert len(tier_records) == 1
    assert tier_records[0]["decision"] == "dispatch"
    assert tier_records[0]["tier"] == "flash"
    assert tier_records[0]["model"] == "gemini-3.8-flash"
    assert tier_records[0]["runner_type"] == "agy_cli"


def test_falls_back_to_claude_sdk_when_requirements_not_met(
    repo, tmp_path, gotthard_config_path, monkeypatch
):
    # No agy binary, no GEMINI_API_KEY/IFM_API_KEY in env -> flash tier's
    # requirements aren't satisfiable -> WOULD-NOT-RUN -> fall back to the
    # existing Claude SDK path. We stub pipeline.query so the test never
    # actually shells out to the claude CLI.
    monkeypatch.setattr(AgyCliRunner, "is_available", lambda self: False)

    from claude_agent_sdk import ResultMessage

    async def fake_query(prompt, options):
        yield ResultMessage(
            subtype="success",
            duration_ms=10,
            duration_api_ms=5,
            is_error=False,
            num_turns=1,
            session_id="sess-1",
            total_cost_usd=0.01,
        )

    monkeypatch.setattr(pipeline, "query", fake_query)

    config = _make_config(repo, tmp_path, gotthard_config_path, "run tests and lint")
    exit_code = _run(run_pipeline(config))

    assert exit_code == 0

    metrics = read_all(config.metrics_log)
    assert len(metrics) == 1
    assert metrics[0]["resolved_tier"] == "flash"
    assert metrics[0]["tier_runner_type"] == "claude_sdk_fallback"

    audit = [json.loads(l) for l in config.audit_log.read_text().splitlines()]
    tier_records = [r for r in audit if r.get("tool") == "gotthard.tier_dispatch"]
    assert len(tier_records) == 1
    assert tier_records[0]["decision"] == "would-not-run"
    assert tier_records[0]["tier"] == "flash"
    assert "agy" in tier_records[0]["reason"]


def test_runner_error_during_dispatch_falls_back_with_fallback_audit_record(
    repo, tmp_path, gotthard_config_path, monkeypatch
):
    monkeypatch.setattr(AgyCliRunner, "is_available", lambda self: True)

    def raising_run(self, model, prompt):
        from agentos_pilot.runner import RunnerError

        raise RunnerError("boom")

    monkeypatch.setattr(AgyCliRunner, "run", raising_run)

    from claude_agent_sdk import ResultMessage

    async def fake_query(prompt, options):
        yield ResultMessage(
            subtype="success",
            duration_ms=10,
            duration_api_ms=5,
            is_error=False,
            num_turns=1,
            session_id="sess-1",
            total_cost_usd=0.01,
        )

    monkeypatch.setattr(pipeline, "query", fake_query)

    config = _make_config(repo, tmp_path, gotthard_config_path, "run tests and lint")
    exit_code = _run(run_pipeline(config))

    assert exit_code == 0

    audit = [json.loads(l) for l in config.audit_log.read_text().splitlines()]
    tier_records = [r for r in audit if r.get("tool") == "gotthard.tier_dispatch"]
    decisions = [r["decision"] for r in tier_records]
    assert decisions == ["dispatch", "fallback"]

    metrics = read_all(config.metrics_log)
    assert metrics[0]["tier_runner_type"] == "claude_sdk_fallback"
