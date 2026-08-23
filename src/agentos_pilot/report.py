"""CLI: print the current cost/success baseline from PILOT_METRICS_LOG.

This is the "instrument a baseline before any model swap" step the
token-engineering brief calls for - a real number to compare a future
Gemini/Haiku-routed run against, instead of an impression that it's
cheaper.

Usage:
    .venv/bin/python -m agentos_pilot.report
"""

from __future__ import annotations

import os
from pathlib import Path

from agentos_pilot.env import load_dotenv
from agentos_pilot.metrics import summarize


def main() -> int:
    load_dotenv(Path(".env"))
    path = Path(os.environ.get("PILOT_METRICS_LOG", "./audit/runs.jsonl"))
    stats = summarize(path)

    if stats["runs"] == 0:
        print(f"[report] no runs recorded yet in {path}")
        return 0

    print(f"[report] baseline from {path} ({stats['runs']} run(s))")
    print(f"  success rate:            {stats['success_rate']:.0%} ({stats['successes']}/{stats['runs']})")
    print(f"  total cost:              ${stats['total_cost_usd']}")
    print(f"  avg cost/run:            ${stats['avg_cost_usd']}")
    print(f"  avg turns/run:           {stats['avg_turns']}")
    print(f"  avg permission denials:  {stats['avg_permission_denials']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
