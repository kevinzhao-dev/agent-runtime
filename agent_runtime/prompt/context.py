"""Context assembler — builds per-turn context from memory layers.

Assembles: rules (always) + index (always) + working memory (always)
         + topics (on demand) + transcripts (never).

Working memory is always included and survives compaction.
Each section carries a source label for debuggability.
"""
from __future__ import annotations

from agent_runtime.engine.models import SessionState, WorkingMemory


def format_working_memory(wm: WorkingMemory) -> str:
    """Format working memory into a readable block for the prompt."""
    parts: list[str] = []
    if wm.task_state:
        parts.append(f"**Current Task:** {wm.task_state}")
    if wm.files_touched:
        parts.append(f"**Files Touched:** {', '.join(wm.files_touched)}")
    if wm.errors_and_corrections:
        parts.append("**Errors & Corrections:**")
        for item in wm.errors_and_corrections[-5:]:  # keep recent
            parts.append(f"  - {item}")
    if wm.key_results:
        parts.append("**Key Results:**")
        for item in wm.key_results[-5:]:
            parts.append(f"  - {item}")
    if wm.worklog:
        parts.append("**Worklog:**")
        for item in wm.worklog[-10:]:
            parts.append(f"  - {item}")

    return "\n".join(parts) if parts else ""


def build_task_context(
    state: SessionState,
    *,
    rules_content: str = "",
    memory_index: str = "",
    topic_content: str = "",
) -> str:
    """Build the task context section for the prompt.

    This is Layer 4 (dynamic, not cacheable) and includes:
    - Working memory (always)
    - Loaded topics (on demand)
    - Recent tool outcomes from ledger
    """
    sections: list[str] = []

    # Working memory — always included
    wm_text = format_working_memory(state.working_memory)
    if wm_text:
        sections.append(f"## Working Memory\n{wm_text}")

    # Topic content — loaded on demand
    if topic_content:
        sections.append(f"## Loaded Topics\n{topic_content}")

    # Recent ledger summary — last 5 entries
    if state.ledger:
        recent = state.ledger[-5:]
        ledger_lines = []
        for entry in recent:
            ledger_lines.append(
                f"  - {entry.tool_name}: {entry.status}"
                + (f" ({entry.summary[:80]})" if entry.summary else "")
            )
        sections.append(f"## Recent Tool Results\n" + "\n".join(ledger_lines))

    # Compact summary if present
    if state.compact_summary:
        sections.append(f"## Prior Context Summary\n{state.compact_summary}")

    return "\n\n".join(sections)
