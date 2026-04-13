"""Coding agent pack — the default pack for software-engineering tasks.

Imports `agent_runtime.tools` to trigger stdlib registration, then picks
which of those tools the agent is allowed to use.
"""
import agent_runtime.tools  # noqa: F401  (side-effect: register stdlib tools)

NAME = "coding"

ALLOWED_TOOLS = [
    "read_file",
    "grep_search",
    "write_file",
    "bash",
    "ask_user",
    "spawn_task",
]

RULES_FILES = ["AGENT.md"]
