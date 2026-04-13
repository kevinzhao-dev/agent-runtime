"""Agent lifecycle tools — check, abort, list background agents.

These tools let the model manage background agents spawned via spawn_task.
They require an AgentManager instance injected via create_agent_ops_executor().
"""
from __future__ import annotations

import json
from typing import Any

from agent_runtime.tools.base import ToolSpec, registry


registry.register(ToolSpec(
    name="check_agent",
    description="Check the status of a background agent. Returns status and output if completed.",
    input_schema={
        "type": "object",
        "properties": {
            "agent_id": {"type": "string", "description": "ID of the agent to check"},
        },
        "required": ["agent_id"],
    },
    executor=lambda params: "[check_agent requires agent manager — use create_spawn_executor()]",
    risk="low",
))

registry.register(ToolSpec(
    name="abort_agent",
    description="Request cooperative cancellation of a running background agent.",
    input_schema={
        "type": "object",
        "properties": {
            "agent_id": {"type": "string", "description": "ID of the agent to abort"},
        },
        "required": ["agent_id"],
    },
    executor=lambda params: "[abort_agent requires agent manager]",
    risk="low",
))

registry.register(ToolSpec(
    name="list_agents",
    description="List all tracked agents and their current status.",
    input_schema={
        "type": "object",
        "properties": {},
    },
    executor=lambda params: "[list_agents requires agent manager]",
    risk="low",
))
