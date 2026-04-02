"""Context compaction — summarize conversation to reclaim token space.

Full flow: strip images -> summarize via LLM -> handle PTL retry
-> build compact boundary -> return CompactResult.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import anthropic

MAX_CONSECUTIVE_COMPACT_FAILURES = 3

COMPACT_SYSTEM_PROMPT = """\
You are a conversation summarizer. Summarize the conversation so far, preserving:
- All file paths and function/class names mentioned
- The current task and its progress
- Any unfinished steps or pending actions
- Key decisions made and their reasons
- Any errors encountered and how they were handled

Be concise but preserve all actionable information. The summary will replace \
the conversation history, so anything not included will be lost."""


@dataclass(frozen=True)
class CompactResult:
    summary_message: dict[str, Any]
    post_compact_messages: list[dict[str, Any]]
    tokens_before: int
    tokens_after: int  # estimated


def _strip_images(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove image content blocks from messages."""
    cleaned = []
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, list):
            filtered = [
                block for block in content
                if not (isinstance(block, dict) and block.get("type") == "image")
            ]
            if filtered:
                cleaned.append({**msg, "content": filtered})
        else:
            cleaned.append(msg)
    return cleaned


def _truncate_head(
    messages: list[dict[str, Any]], fraction: float = 0.5
) -> list[dict[str, Any]]:
    """Drop the oldest fraction of messages as a last-resort fallback."""
    keep_from = int(len(messages) * fraction)
    return messages[keep_from:]


def _build_post_compact_messages(
    summary: str,
    original_messages: list[dict[str, Any]],
    keep_recent: int = 4,
) -> list[dict[str, Any]]:
    """Build new message list: [summary] + last N messages."""
    summary_msg = {
        "role": "user",
        "content": f"[Context Summary]\n{summary}",
    }
    recent = original_messages[-keep_recent:] if keep_recent > 0 else []
    return [summary_msg] + recent


async def _summarize_via_llm(
    messages: list[dict[str, Any]],
    model: str,
    client: Any | None = None,
) -> str:
    """Call LLM to summarize the conversation."""
    # Build a flat text of the conversation for summarization
    conversation_text = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        parts.append(block["text"])
                    elif block.get("type") == "tool_result":
                        parts.append(f"[tool_result: {block.get('content', '')[:200]}]")
                    elif block.get("type") == "tool_use":
                        parts.append(f"[tool_use: {block.get('name', '')}]")
                elif isinstance(block, str):
                    parts.append(block)
            content = "\n".join(parts)
        conversation_text.append(f"{role}: {content}")

    full_text = "\n\n".join(conversation_text)

    if client is None:
        client = anthropic.AsyncAnthropic()
    response = await client.messages.create(
        model=model,
        max_tokens=2048,
        system=COMPACT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"Summarize this conversation:\n\n{full_text}"}],
    )

    return response.content[0].text


async def compact_conversation(
    messages: list[dict[str, Any]],
    model: str,
    tokens_before: int = 0,
    client: Any | None = None,
) -> CompactResult:
    """Run the full compact flow.

    Args:
        messages: Current conversation messages.
        model: Model to use for summarization.
        tokens_before: Current input token count.

    Returns:
        CompactResult with summary and post-compact messages.

    Raises:
        Exception: If compaction fails entirely.
    """
    # Step 1: Strip images
    cleaned = _strip_images(messages)

    # Step 2: Summarize via LLM
    try:
        summary = await _summarize_via_llm(cleaned, model, client=client)
    except anthropic.BadRequestError:
        # Prompt too long even for compact — truncate head and retry
        truncated = _truncate_head(cleaned)
        summary = await _summarize_via_llm(truncated, model, client=client)

    # Step 3: Build post-compact messages
    post_compact = _build_post_compact_messages(summary, messages, keep_recent=4)

    summary_msg = post_compact[0]

    return CompactResult(
        summary_message=summary_msg,
        post_compact_messages=post_compact,
        tokens_before=tokens_before,
        tokens_after=0,  # will be updated from next API response
    )
