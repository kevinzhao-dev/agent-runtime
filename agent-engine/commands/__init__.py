"""Slash command system — modular, dual-use commands.

Commands are usable from both the REPL (user-facing) and programmatically
(system-facing). Each command lives in its own file under commands/.

Usage (REPL — display output):
    registry = create_default_registry()
    result = registry.execute("/history", context)
    renderer.console.print(result.output)

Usage (system — structured data):
    result = registry.execute("/history", context)
    messages = result.data  # list[dict]
"""

from commands.base import BaseCommand, CommandContext, CommandResult
from commands.registry import CommandRegistry, create_default_registry

__all__ = [
    "BaseCommand",
    "CommandContext",
    "CommandResult",
    "CommandRegistry",
    "create_default_registry",
]
