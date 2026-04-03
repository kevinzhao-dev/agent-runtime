"""Tests for engine/state.py — Event types, LoopState, evolve."""

from engine.state import (
    CompactEvent,
    CompactTracking,
    DoneEvent,
    ErrorEvent,
    LoopState,
    TextEvent,
    ToolResultEvent,
    ToolUseEvent,
    TransitionReason,
    evolve,
)


def test_text_event_frozen():
    e = TextEvent(text="hello")
    assert e.text == "hello"


def test_tool_use_event():
    e = ToolUseEvent(tool_name="read_file", tool_id="t1", input={"path": "x"})
    assert e.tool_name == "read_file"
    assert e.input == {"path": "x"}


def test_done_event_default_messages():
    e = DoneEvent(reason="end_turn", turn_count=1)
    assert e.messages == ()


def test_done_event_with_messages():
    msgs = ({"role": "user", "content": "hi"},)
    e = DoneEvent(reason="end_turn", turn_count=1, messages=msgs)
    assert len(e.messages) == 1


def test_transition_reason_values():
    assert TransitionReason.NEXT_TURN.value == "next_turn"
    assert TransitionReason.DONE.value == "done"
    assert TransitionReason.CIRCUIT_BREAK.value == "circuit_break"


def test_loop_state_defaults():
    state = LoopState(messages=())
    assert state.turn_count == 0
    assert state.recovery_attempts == 0
    assert state.compact_tracking.compact_count == 0
    assert state.last_transition is None


def test_evolve_creates_new_state():
    state = LoopState(messages=({"role": "user", "content": "hi"},))
    new = evolve(state, turn_count=1)
    assert new.turn_count == 1
    assert state.turn_count == 0  # original unchanged


def test_evolve_preserves_other_fields():
    state = LoopState(messages=(), turn_count=5, recovery_attempts=2)
    new = evolve(state, turn_count=6)
    assert new.recovery_attempts == 2  # preserved
    assert new.turn_count == 6


def test_evolve_messages():
    state = LoopState(messages=({"role": "user", "content": "a"},))
    new_msg = {"role": "assistant", "content": "b"}
    new = evolve(state, messages=state.messages + (new_msg,))
    assert len(new.messages) == 2
    assert len(state.messages) == 1


def test_compact_tracking_defaults():
    ct = CompactTracking()
    assert ct.compact_count == 0
    assert ct.consecutive_failures == 0
    assert ct.last_compact_token_count == 0
