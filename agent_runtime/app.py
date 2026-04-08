"""CLI entrypoint — thin REPL that drives the query loop.

This is the entrypoint, not business logic. Keep it minimal.
"""
from __future__ import annotations

import asyncio
import sys
from dataclasses import asdict

from agent_runtime.compaction import compact
from agent_runtime.context import build_task_context
from agent_runtime.memory import load_memory_index, load_rules
from agent_runtime.models import SessionState, TurnConfig
from agent_runtime.prompt import build_prompt
from agent_runtime.query_loop import run_query_loop
from agent_runtime.storage import save_session
from agent_runtime.tools import registry


def _build_system_prompt(state: SessionState, config: TurnConfig) -> str:
    """Assemble the full system prompt from all layers."""
    rules = load_rules("AGENT.md", "PROJECT.md")
    memory_index = load_memory_index("MEMORY.md")
    task_context = build_task_context(state, rules_content=rules, memory_index=memory_index)

    # Format tool descriptions
    tool_descs = "\n".join(
        f"- **{s['name']}**: {s['description']}"
        for s in registry.get_schemas()
    )

    prompt_config = build_prompt(
        project_rules=rules,
        runtime_mode="",
        task_context=task_context,
        tool_descriptions=tool_descs,
    )
    return prompt_config.system_prompt


def _permission_prompt(tool_name: str, tool_input: dict) -> bool:
    """Interactive permission prompt for high-risk tools."""
    if not registry.is_high_risk(tool_name):
        return True
    print(f"\n[Permission Required] Tool: {tool_name}")
    print(f"  Input: {tool_input}")
    answer = input("  Allow? (y/n): ").strip().lower()
    return answer in ("y", "yes")


async def _run_session(config: TurnConfig) -> None:
    """Run an interactive REPL session."""
    state = SessionState()
    print(f"Agent Runtime v0.1.0 | Session: {state.session_id}")
    print(f"Model: {config.model_name} | Max turns: {config.max_turns}")
    print("Type 'quit' to exit.\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit"):
            break

        system_prompt = _build_system_prompt(state, config)

        async for event in run_query_loop(
            user_input, state, config,
            system_prompt=system_prompt,
            permission_callback=_permission_prompt,
            compact_handler=compact,
        ):
            if event.type == "text_delta":
                print(event.text, end="", flush=True)
            elif event.type == "thinking":
                pass  # silent
            elif event.type == "tool_call":
                print(f"\n[Tool: {event.tool_name}]")
            elif event.type == "tool_result":
                status = "ok" if event.status == "ok" else f"ERROR: {event.status}"
                print(f"  → {status}")
            elif event.type == "recovery":
                print(f"\n[Recovery: {event.reason}] {event.detail}")
            elif event.type == "final":
                if not event.text.strip():
                    pass  # already streamed
                print()  # newline after response

        # Save after each turn
        save_session(state)

    # Final save
    save_session(state)
    print(f"\nSession saved: {state.session_id}")
    print(f"Tokens: {state.total_input_tokens} in / {state.total_output_tokens} out")


def main() -> None:
    """Entry point."""
    model = "claude-sonnet-4-6"
    if len(sys.argv) > 1:
        model = sys.argv[1]

    config = TurnConfig(model_name=model)

    try:
        asyncio.run(_run_session(config))
    except KeyboardInterrupt:
        print("\nAborted.")


if __name__ == "__main__":
    main()
