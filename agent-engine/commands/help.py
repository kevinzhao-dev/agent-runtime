"""Built-in /help command."""

from __future__ import annotations

from typing import TYPE_CHECKING

from commands.base import BaseCommand, CommandContext, CommandResult

if TYPE_CHECKING:
    from commands.registry import CommandRegistry


class HelpCommand(BaseCommand):
    """Show available slash commands."""

    def __init__(self, registry: CommandRegistry) -> None:
        self._registry = registry

    @property
    def name(self) -> str:
        return "help"

    @property
    def description(self) -> str:
        return "Show available commands"

    def execute(self, ctx: CommandContext, args: str = "") -> CommandResult:
        commands = self._registry.list_commands(include_system=False)
        lines = []
        for cmd in sorted(commands, key=lambda c: c.name):
            lines.append(f"  /{cmd.name:<12} {cmd.description}")
        lines.append(f"  {'exit':<13} Quit the REPL")

        output = "\n".join(lines)
        data = [{"name": c.name, "description": c.description} for c in commands]
        return CommandResult(output=output, data=data)
