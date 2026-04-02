"""Agent tool — spawn sub-engine instances for task delegation.

The coordinator uses this tool to delegate sub-tasks to implementer
or verifier agents. Each sub-agent gets its own LoopState, abort signal,
and role-specific tool set.
"""

from __future__ import annotations

import asyncio
from typing import Any

from context.prompt import build_system_prompt
from engine.state import DoneEvent, ErrorEvent, TextEvent
from roles.config import ROLE_REGISTRY, RoleConfig
from tools.base import BaseTool, ToolContext, ToolResult


class AgentTool(BaseTool):
    @property
    def name(self) -> str:
        return "agent_tool"

    @property
    def description(self) -> str:
        return (
            "Delegate a task to a sub-agent with a specific role. "
            "The sub-agent runs independently and returns its result. "
            "Available roles: implementer, verifier."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "The task description for the sub-agent",
                },
                "role": {
                    "type": "string",
                    "enum": ["implementer", "verifier"],
                    "description": "The role for the sub-agent",
                },
            },
            "required": ["task", "role"],
        }

    def is_read_only(self) -> bool:
        return False

    def is_destructive(self) -> bool:
        return False  # Sub-agent's own tools handle permissions

    async def execute(self, *, input: dict[str, Any], context: ToolContext) -> ToolResult:
        # Lazy import to avoid circular dependency
        from engine.loop import query_loop
        from tools.registry import ToolRegistry, create_default_registry

        task = input["task"]
        role_name = input["role"]

        role_config = ROLE_REGISTRY.get(role_name)
        if role_config is None:
            return ToolResult(content=f"Unknown role: {role_name}", is_error=True)

        # Build sub-agent's tool set
        registry = create_default_registry()
        tool_schemas = registry.get_api_schemas(role_config)

        # Build sub-agent's tool executor (reuses parent's permission gate)
        sub_context = ToolContext(
            working_dir=context.working_dir,
            abort_signal=None,  # child abort set below
            permission_gate=context.permission_gate,
        )

        async def sub_executor(
            tool_name: str, tool_id: str, tool_input: dict[str, Any]
        ) -> ToolResult:
            from tools.permission import PermissionDecision

            tool = registry.get(tool_name)
            if tool is None:
                return ToolResult(content=f"Unknown tool: {tool_name}", is_error=True)

            # Permission check
            if context.permission_gate:
                decision = context.permission_gate.check(tool)
                if decision == PermissionDecision.DENY:
                    return ToolResult(content=f"Permission denied: {tool_name}", is_error=True)
                if decision == PermissionDecision.ASK:
                    granted = await context.permission_gate.request_permission(tool_name, tool_input)
                    if not granted:
                        return ToolResult(content=f"User denied: {tool_name}", is_error=True)

            result = await tool.execute(input=tool_input, context=sub_context)
            return ToolResult(content=result.content, is_error=result.is_error)

        # Create child abort signal linked to parent
        child_abort = asyncio.Event()
        if context.abort_signal is not None:
            _link_abort(context.abort_signal, child_abort)

        # Run sub-agent
        sub_messages = [{"role": "user", "content": task}]
        collected_text: list[str] = []

        try:
            async for event in query_loop(
                messages=sub_messages,
                role_config=role_config,
                tools=tool_schemas,
                tool_executor=sub_executor,
                abort_signal=child_abort,
                max_turns=role_config.max_turns,
            ):
                if isinstance(event, TextEvent):
                    collected_text.append(event.text)
                elif isinstance(event, ErrorEvent):
                    collected_text.append(f"\n[Sub-agent error: {event.error}]")
                elif isinstance(event, DoneEvent):
                    pass  # normal completion
        except Exception as e:
            return ToolResult(content=f"Sub-agent failed: {e}", is_error=True)

        result_text = "".join(collected_text)
        if not result_text:
            result_text = "[Sub-agent produced no output]"

        return ToolResult(content=result_text)


def _link_abort(parent: asyncio.Event, child: asyncio.Event) -> None:
    """When parent abort fires, propagate to child."""
    async def _propagate():
        await parent.wait()
        child.set()
    asyncio.create_task(_propagate())
