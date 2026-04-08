"""Tests for role model — boundary assertions."""
from agent_runtime.roles import (
    ALL_ROLES,
    IMPLEMENTATION,
    RESEARCH,
    ROLE_POLICIES,
    SYNTHESIS,
    VERIFICATION,
    can_verify,
    get_policy,
    is_tool_allowed,
)


class TestRolePolicies:
    def test_all_roles_defined(self):
        for role in ALL_ROLES:
            assert role in ROLE_POLICIES

    def test_implementation_cannot_self_verify(self):
        """KEY ASSERTION: implementation cannot verify its own work."""
        assert IMPLEMENTATION.can_verify_own_work is False

    def test_verification_cannot_self_verify(self):
        assert VERIFICATION.can_verify_own_work is False

    def test_implementation_can_modify_files(self):
        assert IMPLEMENTATION.can_modify_files is True

    def test_verification_cannot_modify_files(self):
        assert VERIFICATION.can_modify_files is False

    def test_research_cannot_modify_files(self):
        assert RESEARCH.can_modify_files is False

    def test_synthesis_cannot_modify_files(self):
        assert SYNTHESIS.can_modify_files is False

    def test_policies_are_frozen(self):
        try:
            IMPLEMENTATION.can_modify_files = False  # type: ignore
            assert False, "Should be frozen"
        except AttributeError:
            pass


class TestCanVerify:
    def test_implementation_verified_by_verification(self):
        assert can_verify("implementation", "verification") is True

    def test_implementation_cannot_self_verify(self):
        """The boundary: impl != verify."""
        assert can_verify("implementation", "implementation") is False

    def test_verification_cannot_self_verify(self):
        assert can_verify("verification", "verification") is False

    def test_research_cannot_verify_implementation(self):
        assert can_verify("implementation", "research") is False

    def test_synthesis_cannot_verify_implementation(self):
        assert can_verify("implementation", "synthesis") is False


class TestIsToolAllowed:
    def test_implementation_has_write(self):
        assert is_tool_allowed("implementation", "write_file") is True

    def test_verification_no_write(self):
        assert is_tool_allowed("verification", "write_file") is False

    def test_research_has_read(self):
        assert is_tool_allowed("research", "read_file") is True

    def test_research_no_write(self):
        assert is_tool_allowed("research", "write_file") is False

    def test_all_roles_have_read_file(self):
        for role in ALL_ROLES:
            assert is_tool_allowed(role, "read_file") is True

    def test_only_implementation_has_write_file(self):
        for role in ALL_ROLES:
            if role == "implementation":
                assert is_tool_allowed(role, "write_file") is True
            else:
                assert is_tool_allowed(role, "write_file") is False


class TestGetPolicy:
    def test_valid_role(self):
        policy = get_policy("implementation")
        assert policy.name == "implementation"

    def test_all_policies_have_description(self):
        for role in ALL_ROLES:
            policy = get_policy(role)
            assert len(policy.description) > 0
