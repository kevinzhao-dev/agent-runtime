"""Minimal pack — a conversation-only agent with no tools.

Useful for quickly validating the pack system itself, and as a starting
point when forking a new non-coding agent (layout, 3D, planning, ...).
"""
NAME = "minimal"

ALLOWED_TOOLS: list[str] = []

RULES_FILES = ["AGENT.md"]
