"""Tests for roles/config.py — RoleConfig and role definitions."""

from roles.config import (
    COORDINATOR_ROLE,
    DEFAULT_ROLE,
    IMPLEMENTER_ROLE,
    ROLE_REGISTRY,
    VERIFIER_ROLE,
    RoleConfig,
)


def test_role_config_frozen():
    role = RoleConfig(name="test", system_prompt_sections=("hi",))
    try:
        role.name = "changed"
        assert False, "Should be frozen"
    except AttributeError:
        pass


def test_default_role():
    assert DEFAULT_ROLE.name == "default"
    assert DEFAULT_ROLE.allowed_tools is None  # all tools
    assert DEFAULT_ROLE.read_only is False
    assert DEFAULT_ROLE.max_turns == 30


def test_coordinator_role():
    assert COORDINATOR_ROLE.can_spawn_agents is True
    assert "agent_tool" in COORDINATOR_ROLE.allowed_tools
    assert "write_file" not in COORDINATOR_ROLE.allowed_tools


def test_implementer_role():
    assert "write_file" in IMPLEMENTER_ROLE.allowed_tools
    assert "agent_tool" not in IMPLEMENTER_ROLE.allowed_tools
    assert IMPLEMENTER_ROLE.max_turns == 50


def test_verifier_role():
    assert VERIFIER_ROLE.read_only is True
    assert "write_file" not in VERIFIER_ROLE.allowed_tools
    assert VERIFIER_ROLE.max_turns == 20


def test_role_registry():
    assert set(ROLE_REGISTRY.keys()) == {"default", "coordinator", "implementer", "verifier"}
    assert ROLE_REGISTRY["default"] is DEFAULT_ROLE
