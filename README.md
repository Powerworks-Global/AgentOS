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

## Inbox / task queue

`agentos_pilot.main` above runs exactly one task, synchronously, from the
command line. The inbox is the queue on top of that, so tasks can be
enqueued (by hand now; by a Discord bot or webhook later) faster than
they're worked, and a worker can pick them off unattended:

```bash
# Queue tasks (source is always "manual" for now)
.venv/bin/python -m agentos_pilot.inbox add "add input validation to the signup form"
.venv/bin/python -m agentos_pilot.inbox add "fix the flaky date test" --repo /path/to/other/repo
.venv/bin/python -m agentos_pilot.inbox list

# Claim and run the oldest pending task, once
.venv/bin/python -m agentos_pilot.worker
```

`worker` claims at most one task per invocation and exits — it's meant to
be invoked repeatedly by a scheduler (cron on the VM, or Cloud Scheduler
hitting an endpoint, per the GCP Fleet Architecture design note), not to
loop forever itself. An empty inbox is a quiet no-op (exit 0), not an
error. Claiming is an atomic file rename (`pending/` → `processing/`), so
running more than one worker against the same `PILOT_INBOX_DIR` won't
double-process a task. A task without its own `--repo` falls back to
`PILOT_REPO_ROOT`; one finishes in `inbox/done/<id>.json` or
`inbox/failed/<id>.json` with the exit code (and error, if any) recorded
alongside it.

**Not wired yet**: an actual cron entry or Cloud Scheduler job calling
`worker` on a schedule. That's a separate, later infra step — this is the
queue and the consumer, not the trigger itself.

## Test

```bash
.venv/bin/pip install pytest
.venv/bin/python -m pytest -q
```

Tests cover the permission policy (`tests/test_permissions.py` — the one
piece where a logic bug would actually be dangerous, e.g. an over-broad
allow regex letting a destructive command through) and the inbox/worker
queue logic (`tests/test_tasks.py`, `tests/test_worker.py` — claim/finish
semantics, tested against a real filesystem with the actual Claude Agent
SDK call mocked out).

## What this pilot deliberately does not do yet

- No scheduler wired to `worker` — cron/Cloud Scheduler invocation is a
  later infra step; today it's run by hand.
- No Discord integration (phase 3 in the design note) — a denied tool call
  is final for the run, not escalated to a human for approval.
- No multi-profile/service-account separation — single policy, single repo
  per run (though a task can now point at a different repo than
  `PILOT_REPO_ROOT` via `inbox add --repo`).
- No parallel subagent fan-out (phase 4) — `worker` claims and runs one
  task at a time, sequentially.

Those are the next phases once this one is proven out. GCP deployment
(phase 2) is done separately — see `gcp/startup-script.sh` and the AgentOS
project note in the Obsidian vault for the live infra.
