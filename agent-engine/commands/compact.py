"""Built-in /compact command."""

from __future__ import annotations

from commands.base import BaseCommand, CommandContext, CommandResult


class CompactCommand(BaseCommand):
    """Show context compaction stats."""

    @property
    def name(self) -> str:
        return "compact"

    @property
    def description(self) -> str:
        return "Show context compaction stats"

    def execute(self, ctx: CommandContext, args: str = "") -> CommandResult:
        total_msgs = len(ctx.messages)
        user_turns = sum(1 for m in ctx.messages if m.get("role") == "user")

        output = f"  Messages: {total_msgs}, User turns: {user_turns}"
        data = {"messages": total_msgs, "user_turns": user_turns}
        return CommandResult(output=output, data=data)
