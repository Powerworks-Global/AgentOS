"""Per-run cost/outcome metrics: the baseline the token-engineering brief
(see the Obsidian vault's "AgentOS Cost and Performance Optimization
Brief") calls for before any model-routing experiment. Every pipeline run
appends one JSON record here, so "did switching models actually help" can
be answered against real numbers instead of vibes.

Deliberately a separate log from permissions.py's audit_log: that one is a
record of every individual tool-call decision; this is one summary record
per completed run (cost, tokens, duration, outcome).
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class RunMetrics:
    task: str
    branch_name: str
    started_at: float
    finished_at: float
    exit_code: int
    success: bool
    task_id: str | None = None
    duration_ms: int | None = None
    duration_api_ms: int | None = None
    num_turns: int | None = None
    total_cost_usd: float | None = None
    usage: dict[str, Any] | None = None
    model_usage: dict[str, Any] | None = None
    permission_denials: int = 0
    stop_reason: str | None = None
    assistant_error: str | None = None
    sdk_error: str | None = None
    # Gotthard tier-dispatch wiring (ADR-0027 ladder / ADR-0028 context):
    # which rung gotthard.toml's routing_rules resolved this task to, and
    # whether the run actually executed via that rung's own runner
    # ("agy_cli" / "openai_compatible") or fell back to the existing
    # Claude SDK path ("claude_sdk_fallback"), e.g. because the rung's
    # requirements (binary / api_key_env) weren't satisfiable.
    resolved_tier: str | None = None
    resolved_tier_model: str | None = None
    tier_runner_type: str | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self))


def append_metrics(path: Path, metrics: RunMetrics) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(metrics.to_json() + "\n")


def read_all(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def summarize(path: Path) -> dict[str, Any]:
    """Aggregate the metrics log into the baseline numbers the token-
    engineering brief calls for: success rate and cost, not vibes.
    """

    runs = read_all(path)
    if not runs:
        return {"runs": 0}

    successes = [r for r in runs if r.get("success")]
    costs = [r["total_cost_usd"] for r in runs if r.get("total_cost_usd") is not None]
    turns = [r["num_turns"] for r in runs if r.get("num_turns") is not None]
    denials = [r.get("permission_denials", 0) for r in runs]

    return {
        "runs": len(runs),
        "successes": len(successes),
        "success_rate": len(successes) / len(runs),
        "total_cost_usd": round(sum(costs), 4) if costs else None,
        "avg_cost_usd": round(sum(costs) / len(costs), 4) if costs else None,
        "avg_turns": round(sum(turns) / len(turns), 2) if turns else None,
        "avg_permission_denials": round(sum(denials) / len(runs), 2),
    }


def now() -> float:
    return time.time()
