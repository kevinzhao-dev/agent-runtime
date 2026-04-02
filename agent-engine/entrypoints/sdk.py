"""SDK entry point — importable AgentEngine class.

Usage:
    from entrypoints.sdk import AgentEngine

    engine = AgentEngine(working_dir="/path/to/project")

    async for event in engine.run("Build a FastAPI server"):
        if isinstance(event, TextEvent):
            print(event.text, end="")
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from typing import Any

from context.prompt import build_system_prompt
from engine.loop import ToolResult, query_loop
from engine.state import Event, TextEvent
from roles.config import DEFAULT_ROLE, RoleConfig
from tools.base import ToolContext
from tools.permission import PermissionDecision, PermissionGate, PermissionMode
from tools.registry import create_default_registry


class AgentEngine:
    """Main entry point for programmatic use of the agent engine.

    Args:
        role: Role configuration (default: DEFAULT_ROLE).
        model: Model override (uses role's model if None).
        working_dir: Working directory for tools.
        permission_mode: Permission mode for tool execution.
        max_turns: Override role's max_turns.
        permission_callback: Async callback for ASK permission decisions.
            Signature: (tool_name, tool_input) -> bool.
            If None, ASK decisions are denied.
    """

    def __init__(
        self,
        role: RoleConfig | None = None,
        model: str | None = None,
        working_dir: str | None = None,
        permission_mode: str | PermissionMode = "default",
        max_turns: int | None = None,
        permission_callback: Any = None,
    ):
        self.role = role or DEFAULT_ROLE
        if model:
            # Override model on role
            self.role = RoleConfig(
                name=self.role.name,
                system_prompt_sections=self.role.system_prompt_sections,
                allowed_tools=self.role.allowed_tools,
                read_only=self.role.read_only,
                can_spawn_agents=self.role.can_spawn_agents,
                max_turns=self.role.max_turns,
                model=model,
            )
        self.working_dir = working_dir or os.getcwd()
        self.permission_mode = PermissionMode(permission_mode)
        self.max_turns = max_turns
        self._permission_callback = permission_callback

    async def run(
        self,
        prompt: str,
        messages: list[dict[str, Any]] | None = None,
    ) -> AsyncGenerator[Event, None]:
        """Run the agent with the given prompt.

        Args:
            prompt: The user's task/question.
            messages: Optional pre-existing message history.

        Yields:
            Event objects (TextEvent, ToolUseEvent, etc.)
        """
        registry = create_default_registry()
        gate = PermissionGate(
            mode=self.permission_mode,
            ask_callback=self._permission_callback,
        )

        tool_schemas = registry.get_api_schemas(self.role)
        tool_ctx = ToolContext(
            working_dir=self.working_dir,
            permission_gate=gate,
        )

        async def executor(
            name: str, tid: str, inp: dict[str, Any]
        ) -> ToolResult:
            tool = registry.get(name)
            if tool is None:
                return ToolResult(content=f"Unknown tool: {name}", is_error=True)

            decision = gate.check(tool)
            if decision == PermissionDecision.DENY:
                return ToolResult(content=f"Permission denied: {name}", is_error=True)
            if decision == PermissionDecision.ASK:
                granted = await gate.request_permission(name, inp)
                if not granted:
                    return ToolResult(content=f"Denied: {name}", is_error=True)

            result = await tool.execute(input=inp, context=tool_ctx)
            return ToolResult(content=result.content, is_error=result.is_error)

        msgs = list(messages) if messages else []
        msgs.append({"role": "user", "content": prompt})

        async for event in query_loop(
            messages=msgs,
            role_config=self.role,
            tools=tool_schemas,
            tool_executor=executor,
            max_turns=self.max_turns or self.role.max_turns,
        ):
            yield event

    async def run_to_completion(self, prompt: str) -> str:
        """Convenience: run and collect all text into a single string."""
        parts: list[str] = []
        async for event in self.run(prompt):
            if isinstance(event, TextEvent):
                parts.append(event.text)
        return "".join(parts)
