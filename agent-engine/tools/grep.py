"""Grep tool — search file contents with regex."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from tools.base import BaseTool, ToolContext, ToolResult

MAX_MATCHES = 100


class GrepTool(BaseTool):
    @property
    def name(self) -> str:
        return "grep"

    @property
    def description(self) -> str:
        return "Search for a regex pattern in files. Returns matching lines with paths and line numbers."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Regex pattern to search for",
                },
                "path": {
                    "type": "string",
                    "description": "Directory or file to search in (default: working dir)",
                },
                "glob": {
                    "type": "string",
                    "description": "File glob pattern, e.g. '*.py'",
                    "default": "*",
                },
                "case_insensitive": {
                    "type": "boolean",
                    "description": "Case insensitive search",
                    "default": False,
                },
            },
            "required": ["pattern"],
        }

    def is_read_only(self) -> bool:
        return True

    async def execute(self, *, input: dict[str, Any], context: ToolContext) -> ToolResult:
        pattern_str = input["pattern"]
        search_path = input.get("path", context.working_dir)
        glob_pattern = input.get("glob", "*")
        case_insensitive = input.get("case_insensitive", False)

        if not os.path.isabs(search_path):
            search_path = os.path.join(context.working_dir, search_path)

        flags = re.IGNORECASE if case_insensitive else 0
        try:
            regex = re.compile(pattern_str, flags)
        except re.error as e:
            return ToolResult(content=f"Invalid regex: {e}", is_error=True)

        matches: list[str] = []
        search = Path(search_path)

        if search.is_file():
            files = [search]
        elif search.is_dir():
            files = sorted(search.rglob(glob_pattern))
        else:
            return ToolResult(content=f"Path not found: {search_path}", is_error=True)

        for filepath in files:
            if not filepath.is_file():
                continue
            try:
                text = filepath.read_text(encoding="utf-8", errors="replace")
            except (PermissionError, OSError):
                continue

            for lineno, line in enumerate(text.splitlines(), 1):
                if regex.search(line):
                    rel = os.path.relpath(filepath, context.working_dir)
                    matches.append(f"{rel}:{lineno}: {line.rstrip()}")
                    if len(matches) >= MAX_MATCHES:
                        matches.append(f"... (truncated at {MAX_MATCHES} matches)")
                        return ToolResult(content="\n".join(matches))

        if not matches:
            return ToolResult(content="No matches found.")
        return ToolResult(content="\n".join(matches))
