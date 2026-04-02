"""Tool registry — registration and lookup.

Provides role-based filtering so each agent role only sees its allowed tools.
"""

from __future__ import annotations

from typing import Any

from roles.config import RoleConfig
from tools.base import BaseTool, Tool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def get_tools_for_role(self, role_config: RoleConfig) -> list[Tool]:
        if role_config.allowed_tools is None:
            return list(self._tools.values())
        return [
            t for t in self._tools.values()
            if t.name in role_config.allowed_tools
        ]

    def get_api_schemas(self, role_config: RoleConfig) -> list[dict[str, Any]]:
        tools = self.get_tools_for_role(role_config)
        return [
            t.to_api_schema() if isinstance(t, BaseTool) else {
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema,
            }
            for t in tools
        ]


def create_default_registry() -> ToolRegistry:
    """Create a registry with all built-in tools."""
    from tools.agent_tool import AgentTool
    from tools.bash import BashTool
    from tools.edit import EditTool
    from tools.grep import GrepTool
    from tools.read_file import ReadFileTool
    from tools.write_file import WriteFileTool

    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(GrepTool())
    registry.register(WriteFileTool())
    registry.register(EditTool())
    registry.register(BashTool())
    registry.register(AgentTool())
    return registry
