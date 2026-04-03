"""Built-in /history command."""

from __future__ import annotations

from commands.base import BaseCommand, CommandContext, CommandResult


class HistoryCommand(BaseCommand):
    """Show conversation turns this session."""

    @property
    def name(self) -> str:
        return "history"

    @property
    def description(self) -> str:
        return "Show conversation turns this session"

    def execute(self, ctx: CommandContext, args: str = "") -> CommandResult:
        if not ctx.messages:
            return CommandResult(output="No conversation history yet.", data=[])

        lines = []
        for i, msg in enumerate(ctx.messages, 1):
            role = msg["role"]
            content = msg.get("content", "")
            if isinstance(content, list):
                content = "[tool result]"
            preview = content[:100] + "..." if len(content) > 100 else content
            lines.append(f"  {i:>3}. {role:<10} {preview}")

        return CommandResult(output="\n".join(lines), data=list(ctx.messages))
