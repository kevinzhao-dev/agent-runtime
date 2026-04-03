"""Tests for context/compact.py — compact helpers and flow."""

import pytest

from context.compact import (
    _build_post_compact_messages,
    _strip_images,
    _truncate_head,
)


def test_strip_images_removes_image_blocks():
    messages = [
        {"role": "user", "content": [
            {"type": "text", "text": "look at this"},
            {"type": "image", "data": "base64..."},
        ]},
        {"role": "assistant", "content": "I see it"},
    ]
    result = _strip_images(messages)
    assert len(result) == 2
    # First message should only have text block
    assert len(result[0]["content"]) == 1
    assert result[0]["content"][0]["type"] == "text"


def test_strip_images_preserves_non_image():
    messages = [
        {"role": "user", "content": "plain text"},
        {"role": "assistant", "content": "reply"},
    ]
    result = _strip_images(messages)
    assert result == messages


def test_truncate_head_half():
    messages = [{"role": "user", "content": f"msg{i}"} for i in range(10)]
    result = _truncate_head(messages, fraction=0.5)
    assert len(result) == 5
    assert result[0]["content"] == "msg5"


def test_truncate_head_custom_fraction():
    messages = [{"role": "user", "content": f"msg{i}"} for i in range(10)]
    result = _truncate_head(messages, fraction=0.8)
    assert len(result) == 2


def test_build_post_compact_messages():
    original = [{"role": "user", "content": f"msg{i}"} for i in range(10)]
    result = _build_post_compact_messages("This is a summary", original, keep_recent=3)
    assert len(result) == 4  # summary + 3 recent
    assert "[Context Summary]" in result[0]["content"]
    assert "This is a summary" in result[0]["content"]
    assert result[1]["content"] == "msg7"
    assert result[3]["content"] == "msg9"


def test_build_post_compact_messages_keep_zero():
    original = [{"role": "user", "content": "a"}]
    result = _build_post_compact_messages("summary", original, keep_recent=0)
    assert len(result) == 1  # just summary
