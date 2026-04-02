"""Role configuration for agent engine.

RoleConfig defines behavior boundaries for each agent role:
system prompt sections, allowed tools, permissions, and limits.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RoleConfig:
    name: str
    system_prompt_sections: tuple[str, ...]
    allowed_tools: tuple[str, ...] | None = None  # None = all tools
    read_only: bool = False
    can_spawn_agents: bool = False
    max_turns: int = 30
    model: str = "claude-sonnet-4-20250514"


# --- Default role: general-purpose coding agent ---

_IDENTITY = """\
You are a coding assistant. You help users with software engineering tasks \
including writing code, debugging, refactoring, and explaining code. \
You have access to tools for reading and writing files, running shell commands, \
and searching codebases."""

_RULES = """\
- Think step by step before acting.
- Read existing code before modifying it.
- Make minimal, focused changes.
- If a tool call fails, read the error and adjust your approach.
- Do not guess file contents — read them first.
- When done, summarize what you did."""

DEFAULT_ROLE = RoleConfig(
    name="default",
    system_prompt_sections=(_IDENTITY, _RULES),
    allowed_tools=None,
    max_turns=30,
)
