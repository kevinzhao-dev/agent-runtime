"""write_file tool — write content to a file."""
from __future__ import annotations

from pathlib import Path

from agent_runtime.tools.base import ToolSpec, registry


def _write_file(params: dict) -> str:
    path = Path(params["file_path"]).expanduser()
    content = params["content"]

    # Create parent directories if needed
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return f"Successfully wrote {len(content)} chars to {path}"


registry.register(ToolSpec(
    name="write_file",
    description="Write content to a file. Creates parent directories if needed.",
    input_schema={
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "Absolute path to the file"},
            "content": {"type": "string", "description": "Content to write"},
        },
        "required": ["file_path", "content"],
    },
    executor=_write_file,
    risk="low",
    side_effecting=True,
))
