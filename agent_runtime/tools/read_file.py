"""read_file tool — read file contents with optional line range."""
from __future__ import annotations

from pathlib import Path

from agent_runtime.tools.base import ToolSpec, registry


def _read_file(params: dict) -> str:
    path = Path(params["file_path"]).expanduser()
    if not path.exists():
        return f"Error: File not found: {path}"
    if not path.is_file():
        return f"Error: Not a file: {path}"

    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines(keepends=True)

    offset = params.get("offset", 0)
    limit = params.get("limit", len(lines))
    selected = lines[offset : offset + limit]

    # Number lines (1-based)
    numbered = [f"{offset + i + 1}\t{line}" for i, line in enumerate(selected)]
    return "".join(numbered)


registry.register(ToolSpec(
    name="read_file",
    description="Read a file's contents. Returns numbered lines.",
    input_schema={
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "Absolute path to the file"},
            "offset": {"type": "integer", "description": "Line offset (0-based)", "default": 0},
            "limit": {"type": "integer", "description": "Max lines to read"},
        },
        "required": ["file_path"],
    },
    executor=_read_file,
    risk="low",
))
