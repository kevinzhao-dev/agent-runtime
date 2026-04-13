"""Tool system foundation: ToolSpec, ToolRegistry, LedgerEntry, permission model.

Tools are managed syscalls. Every tool call passes through a registry,
executes under policy, and lands in a ledger.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Literal


# ── Tool Specification ────────────────────────────────────────────────────

@dataclass(slots=True)
class ToolSpec:
    """Defines a tool's metadata, schema, and executor."""
    name: str
    description: str
    input_schema: dict[str, Any]
    executor: Callable[[dict[str, Any]], str]
    risk: Literal["low", "high"] = "low"
    side_effecting: bool = False


# ── Ledger Entry ──────────────────────────────────────────────────────────

@dataclass(slots=True)
class LedgerEntry:
    """Audit record for every tool execution."""
    tool_name: str
    tool_input: dict[str, Any]
    status: Literal["ok", "error", "interrupted"] = "ok"
    started_at: float = 0.0
    ended_at: float | None = None
    summary: str = ""
    error: str = ""


# ── Tool Registry ─────────────────────────────────────────────────────────

class ToolRegistry:
    """Central registry for tool lookup, schema export, and execution."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def list_names(self) -> list[str]:
        return list(self._tools.keys())

    def get_schemas(self) -> list[dict[str, Any]]:
        """Export tool schemas for the model API (Anthropic format)."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema,
            }
            for t in self._tools.values()
        ]

    def execute(
        self,
        name: str,
        tool_input: dict[str, Any],
        *,
        max_output: int = 32_000,
    ) -> tuple[str, LedgerEntry]:
        """Execute a tool and return (output, ledger_entry).

        Truncates output if it exceeds max_output characters.
        """
        spec = self._tools.get(name)
        if spec is None:
            entry = LedgerEntry(
                tool_name=name,
                tool_input=tool_input,
                status="error",
                started_at=time.time(),
                ended_at=time.time(),
                error=f"Unknown tool: {name}",
            )
            return f"Error: Unknown tool '{name}'", entry

        entry = LedgerEntry(
            tool_name=name,
            tool_input=tool_input,
            started_at=time.time(),
        )

        try:
            output = spec.executor(tool_input)
            entry.status = "ok"
            entry.summary = output[:200]
        except Exception as e:
            output = f"Error: {e}"
            entry.status = "error"
            entry.error = str(e)

        entry.ended_at = time.time()

        # Truncate oversized output
        if len(output) > max_output:
            half = max_output // 2
            quarter = max_output // 4
            output = (
                output[:half]
                + f"\n\n[... {len(output) - half - quarter} chars truncated ...]\n\n"
                + output[-quarter:]
            )

        return output, entry

    def is_high_risk(self, name: str) -> bool:
        spec = self._tools.get(name)
        return spec is not None and spec.risk == "high"


# Global registry instance
registry = ToolRegistry()
