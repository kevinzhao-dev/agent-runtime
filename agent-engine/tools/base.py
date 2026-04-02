"""Base types for the tool system.

Defines the Tool protocol, ToolResult, ToolContext, and a BaseTool
convenience class.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from tools.permission import PermissionGate


@dataclass
class ToolResult:
    """Result of a tool execution."""
    content: str
    is_error: bool = False


@dataclass
class ToolContext:
    """Context passed to tool execution."""
    working_dir: str
    abort_signal: asyncio.Event | None = None
    permission_gate: PermissionGate | None = None


@runtime_checkable
class Tool(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def description(self) -> str: ...

    @property
    def input_schema(self) -> dict[str, Any]: ...

    async def execute(self, *, input: dict[str, Any], context: ToolContext) -> ToolResult: ...

    def is_read_only(self) -> bool: ...

    def is_destructive(self) -> bool: ...


class BaseTool:
    """Convenience base class implementing the Tool protocol."""

    @property
    def name(self) -> str:
        raise NotImplementedError

    @property
    def description(self) -> str:
        raise NotImplementedError

    @property
    def input_schema(self) -> dict[str, Any]:
        raise NotImplementedError

    async def execute(self, *, input: dict[str, Any], context: ToolContext) -> ToolResult:
        raise NotImplementedError

    def is_read_only(self) -> bool:
        return False

    def is_destructive(self) -> bool:
        return not self.is_read_only()

    def to_api_schema(self) -> dict[str, Any]:
        """Convert to Anthropic API tool definition format."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }
