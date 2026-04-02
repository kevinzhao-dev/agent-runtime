"""Interactive REPL for the agent engine.

Consumes the query_loop async generator and displays events to the user.
"""

from __future__ import annotations

import asyncio

from engine.loop import query_loop
from engine.state import (
    DoneEvent,
    ErrorEvent,
    TextEvent,
    ToolResultEvent,
    ToolUseEvent,
)
from roles.config import DEFAULT_ROLE, RoleConfig


async def run_repl(role_config: RoleConfig = DEFAULT_ROLE) -> None:
    """Run an interactive REPL session."""
    print("Agent Engine v0.1.0 (type 'exit' to quit)\n")

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

        async for event in query_loop(messages=messages, role_config=role_config):
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
