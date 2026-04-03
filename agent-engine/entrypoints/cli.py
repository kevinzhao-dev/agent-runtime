"""Interactive REPL for the agent engine.

Consumes the query_loop async generator and displays events via Rich.
Supports persistent command history and modular slash commands.
"""

from __future__ import annotations

import asyncio
import os
import readline
from pathlib import Path
from typing import Any

from commands import CommandContext, create_default_registry as create_command_registry
from engine.loop import ToolResult, query_loop
from engine.session_log import SessionLog
from engine.state import (
    CompactEvent,
    DoneEvent,
    ErrorEvent,
    TextEvent,
    ToolResultEvent,
    ToolUseEvent,
)
from entrypoints.display import DisplayRenderer
from roles.config import DEFAULT_ROLE, RoleConfig
from tools.permission import PermissionDecision, PermissionGate, PermissionMode
from tools.registry import ToolRegistry, create_default_registry as create_tool_registry

# ---------------------------------------------------------------------------
# Readline history
# ---------------------------------------------------------------------------

_HISTORY_DIR = Path.home() / ".agent-engine"
_HISTORY_FILE = _HISTORY_DIR / "history"


def _setup_history() -> None:
    _HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    try:
        readline.read_history_file(_HISTORY_FILE)
    except FileNotFoundError:
        pass
    readline.set_history_length(500)


def _save_history() -> None:
    try:
        readline.write_history_file(_HISTORY_FILE)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Tool executor & permission callback
# ---------------------------------------------------------------------------


def _build_permission_callback(renderer: DisplayRenderer):
    async def callback(tool_name: str, tool_input: dict[str, Any]) -> bool:
        return await asyncio.to_thread(
            renderer.render_permission_prompt, tool_name, tool_input
        )
    return callback


def _build_tool_executor(
    registry: ToolRegistry,
    permission_gate: PermissionGate,
    working_dir: str,
):
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

        decision = permission_gate.check(tool)
        if decision == PermissionDecision.DENY:
            return ToolResult(content=f"Permission denied: {tool_name}", is_error=True)
        if decision == PermissionDecision.ASK:
            granted = await permission_gate.request_permission(tool_name, tool_input)
            if not granted:
                return ToolResult(content=f"User denied: {tool_name}", is_error=True)

        result = await tool.execute(input=tool_input, context=context)
        return ToolResult(content=result.content, is_error=result.is_error)

    return executor


# ---------------------------------------------------------------------------
# Event stream with session logging
# ---------------------------------------------------------------------------


async def _render_and_log(
    renderer: DisplayRenderer,
    events,
    session_log: SessionLog,
) -> DoneEvent | None:
    """Wrap render_event_stream to also log events to session file."""
    async def logging_events():
        async for event in events:
            match event:
                case TextEvent(text=text):
                    session_log.log_text(text)
                case ToolUseEvent(tool_name=name, tool_id=tid, input=inp):
                    session_log.log_tool_use(name, tid, inp)
                case ToolResultEvent(tool_id=tid, content=content, is_error=err):
                    session_log.log_tool_result(tid, content, err)
                case ErrorEvent(error=err, recoverable=r):
                    session_log.log_error(err, r)
                case CompactEvent(tokens_before=b, tokens_after=a):
                    session_log.log_compact(b, a)
                case DoneEvent(reason=reason, turn_count=turns):
                    session_log.log_done(reason, turns)
            yield event

    return await renderer.render_event_stream(logging_events())


# ---------------------------------------------------------------------------
# Main REPL
# ---------------------------------------------------------------------------


async def run_repl(
    role_config: RoleConfig = DEFAULT_ROLE,
    permission_mode: PermissionMode = PermissionMode.DEFAULT,
    working_dir: str | None = None,
    client: Any | None = None,
) -> None:
    """Run an interactive REPL session."""
    _setup_history()

    renderer = DisplayRenderer()
    wd = working_dir or os.getcwd()
    session_log = SessionLog(working_dir=wd)
    cmd_registry = create_command_registry()

    mode_label = " [DRY RUN]" if client is not None else ""
    renderer.render_welcome("v0.1.0", mode_label)

    tool_registry = create_tool_registry()
    permission_gate = PermissionGate(
        mode=permission_mode,
        ask_callback=_build_permission_callback(renderer),
    )

    tool_schemas = tool_registry.get_api_schemas(role_config)
    tool_executor = _build_tool_executor(tool_registry, permission_gate, wd)

    messages: list[dict] = []

    try:
        while True:
            try:
                user_input = await asyncio.to_thread(renderer.get_user_input)
            except (EOFError, KeyboardInterrupt):
                renderer.render_goodbye()
                break

            stripped = user_input.strip()
            if not stripped:
                continue
            if stripped.lower() in ("exit", "quit"):
                renderer.render_goodbye()
                break

            # Slash commands
            if stripped.startswith("/"):
                cmd_ctx = CommandContext(
                    messages=messages,
                    session_log=session_log,
                    working_dir=wd,
                )
                result = cmd_registry.execute(stripped, cmd_ctx)
                if result is not None:
                    if result.output:
                        renderer.console.print()
                        renderer.console.print(result.output)
                        renderer.console.print()
                    continue
                renderer.console.print(f"  [dim]Unknown command: {stripped.split()[0]}. Type /help[/dim]")
                continue

            session_log.log_user_input(stripped)
            messages.append({"role": "user", "content": stripped})

            events = query_loop(
                messages=messages,
                role_config=role_config,
                tools=tool_schemas,
                tool_executor=tool_executor,
                client=client,
            )

            done_event = await _render_and_log(renderer, events, session_log)
            if isinstance(done_event, DoneEvent) and done_event.messages:
                messages = list(done_event.messages)
    finally:
        _save_history()
        session_log.close()
