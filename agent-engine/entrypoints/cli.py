"""Interactive REPL for the agent engine.

Consumes the query_loop async generator and displays events to the user.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from engine.loop import ToolResult, query_loop
from engine.state import (
    DoneEvent,
    ErrorEvent,
    TextEvent,
    ToolResultEvent,
    ToolUseEvent,
)
from roles.config import DEFAULT_ROLE, RoleConfig
from tools.permission import PermissionDecision, PermissionGate, PermissionMode
from tools.registry import ToolRegistry, create_default_registry


async def _cli_ask_callback(tool_name: str, tool_input: dict[str, Any]) -> bool:
    """Ask user for permission in the terminal."""
    preview = str(tool_input)
    if len(preview) > 200:
        preview = preview[:200] + "..."
    answer = await asyncio.to_thread(
        input, f"\n[Permission] Allow {tool_name}({preview})? [y/N] "
    )
    return answer.strip().lower() in ("y", "yes")


def _build_tool_executor(
    registry: ToolRegistry,
    permission_gate: PermissionGate,
    working_dir: str,
):
    """Build a tool executor callback for the query loop."""
    from tools.base import ToolContext

    context = ToolContext(
        working_dir=working_dir,
        permission_gate=permission_gate,
    )

    async def executor(
        tool_name: str, tool_id: str, tool_input: dict[str, Any]
    ) -> ToolResult:
        tool = registry.get(tool_name)
        if tool is None:
            return ToolResult(content=f"Unknown tool: {tool_name}", is_error=True)

        # Permission check
        decision = permission_gate.check(tool)
        if decision == PermissionDecision.DENY:
            return ToolResult(content=f"Permission denied: {tool_name}", is_error=True)
        if decision == PermissionDecision.ASK:
            granted = await permission_gate.request_permission(tool_name, tool_input)
            if not granted:
                return ToolResult(content=f"User denied: {tool_name}", is_error=True)

        # Execute
        result = await tool.execute(input=tool_input, context=context)
        return ToolResult(content=result.content, is_error=result.is_error)

    return executor


async def run_repl(
    role_config: RoleConfig = DEFAULT_ROLE,
    permission_mode: PermissionMode = PermissionMode.DEFAULT,
    working_dir: str | None = None,
    client: Any | None = None,
) -> None:
    """Run an interactive REPL session.

    Args:
        client: Optional Anthropic client override. Pass a DryRunClient for testing.
    """
    mode_label = " [DRY RUN]" if client is not None else ""
    print(f"Agent Engine v0.1.0{mode_label} (type 'exit' to quit)\n")

    wd = working_dir or os.getcwd()
    registry = create_default_registry()
    permission_gate = PermissionGate(
        mode=permission_mode,
        ask_callback=_cli_ask_callback,
    )

    tool_schemas = registry.get_api_schemas(role_config)
    tool_executor = _build_tool_executor(registry, permission_gate, wd)
    tool_names = [t["name"] for t in tool_schemas]

    messages: list[dict] = []

    while True:
        try:
            user_input = await asyncio.to_thread(input, "> ")
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        stripped = user_input.strip()
        if not stripped:
            continue
        if stripped.lower() in ("exit", "quit"):
            print("Goodbye!")
            break

        messages.append({"role": "user", "content": stripped})

        async for event in query_loop(
            messages=messages,
            role_config=role_config,
            tools=tool_schemas,
            tool_executor=tool_executor,
            client=client,
        ):
            match event:
                case TextEvent(text=text):
                    print(text, end="", flush=True)
                case ToolUseEvent(tool_name=name, input=inp):
                    print(f"\n[Tool: {name}({_truncate(str(inp), 120)})]")
                case ToolResultEvent(content=content, is_error=is_error):
                    prefix = "[Error]" if is_error else "[Result]"
                    print(f"{prefix} {_truncate(content, 200)}")
                case ErrorEvent(error=err):
                    print(f"\n[Error: {err}]")
                case DoneEvent(reason=reason, turn_count=turns, messages=final_msgs):
                    print(f"\n--- ({reason}, {turns} turns) ---\n")
                    if final_msgs:
                        messages = list(final_msgs)


def _truncate(s: str, max_len: int) -> str:
    return s[:max_len] + "..." if len(s) > max_len else s
