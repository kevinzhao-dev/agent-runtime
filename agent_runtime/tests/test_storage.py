"""Tests for flat file storage."""
import json

from agent_runtime.models import SessionState, WorkingMemory
from agent_runtime.storage import (
    append_transcript,
    list_sessions,
    load_session,
    save_session,
)
from agent_runtime.tools.base import LedgerEntry


class TestSaveAndLoad:
    def test_roundtrip(self, tmp_path):
        state = SessionState(session_id="test123")
        state.messages = [{"role": "user", "content": "hello"}]
        state.working_memory.task_state = "testing"
        state.working_memory.files_touched = ["a.py"]
        state.total_input_tokens = 100
        state.total_output_tokens = 50
        state.turn_count = 3
        state.compact_summary = "prior work"

        save_session(state, base=tmp_path)
        loaded = load_session("test123", base=tmp_path)

        assert loaded is not None
        assert loaded.session_id == "test123"
        assert loaded.messages == [{"role": "user", "content": "hello"}]
        assert loaded.working_memory.task_state == "testing"
        assert loaded.working_memory.files_touched == ["a.py"]
        assert loaded.total_input_tokens == 100
        assert loaded.total_output_tokens == 50
        assert loaded.turn_count == 3
        assert loaded.compact_summary == "prior work"

    def test_load_nonexistent(self, tmp_path):
        assert load_session("nope", base=tmp_path) is None

    def test_save_with_ledger(self, tmp_path):
        state = SessionState(session_id="led1")
        state.ledger.append(LedgerEntry(
            tool_name="bash",
            tool_input={"cmd": "ls"},
            status="ok",
            started_at=1.0,
            ended_at=2.0,
        ))
        save_session(state, base=tmp_path)
        loaded = load_session("led1", base=tmp_path)
        assert len(loaded.ledger) == 1
        assert loaded.ledger[0]["tool_name"] == "bash"


class TestTranscript:
    def test_append_and_read(self, tmp_path):
        append_transcript("s1", {"type": "text_delta", "text": "hi"}, base=tmp_path)
        append_transcript("s1", {"type": "final", "text": "done"}, base=tmp_path)

        path = tmp_path / "s1" / "transcript.jsonl"
        lines = path.read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["type"] == "text_delta"
        assert json.loads(lines[1])["type"] == "final"


class TestListSessions:
    def test_empty(self, tmp_path):
        assert list_sessions(tmp_path) == []

    def test_list(self, tmp_path):
        s1 = SessionState(session_id="aaa")
        s2 = SessionState(session_id="bbb")
        save_session(s1, base=tmp_path)
        save_session(s2, base=tmp_path)
        sessions = list_sessions(tmp_path)
        assert sessions == ["aaa", "bbb"]
