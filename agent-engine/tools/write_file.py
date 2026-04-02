"""Write file tool — create or overwrite a file."""

from __future__ import annotations

import os
from typing import Any

from tools.base import BaseTool, ToolContext, ToolResult


class WriteFileTool(BaseTool):
    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return "Create or overwrite a file with the given content."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to write to (absolute or relative to working dir)",
                },
                "content": {
                    "type": "string",
                    "description": "Content to write",
                },
            },
            "required": ["file_path", "content"],
        }

    def is_read_only(self) -> bool:
        return False

    async def execute(self, *, input: dict[str, Any], context: ToolContext) -> ToolResult:
        file_path = input["file_path"]
        content = input["content"]

        if not os.path.isabs(file_path):
            file_path = os.path.join(context.working_dir, file_path)

        try:
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
        except PermissionError:
            return ToolResult(content=f"Permission denied: {file_path}", is_error=True)
        except OSError as e:
            return ToolResult(content=f"Write error: {e}", is_error=True)

        line_count = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
        return ToolResult(content=f"Wrote {line_count} lines to {file_path}")
