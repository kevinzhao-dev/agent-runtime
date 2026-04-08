"""Role model — responsibility separation as architecture.

Four roles: research, implementation, verification, synthesis.
Key constraint: implementation != verification. The agent that writes
the code and the agent that verifies it must not be the same.

MVP defines the model; full spawning comes later.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

RoleName = Literal["research", "implementation", "verification", "synthesis"]

ALL_ROLES: list[RoleName] = ["research", "implementation", "verification", "synthesis"]


@dataclass(frozen=True, slots=True)
class RolePolicy:
    """Defines what a role is allowed and expected to do."""
    name: RoleName
    description: str
    allowed_tools: list[str] = field(default_factory=list)
    can_verify_own_work: bool = False
    can_modify_files: bool = False


# ── Role Definitions ──────────────────────────────────────────────────────

RESEARCH = RolePolicy(
    name="research",
    description="Investigate, read, search, and gather information.",
    allowed_tools=["read_file", "grep_search", "bash", "ask_user"],
    can_verify_own_work=False,
    can_modify_files=False,
)

IMPLEMENTATION = RolePolicy(
    name="implementation",
    description="Write code, modify files, execute commands.",
    allowed_tools=["read_file", "write_file", "bash", "grep_search", "ask_user"],
    can_verify_own_work=False,  # KEY: cannot self-verify
    can_modify_files=True,
)

VERIFICATION = RolePolicy(
    name="verification",
    description="Review, test, and verify work done by others.",
    allowed_tools=["read_file", "grep_search", "bash", "ask_user"],
    can_verify_own_work=False,
    can_modify_files=False,
)

SYNTHESIS = RolePolicy(
    name="synthesis",
    description="Coordinate, synthesize results, make decisions.",
    allowed_tools=["read_file", "grep_search", "ask_user"],
    can_verify_own_work=False,
    can_modify_files=False,
)

ROLE_POLICIES: dict[RoleName, RolePolicy] = {
    "research": RESEARCH,
    "implementation": IMPLEMENTATION,
    "verification": VERIFICATION,
    "synthesis": SYNTHESIS,
}


def get_policy(role: RoleName) -> RolePolicy:
    """Get the policy for a given role."""
    return ROLE_POLICIES[role]


def can_verify(implementer: RoleName, verifier: RoleName) -> bool:
    """Check if verifier role can verify implementer's work.

    Key rule: a role cannot verify its own work.
    Implementation and verification must be structurally independent.
    """
    if implementer == verifier:
        return False
    if verifier != "verification":
        return False
    return True


def is_tool_allowed(role: RoleName, tool_name: str) -> bool:
    """Check if a tool is allowed for the given role."""
    policy = ROLE_POLICIES.get(role)
    if policy is None:
        return False
    return tool_name in policy.allowed_tools
