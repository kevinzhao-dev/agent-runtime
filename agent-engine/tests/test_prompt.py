"""Tests for context/prompt.py — system prompt assembly."""

from context.prompt import build_system_prompt
from roles.config import COORDINATOR_ROLE, DEFAULT_ROLE, RoleConfig


def test_basic_prompt():
    prompt = build_system_prompt(DEFAULT_ROLE)
    assert "coding assistant" in prompt
    assert "step by step" in prompt


def test_prompt_sections_joined():
    role = RoleConfig(name="test", system_prompt_sections=("AAA", "BBB"))
    prompt = build_system_prompt(role)
    assert "AAA" in prompt
    assert "BBB" in prompt
    assert "AAA\n\nBBB" in prompt


def test_tool_names_section():
    prompt = build_system_prompt(DEFAULT_ROLE, tool_names=["read_file", "bash"])
    assert "read_file" in prompt
    assert "bash" in prompt


def test_tool_names_none():
    prompt = build_system_prompt(DEFAULT_ROLE, tool_names=None)
    assert "tools:" not in prompt.lower() or "access to tools" not in prompt


def test_append_sections():
    prompt = build_system_prompt(DEFAULT_ROLE, append_sections=["EXTRA RULES"])
    assert "EXTRA RULES" in prompt


def test_coordinator_prompt_has_instructions():
    prompt = build_system_prompt(COORDINATOR_ROLE)
    assert "coordinator" in prompt.lower()
    assert "delegate" in prompt.lower() or "agent_tool" in prompt.lower()
