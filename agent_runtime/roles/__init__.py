"""Role model — responsibility separation."""
from agent_runtime.roles.policy import (
    ALL_ROLES,
    IMPLEMENTATION,
    RESEARCH,
    ROLE_POLICIES,
    SYNTHESIS,
    VERIFICATION,
    RoleName,
    RolePolicy,
    can_verify,
    get_policy,
    is_tool_allowed,
)
