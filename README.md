# AgentOS pilot — phase 1

Phase-1 pilot from the AgentOS design work in the Obsidian vault
(`Planned_Projects/AgentOS/GCP Fleet Architecture (Hermes-inspired design).md`).
Goal: prove "headless coding pipeline, no tmux, no permission nagging, still
refuses anything destructive" locally, on Claude Agent SDK, before touching
any GCP infrastructure.

One `query()` call drives a full branch → implement → test → PR loop. A
`can_use_tool` policy (`src/agentos_pilot/permissions.py`) auto-approves
read tools and repo-scoped edits, allows a fixed allowlist of safe git/test/
`gh` commands, and default-denies everything else — no interactive prompt,
no human in the loop, matching the "cron jobs have no interactive tools"
principle from the design note. Every decision is logged to
`audit/decisions.jsonl` for review after a run.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
cp .env.example .env   # then set PILOT_REPO_ROOT to a real, clean git repo
```

Requires the `claude` CLI already installed and authenticated on this
machine (it is, as of this scaffold) — the SDK drives it directly, no
separate API key needed.

## Run

```bash
.venv/bin/python -m agentos_pilot.main "add input validation to the signup form"
```

The pipeline refuses to start if `PILOT_REPO_ROOT` isn't a git repo, or has
a dirty working tree — it should never run on top of uncommitted work.

## Test

```bash
.venv/bin/pip install pytest
.venv/bin/python -m pytest -q
```

Tests cover the permission policy only (`tests/test_permissions.py`) —
that's the one piece of this pilot where a logic bug would actually be
dangerous (an over-broad allow regex letting a destructive command through).

## What this pilot deliberately does not do yet

- No Discord integration (phase 3 in the design note) — a denied tool call
  is final for the run, not escalated to a human for approval.
- No GCP (phase 2) — this runs on whatever machine you invoke it on.
- No multi-profile/service-account separation — single policy, single repo.
- No parallel subagent fan-out (phase 4) — one linear pipeline.

Those are the next phases once this one is proven out.
