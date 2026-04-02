"""Permission gate for tool execution.

Three modes: DEFAULT (read-only=allow, destructive=ask),
YOLO (everything=allow), STRICT (everything=ask).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Any

from tools.base import Tool


class PermissionMode(str, Enum):
    DEFAULT = "default"
    YOLO = "yolo"
    STRICT = "strict"


class PermissionDecision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


class PermissionGate:
    def __init__(
        self,
        mode: PermissionMode = PermissionMode.DEFAULT,
        ask_callback: Callable[[str, dict[str, Any]], Awaitable[bool]] | None = None,
    ):
        self.mode = mode
        self._ask_callback = ask_callback

    def check(self, tool: Tool) -> PermissionDecision:
        """Determine permission decision (no IO)."""
        if self.mode == PermissionMode.YOLO:
            return PermissionDecision.ALLOW
        if self.mode == PermissionMode.STRICT:
            return PermissionDecision.ASK
        # DEFAULT mode
        if tool.is_read_only():
            return PermissionDecision.ALLOW
        return PermissionDecision.ASK

    async def request_permission(
        self, tool_name: str, tool_input: dict[str, Any]
    ) -> bool:
        """Ask the user for permission. Returns True if granted."""
        if self._ask_callback:
            return await self._ask_callback(tool_name, tool_input)
        return False
