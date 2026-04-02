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


# ---------------------------------------------------------------------------
# Prompt sections
# ---------------------------------------------------------------------------

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

_COORDINATOR_INSTRUCTIONS = """\
You are a coordinator. Your job is to:
1. Analyze the user's request and break it into sub-tasks.
2. Delegate each sub-task to a sub-agent using the agent_tool.
3. Synthesize the results from sub-agents into a coherent response.

IMPORTANT: Do NOT implement code yourself. Use agent_tool to delegate \
implementation to an "implementer" agent and verification to a "verifier" agent."""

_IMPLEMENTER_INSTRUCTIONS = """\
You are an implementer. Complete the assigned coding task using the available tools. \
Focus on writing correct, clean code. Read existing files before modifying them. \
Test your changes when possible by running the code."""

_VERIFIER_INSTRUCTIONS = """\
You are a code verifier. Your job is to independently check whether an \
implementation is correct. Assume the code has bugs — your task is to find them.

- Read the relevant files carefully.
- Run tests if available (using bash with read-only intent).
- Check for edge cases, missing error handling, and logical errors.
- Report your findings clearly: PASS, FAIL, or PARTIAL with reasons."""

# ---------------------------------------------------------------------------
# Role definitions
# ---------------------------------------------------------------------------

DEFAULT_ROLE = RoleConfig(
    name="default",
    system_prompt_sections=(_IDENTITY, _RULES),
    allowed_tools=None,
    max_turns=30,
)

COORDINATOR_ROLE = RoleConfig(
    name="coordinator",
    system_prompt_sections=(_IDENTITY, _RULES, _COORDINATOR_INSTRUCTIONS),
    allowed_tools=("read_file", "grep", "agent_tool"),
    can_spawn_agents=True,
    max_turns=30,
)

IMPLEMENTER_ROLE = RoleConfig(
    name="implementer",
    system_prompt_sections=(_IDENTITY, _RULES, _IMPLEMENTER_INSTRUCTIONS),
    allowed_tools=("read_file", "write_file", "edit", "bash", "grep"),
    max_turns=50,
)

VERIFIER_ROLE = RoleConfig(
    name="verifier",
    system_prompt_sections=(_IDENTITY, _RULES, _VERIFIER_INSTRUCTIONS),
    allowed_tools=("read_file", "grep", "bash"),
    read_only=True,
    max_turns=20,
)

ROLE_REGISTRY: dict[str, RoleConfig] = {
    "default": DEFAULT_ROLE,
    "coordinator": COORDINATOR_ROLE,
    "implementer": IMPLEMENTER_ROLE,
    "verifier": VERIFIER_ROLE,
}
