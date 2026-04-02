"""Edit tool — str_replace style precise editing."""

from __future__ import annotations

import os
from typing import Any

from tools.base import BaseTool, ToolContext, ToolResult


class EditTool(BaseTool):
    @property
    def name(self) -> str:
        return "edit"

    @property
    def description(self) -> str:
        return (
            "Replace an exact string in a file with new content. "
            "The old_string must match exactly (including whitespace)."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file to edit",
                },
                "old_string": {
                    "type": "string",
                    "description": "Exact string to find and replace",
                },
                "new_string": {
                    "type": "string",
                    "description": "Replacement string",
                },
            },
            "required": ["file_path", "old_string", "new_string"],
        }

    def is_read_only(self) -> bool:
        return False

    async def execute(self, *, input: dict[str, Any], context: ToolContext) -> ToolResult:
        file_path = input["file_path"]
        old_string = input["old_string"]
        new_string = input["new_string"]

        if not os.path.isabs(file_path):
            file_path = os.path.join(context.working_dir, file_path)

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except FileNotFoundError:
            return ToolResult(content=f"File not found: {file_path}", is_error=True)

        count = content.count(old_string)
        if count == 0:
            return ToolResult(
                content=f"old_string not found in {file_path}",
                is_error=True,
            )
        if count > 1:
            return ToolResult(
                content=f"old_string found {count} times — must be unique. Provide more context.",
                is_error=True,
            )

        new_content = content.replace(old_string, new_string, 1)

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(new_content)
        except OSError as e:
            return ToolResult(content=f"Write error: {e}", is_error=True)

        return ToolResult(content=f"Edited {file_path}: replaced 1 occurrence")
