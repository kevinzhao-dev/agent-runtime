"""Base types for the command system."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.session_log import SessionLog


@dataclass
class CommandContext:
    """Shared state available to all commands.

    Passed to every command execution — both user-invoked and system-invoked.
    """
    messages: list[dict[str, Any]]
    session_log: SessionLog
    working_dir: str = ""


@dataclass
class CommandResult:
    """Result of a command execution.

    output: Human-readable text for REPL display.
    data:   Structured data for programmatic/system use.
    """
    output: str = ""
    data: Any = None


class BaseCommand:
    """Base class for slash commands.

    Subclass and override name, description, and execute().
    """

    @property
    def name(self) -> str:
        """The slash command name without the leading slash (e.g., 'help')."""
        raise NotImplementedError

    @property
    def description(self) -> str:
        """Short one-line description shown in /help."""
        raise NotImplementedError

    @property
    def system_only(self) -> bool:
        """If True, this command is hidden from /help but callable by the system."""
        return False

    def execute(self, ctx: CommandContext, args: str = "") -> CommandResult:
        """Execute the command.

        Args:
            ctx:  Shared state (messages, session_log, etc.)
            args: Any text after the command name (e.g., "/history 5" → args="5")

        Returns:
            CommandResult with output (for display) and data (for system use).
        """
        raise NotImplementedError
