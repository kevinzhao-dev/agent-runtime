"""Compaction and recovery — context overflow is a primary engineering concern.

When context exceeds threshold:
1. Generate compact summary (LLM call or heuristic)
2. Preserve intact: session working memory
3. Preserve: recent tool outcomes, active file references
4. Discard: full transcript history

Recovery paths:
- Output too long → continue generation
- Context too long → compact
- Tool failure/interrupt → ledger entry + report to loop
- Task abort → cleanup path (finalize ledger + transcript)
"""
from __future__ import annotations

from typing import Any

from agent_runtime.engine.loop import estimate_tokens
from agent_runtime.engine.models import SessionState, TurnConfig, WorkingMemory, user_message
from agent_runtime.prompt.context import format_working_memory


def _summarize_messages(messages: list[dict[str, Any]], max_lines: int = 20) -> str:
    """Create a heuristic summary of conversation messages.

    This is the MVP approach — no LLM call, just extract key info.
    Can be replaced with an LLM-based summarizer later.
    """
    lines: list[str] = []
    for m in messages:
        role = m.get("role", "")
        content = m.get("content", "")
        if isinstance(content, str) and content.strip():
            # Take first 100 chars of each message
            preview = content.strip()[:100].replace("\n", " ")
            lines.append(f"[{role}] {preview}")
        elif role == "tool":
            name = m.get("name", "tool")
            lines.append(f"[tool:{name}] (result)")
        if len(lines) >= max_lines:
            lines.append("... (earlier messages omitted)")
            break
    return "\n".join(lines)


def compact(
    state: SessionState,
    config: TurnConfig,
    *,
    preserve_recent: int = 4,
) -> str:
    """Perform compaction on session state.

    Preserves:
    - Working memory (always intact)
    - Recent messages (last `preserve_recent`)
    - Compact summary

    Discards:
    - Old transcript messages

    Returns the generated summary string.
    """
    if len(state.messages) <= preserve_recent:
        return state.compact_summary  # nothing to compact

    # Split: old messages to summarize, recent to keep
    old_messages = state.messages[:-preserve_recent]
    recent_messages = state.messages[-preserve_recent:]

    # Generate summary of old messages
    summary = _summarize_messages(old_messages)

    # Build the compacted message history
    compact_msg = user_message(
        f"[System: Previous conversation compacted]\n\n"
        f"## Summary of prior conversation\n{summary}\n\n"
        f"## Working Memory\n{format_working_memory(state.working_memory)}"
    )

    # Replace messages with compact summary + recent
    state.messages = [compact_msg] + recent_messages
    state.compact_summary = summary

    return summary


def update_working_memory(
    wm: WorkingMemory,
    *,
    tool_name: str | None = None,
    tool_output: str | None = None,
    file_path: str | None = None,
    error: str | None = None,
    correction: str | None = None,
    result: str | None = None,
    worklog_entry: str | None = None,
) -> None:
    """Update working memory after a tool execution or significant event."""
    if file_path and file_path not in wm.files_touched:
        wm.files_touched.append(file_path)
    if error:
        entry = f"{error}"
        if correction:
            entry += f" → {correction}"
        wm.errors_and_corrections.append(entry)
    if result:
        wm.key_results.append(result)
    if worklog_entry:
        wm.worklog.append(worklog_entry)
