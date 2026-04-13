"""Agent configuration and result types."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from agent_runtime.roles.policy import RoleName

MAX_DEPTH = 3


@dataclass(frozen=True, slots=True)
class AgentConfig:
    """Configuration for a spawned agent.

    fork: If True, child inherits parent's message history (prompt cache hit).
          If False (default), child starts with a fresh context.
    """
    role: RoleName
    model_name: str = "gpt-5.4-mini"
    max_turns: int = 8
    allowed_tools: list[str] | None = None  # None = use role default
    agent_id: str = field(default_factory=lambda: f"agent-{uuid.uuid4().hex[:8]}")
    parent_id: str | None = None
    depth: int = 0
    fork: bool = False


@dataclass(slots=True)
class AgentResult:
    """Result from a completed agent."""
    agent_id: str = ""
    role: str = ""
    output: str = ""
    turn_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    error: str = ""
