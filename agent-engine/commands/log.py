"""Built-in /log command."""

from __future__ import annotations

from commands.base import BaseCommand, CommandContext, CommandResult


class LogCommand(BaseCommand):
    """Show the path to the current session log file."""

    @property
    def name(self) -> str:
        return "log"

    @property
    def description(self) -> str:
        return "Show path to the session log file"

    def execute(self, ctx: CommandContext, args: str = "") -> CommandResult:
        path = str(ctx.session_log.path)
        output = f"  Session log: {path}"
        return CommandResult(output=output, data=path)
