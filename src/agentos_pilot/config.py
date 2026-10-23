"""Declarative configuration loader for Gotthard control plane.

Loads gotthard.toml (or agentos.toml) and resolves secrets from environment variables.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class TierConfig:
    name: str
    description: str = ""
    type: str = "openai_compatible"  # "cli_or_api", "openai_compatible", "anthropic_or_tensorx"
    engine: Optional[str] = None     # "agy", "gemini_api", etc.
    model: str = ""
    api_base: Optional[str] = None
    api_key_env: Optional[str] = None
    temperature: float = 0.2
    max_tokens: int = 4096
    supports_tools: bool = True
    prompt_caching: bool = False
    enabled: bool = True
    fallback_tier: Optional[str] = None

    @property
    def api_key(self) -> Optional[str]:
        if self.api_key_env:
            return os.environ.get(self.api_key_env)
        return None


@dataclass
class BouncerConfig:
    enabled: bool = True
    max_identical_tool_calls: int = 3
    context_warning_percent: int = 75
    context_compaction_tier: str = "flash"
    heartbeat_timeout_seconds: int = 90
    on_loop_detected: str = "pause_and_notify"  # "kill" | "pause_and_notify" | "auto_compact"


@dataclass
class ContextConfig:
    layers: List[str] = field(default_factory=lambda: ["system", "pinned_spec", "injected_dynamic", "scratchpad_trace"])
    allow_runtime_injection: bool = True
    max_scratchpad_tokens: int = 16384


@dataclass
class RuntimeConfig:
    default_tier: str = "flash"
    max_task_duration_seconds: int = 900
    per_run_budget_usd: float = 0.50
    max_turns_per_run: int = 30
    worktree_root: Path = Path("/tmp/gotthard-worktrees")


@dataclass
class GotthardConfig:
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    bouncer: BouncerConfig = field(default_factory=BouncerConfig)
    context: ContextConfig = field(default_factory=ContextConfig)
    tiers: Dict[str, TierConfig] = field(default_factory=dict)
    routing_rules: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def default(cls) -> GotthardConfig:
        tiers = {
            "flash": TierConfig(
                name="flash",
                description="Antigravity CLI / Gemini Flash baseline",
                type="cli_or_api",
                engine="agy",
                model="gemini-3.8-flash",
                api_base="https://generativelanguage.googleapis.com/v1beta",
                api_key_env="GEMINI_API_KEY",
                temperature=0.2,
                supports_tools=True,
                fallback_tier="ifm",
            ),
            "ifm": TierConfig(
                name="ifm",
                description="Abu Dhabi Institute of Foundation Models (IFM)",
                type="openai_compatible",
                api_base="https://api.ifm.ai/v1",
                model="IFM/K2-Horizon-375B-A23B",
                api_key_env="IFM_API_KEY",
                temperature=0.3,
                max_tokens=8192,
                supports_tools=True,
                fallback_tier="grok",
            ),
            "grok": TierConfig(
                name="grok",
                description="xAI Grok API candidate",
                enabled=False,
                type="openai_compatible",
                api_base="https://api.x.ai/v1",
                model="grok-beta",
                api_key_env="XAI_API_KEY",
                temperature=0.2,
                fallback_tier="frontier",
            ),
            "frontier": TierConfig(
                name="frontier",
                description="Frontier Anthropic / TensorX fallback",
                type="anthropic_or_tensorx",
                api_base="https://api.tensorx.ai/v1",
                model="claude-3-7-sonnet",
                api_key_env="TENSORX_API_KEY",
                prompt_caching=True,
                temperature=0.1,
                fallback_tier=None,
            ),
        }
        routing_rules = {
            "test,lint,format,docs": "flash",
            "architecture,specification,review,adr": "ifm",
            "complex_refactor,debug_loop": "frontier",
        }
        return cls(tiers=tiers, routing_rules=routing_rules)

    @classmethod
    def from_toml_file(cls, path: Path) -> GotthardConfig:
        if not path.exists():
            return cls.default()
        with open(path, "rb") as f:
            data = tomllib.load(f)

        runtime_data = data.get("runtime", {})
        runtime = RuntimeConfig(
            default_tier=runtime_data.get("default_tier", "flash"),
            max_task_duration_seconds=runtime_data.get("max_task_duration_seconds", 900),
            per_run_budget_usd=float(runtime_data.get("per_run_budget_usd", 0.50)),
            max_turns_per_run=runtime_data.get("max_turns_per_run", 30),
            worktree_root=Path(runtime_data.get("worktree_root", "/tmp/gotthard-worktrees")),
        )

        bouncer_data = data.get("bouncer", {})
        bouncer = BouncerConfig(
            enabled=bouncer_data.get("enabled", True),
            max_identical_tool_calls=bouncer_data.get("max_identical_tool_calls", 3),
            context_warning_percent=bouncer_data.get("context_warning_percent", 75),
            context_compaction_tier=bouncer_data.get("context_compaction_tier", "flash"),
            heartbeat_timeout_seconds=bouncer_data.get("heartbeat_timeout_seconds", 90),
            on_loop_detected=bouncer_data.get("on_loop_detected", "pause_and_notify"),
        )

        ctx_data = data.get("context", {})
        context = ContextConfig(
            layers=ctx_data.get("layers", ["system", "pinned_spec", "injected_dynamic", "scratchpad_trace"]),
            allow_runtime_injection=ctx_data.get("allow_runtime_injection", True),
            max_scratchpad_tokens=ctx_data.get("max_scratchpad_tokens", 16384),
        )

        tiers: Dict[str, TierConfig] = {}
        for name, t_data in data.get("tiers", {}).items():
            tiers[name] = TierConfig(
                name=name,
                description=t_data.get("description", ""),
                type=t_data.get("type", "openai_compatible"),
                engine=t_data.get("engine"),
                model=t_data.get("model", ""),
                api_base=t_data.get("api_base"),
                api_key_env=t_data.get("api_key_env"),
                temperature=float(t_data.get("temperature", 0.2)),
                max_tokens=int(t_data.get("max_tokens", 4096)),
                supports_tools=t_data.get("supports_tools", True),
                prompt_caching=t_data.get("prompt_caching", False),
                enabled=t_data.get("enabled", True),
                fallback_tier=t_data.get("fallback_tier"),
            )

        # Merge with default if none provided
        if not tiers:
            tiers = cls.default().tiers

        routing_rules = data.get("routing_rules", cls.default().routing_rules)

        return cls(
            runtime=runtime,
            bouncer=bouncer,
            context=context,
            tiers=tiers,
            routing_rules=routing_rules,
        )

    def resolve_tier_for_task(self, task_description: str) -> TierConfig:
        """Resolve which model tier should handle the task based on rules or default."""
        desc_lower = task_description.lower()
        for keywords, tier_name in self.routing_rules.items():
            for kw in keywords.split(","):
                if kw.strip() and kw.strip() in desc_lower:
                    if tier_name in self.tiers and self.tiers[tier_name].enabled:
                        return self.tiers[tier_name]

        default_name = self.runtime.default_tier
        if default_name in self.tiers and self.tiers[default_name].enabled:
            return self.tiers[default_name]

        # First enabled tier
        for tier in self.tiers.values():
            if tier.enabled:
                return tier

        raise ValueError("No enabled tiers configured in Gotthard.")
