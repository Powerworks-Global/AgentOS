"""Telegram notification channel — the swap-in for the design note's
originally-planned Discord integration (Phase 3).

Scoped deliberately narrow for this pass: post-run notification only
(success/failure/cost/denial-count), not full interactive approve/resume.
A denied tool call is still final for the run, exactly as before this
module existed — Telegram makes a human aware of the outcome quickly, it
does not yet let them approve a specific denied action and have the run
continue from there. That's the real remaining Phase 3b gap, named here
rather than silently assumed to be solved.

Uses stdlib `urllib.request` only — no new dependency, matching the rest
of this pilot's zero-extra-deps posture (`pyproject.toml` names exactly
one dependency: `claude-agent-sdk`). Telegram's Bot API is a plain HTTPS
POST; nothing here needs more than that.

Configured via TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID. Both optional —
notify_run_result() is a silent no-op if either is unset, so Telegram is
strictly additive and never blocks a run that doesn't have it configured.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

from agentos_pilot.metrics import RunMetrics

TELEGRAM_API_BASE = "https://api.telegram.org"


@dataclass(frozen=True)
class TelegramConfig:
    bot_token: str
    chat_id: str

    @staticmethod
    def from_env() -> "TelegramConfig | None":
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID")
        if not token or not chat_id:
            return None
        return TelegramConfig(bot_token=token, chat_id=chat_id)


def send_message(config: TelegramConfig, text: str) -> bool:
    """POSTs to Telegram's sendMessage endpoint. Never raises — a
    notification failure (bad token, network blip, Telegram outage) must
    not take down a pipeline run that otherwise succeeded or failed on its
    own merits, same "fail soft on the non-essential path" posture as the
    rest of this pilot. Returns whether it actually sent."""
    url = f"{TELEGRAM_API_BASE}/bot{config.bot_token}/sendMessage"
    body = json.dumps({"chat_id": config.chat_id, "text": text}).encode()
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status == 200
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        print(f"[notify] Telegram send failed (non-fatal): {e}")
        return False


def format_run_result(metrics: RunMetrics) -> str:
    status = "SUCCESS" if metrics.success else "FAILED"
    lines = [f"[AgentOS] {status}: {metrics.task}"]
    if metrics.task_id:
        lines.append(f"task_id: {metrics.task_id}")
    lines.append(f"branch: {metrics.branch_name}")
    if metrics.total_cost_usd is not None:
        lines.append(f"cost: ${metrics.total_cost_usd:.4f}  turns: {metrics.num_turns}")
    if metrics.permission_denials:
        lines.append(f"permission denials: {metrics.permission_denials}")
    if metrics.assistant_error:
        lines.append(f"assistant error: {metrics.assistant_error}")
    if metrics.sdk_error:
        lines.append(f"sdk error: {metrics.sdk_error}")
    return "\n".join(lines)


def notify_run_result(metrics: RunMetrics, config: TelegramConfig | None = None) -> bool:
    """Sends a post-run summary. No-op (returns False) if Telegram isn't
    configured — this must never be the reason a run can't complete."""
    resolved = config if config is not None else TelegramConfig.from_env()
    if resolved is None:
        return False
    return send_message(resolved, format_run_result(metrics))
