"""Core data models for the agent runtime kernel.

Defines event types, session state, turn configuration, and working memory.
All models use dataclasses with slots for performance and clarity.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Literal


# ── Event Types ───────────────────────────────────────────────────────────
# Tagged union via `type` discriminator field.
# The query loop yields these as AsyncGenerator[Event, None].

@dataclass(slots=True)
class ThinkingEvent:
    """Model is producing internal reasoning."""
    type: Literal["thinking"] = "thinking"
    text: str = ""


@dataclass(slots=True)
class TextDeltaEvent:
    """Streaming text chunk from the model."""
    type: Literal["text_delta"] = "text_delta"
    text: str = ""


@dataclass(slots=True)
class ToolCallEvent:
    """Model requests a tool invocation."""
    type: Literal["tool_call"] = "tool_call"
    tool_call_id: str = ""
    tool_name: str = ""
    tool_input: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ToolResultEvent:
    """Result from a tool execution."""
    type: Literal["tool_result"] = "tool_result"
    tool_call_id: str = ""
    tool_name: str = ""
    output: str = ""
    status: Literal["ok", "error", "interrupted"] = "ok"


@dataclass(slots=True)
class RecoveryEvent:
    """A recovery action was taken (compact, continue, error report)."""
    type: Literal["recovery"] = "recovery"
    reason: Literal["output_too_long", "context_too_long", "tool_failure", "abort"] = "context_too_long"
    detail: str = ""


@dataclass(slots=True)
class FinalEvent:
    """Loop completed. Carries the final assistant message."""
    type: Literal["final"] = "final"
    text: str = ""


Event = ThinkingEvent | TextDeltaEvent | ToolCallEvent | ToolResultEvent | RecoveryEvent | FinalEvent


# ── Turn Configuration (immutable per query) ──────────────────────────────

@dataclass(frozen=True, slots=True)
class TurnConfig:
    """Immutable parameters for a single query loop invocation."""
    max_turns: int = 8
    allow_tools: bool = True
    model_name: str = "claude-sonnet-4-6"
    compact_threshold_tokens: int = 24_000
    max_tokens: int = 8192
    system_mode: str = "default"


# ── Working Memory (survives compaction) ──────────────────────────────────

@dataclass(slots=True)
class WorkingMemory:
    """Short-term structured memory that survives compaction.

    This is not transcript — it is a structured artifact the loop
    maintains and updates. Without it, compaction destroys continuity.
    """
    task_state: str = ""
    files_touched: list[str] = field(default_factory=list)
    errors_and_corrections: list[str] = field(default_factory=list)
    key_results: list[str] = field(default_factory=list)
    worklog: list[str] = field(default_factory=list)


# ── Session State (mutable, carried across turns) ─────────────────────────

@dataclass(slots=True)
class SessionState:
    """Mutable state for the duration of a session."""
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    messages: list[dict[str, Any]] = field(default_factory=list)
    ledger: list[Any] = field(default_factory=list)  # list[LedgerEntry] once tools module exists
    loaded_topics: list[str] = field(default_factory=list)
    working_memory: WorkingMemory = field(default_factory=WorkingMemory)
    compact_summary: str = ""
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    turn_count: int = 0


# ── Neutral Message Format ────────────────────────────────────────────────
# Internal format that is provider-agnostic.
# Converters in provider.py translate to/from API-specific formats.
#
#   {"role": "user",      "content": "text"}
#   {"role": "assistant", "content": "text",
#    "tool_calls": [{"id": "...", "name": "...", "input": {...}}]}
#   {"role": "tool", "tool_call_id": "...", "name": "...", "content": "..."}


def user_message(content: str) -> dict[str, Any]:
    return {"role": "user", "content": content}


def assistant_message(
    content: str = "",
    tool_calls: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    msg: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return msg


def tool_result_message(
    tool_call_id: str,
    name: str,
    content: str,
) -> dict[str, Any]:
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "name": name,
        "content": content,
    }
