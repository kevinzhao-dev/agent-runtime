"""Read file tool — reads file content with optional line range."""

from __future__ import annotations

import os
from typing import Any

from tools.base import BaseTool, ToolContext, ToolResult


class ReadFileTool(BaseTool):
    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return "Read the contents of a file. Returns line-numbered output."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file (absolute or relative to working dir)",
                },
                "offset": {
                    "type": "integer",
                    "description": "Starting line number (0-based)",
                    "default": 0,
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of lines to read",
                    "default": 2000,
                },
            },
            "required": ["file_path"],
        }

    def is_read_only(self) -> bool:
        return True

    async def execute(self, *, input: dict[str, Any], context: ToolContext) -> ToolResult:
        file_path = input["file_path"]
        offset = input.get("offset", 0)
        limit = input.get("limit", 2000)

        if not os.path.isabs(file_path):
            file_path = os.path.join(context.working_dir, file_path)

        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except FileNotFoundError:
            return ToolResult(content=f"File not found: {file_path}", is_error=True)
        except PermissionError:
            return ToolResult(content=f"Permission denied: {file_path}", is_error=True)

        selected = lines[offset : offset + limit]
        numbered = [
            f"{offset + i + 1}\t{line.rstrip()}"
            for i, line in enumerate(selected)
        ]

        if not numbered:
            return ToolResult(content="(empty file or offset beyond end)")

        result = "\n".join(numbered)
        if offset + limit < len(lines):
            result += f"\n... ({len(lines) - offset - limit} more lines)"
        return ToolResult(content=result)
