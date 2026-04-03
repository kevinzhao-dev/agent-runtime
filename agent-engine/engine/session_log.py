"""Session file logger — writes structured event logs per session.

Each REPL session creates a timestamped log file under .agent-engine/logs/.
Captures all events for post-mortem debugging without polluting the terminal.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("agent_engine.session_log")

_LOG_DIR = ".agent-engine/logs"


class SessionLog:
    """Append-only structured log for a single session."""

    def __init__(self, working_dir: str | None = None):
        base = Path(working_dir or os.getcwd()) / _LOG_DIR
        base.mkdir(parents=True, exist_ok=True)

        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self.path = base / f"session_{ts}.jsonl"
        self._file = open(self.path, "a", encoding="utf-8")

        self._write("session_start", {
            "working_dir": str(working_dir or os.getcwd()),
            "timestamp": ts,
        })
        logger.info("session log: %s", self.path)

    def log_user_input(self, text: str) -> None:
        self._write("user_input", {"text": text})

    def log_text(self, text: str) -> None:
        self._write("text", {"text": text})

    def log_tool_use(self, name: str, tool_id: str, tool_input: dict[str, Any]) -> None:
        self._write("tool_use", {"name": name, "tool_id": tool_id, "input": tool_input})

    def log_tool_result(self, tool_id: str, content: str, is_error: bool) -> None:
        self._write("tool_result", {"tool_id": tool_id, "content": content, "is_error": is_error})

    def log_error(self, error: str, recoverable: bool) -> None:
        self._write("error", {"error": error, "recoverable": recoverable})

    def log_compact(self, tokens_before: int, tokens_after: int) -> None:
        self._write("compact", {"tokens_before": tokens_before, "tokens_after": tokens_after})

    def log_done(self, reason: str, turn_count: int) -> None:
        self._write("done", {"reason": reason, "turn_count": turn_count})

    def log_command(self, command: str) -> None:
        self._write("slash_command", {"command": command})

    def close(self) -> None:
        self._write("session_end", {})
        self._file.close()

    def _write(self, event_type: str, data: dict[str, Any]) -> None:
        ts = datetime.now(timezone.utc).isoformat()
        record = {"ts": ts, "event": event_type, **data}
        try:
            self._file.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._file.flush()
        except Exception:
            pass  # Never crash the agent due to logging
