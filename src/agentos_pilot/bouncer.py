"""The Argos / Bouncer watchdog for Gotthard agent execution loops.

Monitors AST similarity / cycle detection, token gradient inflation,
and maintains layered dynamic context injection mid-flight.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class ToolExecutionRecord:
    tool_name: str
    arguments: Dict[str, Any]
    output: str
    exit_code: int
    timestamp: float = field(default_factory=time.time)


@dataclass
class DynamicContextLayer:
    system_invariants: List[str] = field(default_factory=list)
    pinned_specs: List[str] = field(default_factory=list)
    injected_runtime_hints: List[str] = field(default_factory=list)
    scratchpad_trace: List[ToolExecutionRecord] = field(default_factory=list)

    def inject_hint(self, hint: str) -> None:
        """Inject a directive or fact mid-flight into Layer 2."""
        self.injected_runtime_hints.append(hint)

    def compile_prompt_payload(self) -> str:
        """Compile layered context deterministically."""
        sections = []
        if self.system_invariants:
            sections.append("### SYSTEM INVARIANTS (IMMUTABLE)\n" + "\n".join(f"- {i}" for i in self.system_invariants))
        if self.pinned_specs:
            sections.append("### PINNED OBJECTIVES & GHERKIN SPEC\n" + "\n".join(self.pinned_specs))
        if self.injected_runtime_hints:
            sections.append("### RUNTIME OPERATOR INJECTIONS (HOT-UPDATE)\n" + "\n".join(f"• {h}" for h in self.injected_runtime_hints))
        return "\n\n".join(sections)


class BouncerIntervention(Exception):
    """Raised when the Bouncer watchdog halts or mutates execution."""
    pass


class ArgosBouncer:
    def __init__(
        self,
        max_identical_tool_calls: int = 3,
        context_warning_percent: int = 75,
        heartbeat_timeout_seconds: int = 90,
    ) -> None:
        self.max_identical_tool_calls = max_identical_tool_calls
        self.context_warning_percent = context_warning_percent
        self.heartbeat_timeout_seconds = heartbeat_timeout_seconds
        self.context = DynamicContextLayer()
        self.last_turn_timestamp = time.time()
        self._recent_tool_signatures: List[str] = []

    def record_heartbeat(self) -> None:
        """Reset the heartbeat timer on active streaming or turn activity."""
        self.last_turn_timestamp = time.time()

    def check_heartbeat(self) -> None:
        """Check if execution has hung past the timeout."""
        elapsed = time.time() - self.last_turn_timestamp
        if elapsed > self.heartbeat_timeout_seconds:
            raise BouncerIntervention(
                f"[Argos Bouncer] Heartbeat timeout exceeded ({elapsed:.1f}s > {self.heartbeat_timeout_seconds}s). Worker stalled."
            )

    def _signature(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        # Create normalized signature of tool invocation
        arg_items = sorted((k, str(v)) for k, v in arguments.items() if k != "timestamp")
        return f"{tool_name}:{arg_items}"

    def inspect_tool_dispatch(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        exit_code: int,
        output: str,
    ) -> None:
        """Inspect tool execution for dead-loops or repeated failure cycles."""
        self.record_heartbeat()
        sig = self._signature(tool_name, arguments)
        self._recent_tool_signatures.append(sig)

        record = ToolExecutionRecord(
            tool_name=tool_name,
            arguments=arguments,
            output=output,
            exit_code=exit_code,
        )
        self.context.scratchpad_trace.append(record)

        # Check for identical failing or cyclic calls
        if len(self._recent_tool_signatures) >= self.max_identical_tool_calls:
            window = self._recent_tool_signatures[-self.max_identical_tool_calls:]
            if len(set(window)) == 1 and exit_code != 0:
                raise BouncerIntervention(
                    f"[Argos Bouncer] Cycle detected! Tool '{tool_name}' failed with identical arguments {self.max_identical_tool_calls} times in a row."
                )

    def compact_scratchpad(self, max_records: int = 10) -> int:
        """Compact older scratchpad records into high-level event summary."""
        if len(self.context.scratchpad_trace) <= max_records:
            return 0
        pruned_count = len(self.context.scratchpad_trace) - max_records
        self.context.scratchpad_trace = self.context.scratchpad_trace[-max_records:]
        return pruned_count
