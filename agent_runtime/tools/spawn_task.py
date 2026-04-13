"""spawn_task tool — spawn a child agent with role-scoped tools.

This tool is special: it returns an AsyncGenerator (not a str).
The query loop detects this and streams child events to the caller.

Registration happens via `create_spawn_executor()` which returns a
tool_executor function that the loop can use. The tool schema is
registered in the global registry for model discovery.
"""
from __future__ import annotations

from typing import Any, AsyncGenerator

from agent_runtime.engine.models import Event, SessionState, TurnConfig
from agent_runtime.tools.base import ToolSpec, registry


# Register schema so the model knows spawn_task exists
registry.register(ToolSpec(
    name="spawn_task",
    description=(
        "Spawn a sub-agent to handle a task. The agent runs with role-scoped "
        "tools and returns its result. Roles: research (read-only), "
        "implementation (can write), verification (read-only, for review)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Task description for the sub-agent",
            },
            "role": {
                "type": "string",
                "enum": ["research", "implementation", "verification", "synthesis"],
                "description": "Role for the sub-agent",
            },
        },
        "required": ["prompt", "role"],
    },
    executor=lambda params: "[spawn_task requires async executor — use create_spawn_executor()]",
    risk="low",
))


def create_spawn_executor(
    manager: Any | None = None,
    parent_depth: int = 0,
    parent_role: str | None = None,
    system_prompt: str = "",
) -> Any:
    """Create a tool_executor function that handles spawn_task.

    Returns a callable compatible with run_query_loop's tool_executor parameter.
    For non-spawn tools, falls back to the global registry.
    """
    from agent_runtime.agents.config import AgentConfig as _AgentConfig
    from agent_runtime.agents.manager import AgentManager as _AgentManager
    mgr = manager or _AgentManager()

    async def executor(
        name: str,
        tool_input: dict[str, Any],
        state: SessionState,
        config: TurnConfig,
    ) -> str | AsyncGenerator[Event, None]:
        if name == "spawn_task":
            wait = tool_input.get("wait", True)
            child_config = _AgentConfig(
                role=tool_input["role"],
                model_name=config.model_name,
                parent_id=state.session_id,
                depth=parent_depth + 1,
            )
            if wait:
                # Streaming spawn — yields ChildEvents
                return mgr.spawn(
                    tool_input["prompt"],
                    child_config,
                    system_prompt=system_prompt,
                )
            else:
                # Background spawn — returns immediately
                agent_id = await mgr.spawn_background(
                    tool_input["prompt"],
                    child_config,
                    system_prompt=system_prompt,
                )
                return f"Agent {agent_id} spawned in background."

        if name == "check_agent":
            import json
            return json.dumps(mgr.check_agent(tool_input["agent_id"]))

        if name == "abort_agent":
            return mgr.abort_agent(tool_input["agent_id"])

        if name == "list_agents":
            import json
            return json.dumps(mgr.list_agents(), indent=2)

        # Fall back to registry for other tools
        output, entry = registry.execute(name, tool_input)
        state.ledger.append(entry)
        return output

    return executor, mgr
