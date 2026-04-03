"""Rich-based display renderer for the agent engine CLI.

Renders engine events with compact inline formatting, streaming Markdown,
and clear interactive permission prompts.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.rule import Rule
from rich.status import Status
from rich.text import Text

from engine.state import (
    CompactEvent,
    DoneEvent,
    ErrorEvent,
    Event,
    TextEvent,
    ToolResultEvent,
    ToolUseEvent,
)

# Max lines for tool results before collapsing
_COLLAPSE_THRESHOLD = 20
_COLLAPSE_TAIL = 5


class DisplayRenderer:
    """Renders engine events to the terminal using Rich."""

    def __init__(self, console: Console | None = None):
        self.console = console or Console()
        self._active_status: Status | None = None

    # ------------------------------------------------------------------
    # Chrome: welcome, goodbye, input
    # ------------------------------------------------------------------

    def render_welcome(self, version: str, mode_label: str = "") -> None:
        title = f"Agent Engine {version}{mode_label}"
        self.console.print(
            Text(title, style="bold cyan"),
            Text("  type 'exit' to quit", style="dim"),
        )
        self.console.print()

    def render_goodbye(self) -> None:
        self.console.print(Text("Goodbye!", style="bold"))

    def get_user_input(self) -> str:
        return self.console.input("[bold green]> [/bold green]")

    # ------------------------------------------------------------------
    # Permission prompt — must stand out clearly
    # ------------------------------------------------------------------

    def render_permission_prompt(
        self, tool_name: str, tool_input: dict[str, Any]
    ) -> bool:
        # Pause any active spinner so the prompt is clean
        paused_status = self._active_status
        if paused_status is not None:
            paused_status.stop()
            self._active_status = None

        summary = _one_line_summary(tool_input)
        self.console.print()
        self.console.print(
            Rule("[bold yellow]Permission Required[/bold yellow]", style="yellow")
        )
        self.console.print(
            f"  [bold]{tool_name}[/bold] [dim]{summary}[/dim]"
        )
        self.console.print()
        answer = self.console.input("  [bold yellow]Allow? [y/N]:[/bold yellow] ")
        self.console.print(Rule(style="yellow"))

        # Resume spinner if one was active
        if paused_status is not None:
            paused_status.start()
            self._active_status = paused_status

        return answer.strip().lower() in ("y", "yes")

    # ------------------------------------------------------------------
    # Compact event rendering — inline, no panels
    # ------------------------------------------------------------------

    def render_tool_use(self, name: str, tool_input: dict[str, Any]) -> None:
        summary = _one_line_summary(tool_input)
        self.console.print(f"  [dim bold]{name}[/dim bold] [dim]{summary}[/dim]")

    def render_tool_result(self, content: str, is_error: bool) -> None:
        if is_error:
            self.console.print(f"  [red]Error: {_truncate(content, 200)}[/red]")
            return

        lines = content.split("\n")
        if len(lines) <= _COLLAPSE_THRESHOLD:
            for line in lines:
                self.console.print(f"  [dim]{line}[/dim]")
        else:
            for line in lines[:_COLLAPSE_TAIL]:
                self.console.print(f"  [dim]{line}[/dim]")
            hidden = len(lines) - _COLLAPSE_TAIL
            self.console.print(f"  [dim italic]... {hidden} more lines[/dim italic]")

    def render_error(self, error: str) -> None:
        self.console.print(f"  [bold red]Error:[/bold red] [red]{error}[/red]")

    def render_compact(
        self, summary: str, tokens_before: int, tokens_after: int
    ) -> None:
        saved = tokens_before - tokens_after
        self.console.print(
            f"  [dim]compacted {tokens_before:,} -> {tokens_after:,} tokens (saved {saved:,})[/dim]"
        )

    def render_done(self, reason: str, turns: int) -> None:
        label = f"{reason}, {turns} turn{'s' if turns != 1 else ''}"
        self.console.print()
        self.console.print(Rule(label, style="dim"))
        self.console.print()

    # ------------------------------------------------------------------
    # Spinner management
    # ------------------------------------------------------------------

    def _start_status(self, message: str) -> None:
        self._active_status = Status(message, console=self.console, spinner="dots")
        self._active_status.start()

    def _stop_status(self) -> None:
        if self._active_status is not None:
            self._active_status.stop()
            self._active_status = None

    # ------------------------------------------------------------------
    # Streaming markdown renderer
    # ------------------------------------------------------------------

    async def render_event_stream(
        self, events: AsyncIterator[Event]
    ) -> DoneEvent | None:
        """Consume an event stream, rendering each event.

        Text events are accumulated and progressively rendered as Markdown.
        Returns the DoneEvent when the stream finishes.
        """
        buffer = ""
        live: Live | None = None

        self._start_status("Thinking...")

        try:
            async for event in events:
                match event:
                    case TextEvent(text=text):
                        self._stop_status()

                        if live is None:
                            live = Live(
                                Markdown(text),
                                console=self.console,
                                refresh_per_second=8,
                                vertical_overflow="visible",
                            )
                            live.start()

                        buffer += text
                        live.update(Markdown(buffer))

                    case ToolUseEvent(tool_name=name, input=inp):
                        if live is not None:
                            live.update(Markdown(buffer))
                            live.stop()
                            live = None
                            buffer = ""

                        self._stop_status()
                        self.render_tool_use(name, inp)
                        self._start_status(f"  Executing {name}...")

                    case ToolResultEvent(content=content, is_error=is_error):
                        self._stop_status()
                        self.render_tool_result(content, is_error)
                        self._start_status("Thinking...")

                    case CompactEvent(
                        summary=summary,
                        tokens_before=before,
                        tokens_after=after,
                    ):
                        self.render_compact(summary, before, after)

                    case ErrorEvent(error=err):
                        self._stop_status()
                        if live is not None:
                            live.update(Markdown(buffer))
                            live.stop()
                            live = None
                            buffer = ""
                        self.render_error(err)

                    case DoneEvent(reason=reason, turn_count=turns):
                        if live is not None:
                            live.update(Markdown(buffer))
                            live.stop()
                            live = None
                            buffer = ""
                        self._stop_status()
                        self.render_done(reason, turns)
                        return event

        finally:
            if live is not None:
                live.stop()
            self._stop_status()

        return None


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _one_line_summary(data: dict[str, Any], max_len: int = 100) -> str:
    """Compact one-line summary of tool input."""
    try:
        text = json.dumps(data, ensure_ascii=False, separators=(", ", ": "))
    except (TypeError, ValueError):
        text = str(data)
    return _truncate(text, max_len)


def _truncate(s: str, max_len: int) -> str:
    return s[:max_len] + "..." if len(s) > max_len else s
