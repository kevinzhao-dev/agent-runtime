"""grep_search tool — search file contents with regex patterns."""
from __future__ import annotations

import re
from pathlib import Path

from agent_runtime.tools.base import ToolSpec, registry

_MAX_RESULTS = 100


def _grep_search(params: dict) -> str:
    pattern = params["pattern"]
    path = Path(params.get("path", ".")).expanduser()
    glob_pattern = params.get("glob", "**/*")

    try:
        regex = re.compile(pattern)
    except re.error as e:
        return f"Error: Invalid regex: {e}"

    if not path.exists():
        return f"Error: Path not found: {path}"

    results: list[str] = []

    if path.is_file():
        files = [path]
    else:
        files = sorted(path.glob(glob_pattern))

    for fp in files:
        if not fp.is_file():
            continue
        try:
            text = fp.read_text(encoding="utf-8", errors="replace")
        except (PermissionError, OSError):
            continue

        for i, line in enumerate(text.splitlines(), 1):
            if regex.search(line):
                results.append(f"{fp}:{i}: {line}")
                if len(results) >= _MAX_RESULTS:
                    results.append(f"... (truncated at {_MAX_RESULTS} results)")
                    return "\n".join(results)

    if not results:
        return "No matches found."
    return "\n".join(results)


registry.register(ToolSpec(
    name="grep_search",
    description="Search file contents using a regex pattern.",
    input_schema={
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Regex pattern to search for"},
            "path": {"type": "string", "description": "Directory or file to search in", "default": "."},
            "glob": {"type": "string", "description": "Glob filter for files", "default": "**/*"},
        },
        "required": ["pattern"],
    },
    executor=_grep_search,
    risk="low",
))
