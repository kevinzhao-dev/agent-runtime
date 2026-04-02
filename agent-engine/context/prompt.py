"""System prompt assembly.

Builds the system prompt from RoleConfig sections with layered priority.
Priority: identity + rules + role-specific + tool awareness + append.
"""

from __future__ import annotations

from roles.config import RoleConfig


def build_system_prompt(
    role_config: RoleConfig,
    *,
    tool_names: list[str] | None = None,
    append_sections: list[str] | None = None,
) -> str:
    """Assemble system prompt from role config sections.

    Args:
        role_config: The role whose prompt sections to use.
        tool_names: If provided, adds a tool awareness section.
        append_sections: Additional sections appended at the end.

    Returns:
        The assembled system prompt string.
    """
    parts: list[str] = list(role_config.system_prompt_sections)

    if tool_names:
        tools_section = (
            "You have access to the following tools: "
            + ", ".join(tool_names)
            + ".\nUse them when appropriate to complete the user's request."
        )
        parts.append(tools_section)

    if append_sections:
        parts.extend(append_sections)

    return "\n\n".join(parts)
