"""Command registry — registration, lookup, and execution."""

from __future__ import annotations

from commands.base import BaseCommand, CommandContext, CommandResult


class CommandRegistry:
    """Registry for slash commands."""

    def __init__(self) -> None:
        self._commands: dict[str, BaseCommand] = {}

    def register(self, command: BaseCommand) -> None:
        self._commands[command.name] = command

    def get(self, name: str) -> BaseCommand | None:
        """Look up a command by name (without leading slash)."""
        return self._commands.get(name)

    def list_commands(self, include_system: bool = False) -> list[BaseCommand]:
        """List all registered commands."""
        if include_system:
            return list(self._commands.values())
        return [c for c in self._commands.values() if not c.system_only]

    def execute(self, raw_input: str, ctx: CommandContext) -> CommandResult | None:
        """Parse and execute a slash command.

        Args:
            raw_input: Full input string starting with '/' (e.g., "/history 5").
            ctx: Command context.

        Returns:
            CommandResult if the command was found and executed, None otherwise.
        """
        parts = raw_input.strip().split(maxsplit=1)
        name = parts[0].lstrip("/").lower()
        args = parts[1] if len(parts) > 1 else ""

        command = self.get(name)
        if command is None:
            return None

        ctx.session_log.log_command(f"/{name}")
        return command.execute(ctx, args)


def create_default_registry() -> CommandRegistry:
    """Create a registry with all built-in commands."""
    from commands.compact import CompactCommand
    from commands.help import HelpCommand
    from commands.history import HistoryCommand
    from commands.log import LogCommand

    registry = CommandRegistry()
    registry.register(HelpCommand(registry))
    registry.register(HistoryCommand())
    registry.register(LogCommand())
    registry.register(CompactCommand())
    return registry
