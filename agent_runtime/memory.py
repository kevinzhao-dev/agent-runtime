"""3-layer memory model — treat the context window as a scarce resource.

Layer 1 (Rules):       Always loaded. AGENT.md, PROJECT.md.
Layer 2 (Index):       Always loaded. MEMORY.md — short lines, pointers only.
Layer 3 (Topic files): Loaded on demand. Full knowledge content.

Transcripts:           Never in prompt. Stored separately.

Write discipline: index is pointers, not content.
If a fact can be re-derived from the codebase, do not store it.
"""
from __future__ import annotations

from pathlib import Path


def load_rules(*paths: str | Path) -> str:
    """Load rule files (AGENT.md, PROJECT.md). Always loaded every turn.

    Returns concatenated content of all existing rule files.
    """
    parts: list[str] = []
    for p in paths:
        path = Path(p).expanduser()
        if path.is_file():
            content = path.read_text(encoding="utf-8", errors="replace").strip()
            if content:
                parts.append(f"# {path.name}\n{content}")
    return "\n\n".join(parts)


def load_memory_index(path: str | Path = "MEMORY.md") -> str:
    """Load the memory index. Always loaded every turn (cheap).

    The index contains short pointer lines, not full content.
    """
    index_path = Path(path).expanduser()
    if not index_path.is_file():
        return ""
    content = index_path.read_text(encoding="utf-8", errors="replace").strip()
    # Enforce line limit to keep it cheap
    lines = content.splitlines()
    if len(lines) > 200:
        lines = lines[:200]
        lines.append("... (index truncated at 200 lines)")
    return "\n".join(lines)


def load_topic(path: str | Path) -> str:
    """Load a topic file on demand. Only when retrieval logic requests it.

    Returns the file content, or an error message if not found.
    """
    topic_path = Path(path).expanduser()
    if not topic_path.is_file():
        return f"Topic file not found: {topic_path}"
    return topic_path.read_text(encoding="utf-8", errors="replace").strip()


def list_topics(memory_dir: str | Path = ".") -> list[Path]:
    """List available topic files in a memory directory.

    Excludes MEMORY.md (the index) and rule files.
    """
    dir_path = Path(memory_dir).expanduser()
    if not dir_path.is_dir():
        return []
    exclude = {"MEMORY.md", "AGENT.md", "PROJECT.md"}
    return sorted(
        p for p in dir_path.glob("*.md")
        if p.name not in exclude and p.is_file()
    )
