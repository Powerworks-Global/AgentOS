"""Tier-dispatch runners for the Gotthard control plane (ADR-0027 ladder).

Each rung in gotthard.toml names a `type` (and, for the cli_or_api rung, an
`engine`) describing how to actually reach that model. This module is the
thin, dependency-free layer that turns a resolved TierConfig into something
that can produce text: either by shelling out to a local CLI (the `agy`
engine, i.e. Antigravity CLI / Gemini Flash) or by POSTing to an
OpenAI-compatible chat/completions endpoint with stdlib `urllib` only (no
new pip dependency for something this small).

Deliberately minimal: `Runner.run(model, prompt) -> text` is the whole
interface. Nothing here drives tool use, git, or multi-turn conversation -
that remains the Claude Agent SDK's job in pipeline.py. This is only used
for rungs whose requirements are actually satisfiable (binary present for
`agy`, api_key_env set for `openai_compatible`); pipeline.py decides whether
to dispatch here or fall back to the existing SDK path.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Protocol

from agentos_pilot.config import TierConfig


class RunnerError(RuntimeError):
    """Raised when a runner cannot execute, or the backend call fails."""


class Runner(Protocol):
    """Minimal interface every concrete tier runner implements."""

    def is_available(self) -> bool:
        """Whether this runner's requirements are currently satisfiable."""
        ...

    def run(self, model: str, prompt: str) -> str:
        """Run `prompt` against `model` and return the text response."""
        ...


def _agy_binary() -> str | None:
    """Locate the `agy` CLI: PATH first, then the typical install location."""
    found = shutil.which("agy")
    if found:
        return found
    typical = Path.home() / ".local" / "bin" / "agy"
    if typical.exists():
        return str(typical)
    return None


class AgyCliRunner:
    """Runner for `cli_or_api` tiers whose engine is `agy` (Antigravity CLI).

    Shells out to: agy --print --model <model> <prompt>
    """

    def __init__(self, binary: str | None = None) -> None:
        self._binary = binary if binary is not None else _agy_binary()

    def is_available(self) -> bool:
        return self._binary is not None

    def run(self, model: str, prompt: str) -> str:
        if not self._binary:
            raise RunnerError(
                "agy binary not found on PATH (tried ~/.local/bin/agy)"
            )
        result = subprocess.run(
            [self._binary, "--print", "--model", model, prompt],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RunnerError(
                f"agy exited {result.returncode}: {result.stderr.strip()}"
            )
        return result.stdout


class OpenAiCompatibleRunner:
    """Runner for `openai_compatible` tiers (e.g. IFM, Grok).

    POSTs to <api_base>/chat/completions with the configured api_key_env's
    value as a Bearer token, using stdlib urllib only. 60s timeout; raises
    RunnerError with a clear message on any non-2xx response.
    """

    def __init__(self, api_base: str, api_key_env: str, timeout: float = 60.0) -> None:
        self.api_base = api_base.rstrip("/")
        self.api_key_env = api_key_env
        self.timeout = timeout

    def is_available(self) -> bool:
        return bool(self.api_key_env and os.environ.get(self.api_key_env))

    def run(self, model: str, prompt: str) -> str:
        api_key = os.environ.get(self.api_key_env) if self.api_key_env else None
        if not api_key:
            raise RunnerError(f"{self.api_key_env} is not set in the environment")

        url = f"{self.api_base}/chat/completions"
        payload = json.dumps(
            {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                status = getattr(response, "status", None) or response.getcode()
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise RunnerError(f"{url} returned HTTP {e.code}: {body}") from e
        except urllib.error.URLError as e:
            raise RunnerError(f"request to {url} failed: {e}") from e

        if not (200 <= status < 300):
            raise RunnerError(f"{url} returned HTTP {status}: {body}")

        try:
            data = json.loads(body)
            return data["choices"][0]["message"]["content"]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
            raise RunnerError(f"unexpected response shape from {url}: {body}") from e


def build_runner_for_tier(tier: TierConfig) -> tuple[Runner | None, str]:
    """Build the concrete runner for a resolved tier.

    Returns (runner_or_none, runner_type_label). runner is None when the
    tier's `type` isn't one Gotthard knows how to dispatch to yet (e.g.
    `anthropic_or_tensorx` - rung 4 stays on the existing Claude SDK path by
    design, not because of a missing credential).
    """

    if tier.type == "cli_or_api" and tier.engine == "agy":
        return AgyCliRunner(), "agy_cli"
    if tier.type == "openai_compatible":
        if not tier.api_base or not tier.api_key_env:
            return None, "openai_compatible"
        return (
            OpenAiCompatibleRunner(api_base=tier.api_base, api_key_env=tier.api_key_env),
            "openai_compatible",
        )
    return None, tier.type


def runner_requirements_met(tier: TierConfig, runner: Runner | None) -> tuple[bool, str]:
    """Check whether a resolved tier's runner requirements are satisfiable now.

    Never raises: this is consulted on every run to decide dispatch-vs-fallback,
    and an unprovisioned rung (missing binary or API key) must never fail the
    task - it should just log why and fall back to the existing Claude SDK path.
    """

    if runner is None:
        return (
            False,
            f"tier {tier.name!r} (type={tier.type}) has no dispatchable runner implemented",
        )
    if runner.is_available():
        return True, f"tier {tier.name!r} runner requirements satisfied"

    if isinstance(runner, AgyCliRunner):
        return (
            False,
            f"tier {tier.name!r} requires the `agy` binary on PATH "
            f"(typical: ~/.local/bin/agy); not found",
        )
    if isinstance(runner, OpenAiCompatibleRunner):
        return (
            False,
            f"tier {tier.name!r} requires {tier.api_key_env} to be set in the "
            f"environment; not found",
        )
    return False, f"tier {tier.name!r} requirements not met"
