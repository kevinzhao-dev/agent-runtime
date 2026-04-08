"""Tests for core data models."""
from agent_runtime.models import (
    FinalEvent,
    RecoveryEvent,
    SessionState,
    TextDeltaEvent,
    ThinkingEvent,
    ToolCallEvent,
    ToolResultEvent,
    TurnConfig,
    WorkingMemory,
    assistant_message,
    tool_result_message,
    user_message,
)


class TestEventTypes:
    def test_text_delta_event(self):
        e = TextDeltaEvent(text="hello")
        assert e.type == "text_delta"
        assert e.text == "hello"

    def test_thinking_event(self):
        e = ThinkingEvent(text="reasoning")
        assert e.type == "thinking"

    def test_tool_call_event(self):
        e = ToolCallEvent(tool_call_id="t1", tool_name="bash", tool_input={"cmd": "ls"})
        assert e.type == "tool_call"
        assert e.tool_name == "bash"

    def test_tool_result_event(self):
        e = ToolResultEvent(tool_call_id="t1", tool_name="bash", output="file.txt", status="ok")
        assert e.type == "tool_result"
        assert e.status == "ok"

    def test_recovery_event(self):
        e = RecoveryEvent(reason="context_too_long", detail="compacted")
        assert e.type == "recovery"

    def test_final_event(self):
        e = FinalEvent(text="done")
        assert e.type == "final"

    def test_event_union_type(self):
        """All event types are part of the Event union."""
        events = [
            ThinkingEvent(), TextDeltaEvent(), ToolCallEvent(),
            ToolResultEvent(), RecoveryEvent(), FinalEvent(),
        ]
        for e in events:
            assert hasattr(e, "type")


class TestTurnConfig:
    def test_defaults(self):
        c = TurnConfig()
        assert c.max_turns == 8
        assert c.allow_tools is True
        assert c.model_name == "claude-sonnet-4-6"
        assert c.compact_threshold_tokens == 24_000

    def test_frozen(self):
        c = TurnConfig()
        try:
            c.max_turns = 99  # type: ignore[misc]
            assert False, "Should be frozen"
        except AttributeError:
            pass


class TestWorkingMemory:
    def test_defaults(self):
        wm = WorkingMemory()
        assert wm.task_state == ""
        assert wm.files_touched == []
        assert wm.worklog == []

    def test_mutation(self):
        wm = WorkingMemory()
        wm.task_state = "reading files"
        wm.files_touched.append("main.py")
        assert wm.task_state == "reading files"
        assert wm.files_touched == ["main.py"]


class TestSessionState:
    def test_defaults(self):
        s = SessionState()
        assert len(s.session_id) == 12
        assert s.messages == []
        assert s.turn_count == 0
        assert isinstance(s.working_memory, WorkingMemory)

    def test_unique_session_ids(self):
        s1 = SessionState()
        s2 = SessionState()
        assert s1.session_id != s2.session_id


class TestMessageHelpers:
    def test_user_message(self):
        m = user_message("hello")
        assert m == {"role": "user", "content": "hello"}

    def test_assistant_message_text_only(self):
        m = assistant_message("reply")
        assert m == {"role": "assistant", "content": "reply"}
        assert "tool_calls" not in m

    def test_assistant_message_with_tools(self):
        tc = [{"id": "t1", "name": "bash", "input": {"cmd": "ls"}}]
        m = assistant_message("text", tool_calls=tc)
        assert m["tool_calls"] == tc

    def test_tool_result_message(self):
        m = tool_result_message("t1", "bash", "output")
        assert m["role"] == "tool"
        assert m["tool_call_id"] == "t1"
        assert m["name"] == "bash"
