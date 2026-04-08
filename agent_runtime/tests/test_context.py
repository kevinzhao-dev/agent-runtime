"""Tests for the context assembler."""
from agent_runtime.prompt.context import build_task_context, format_working_memory
from agent_runtime.engine.models import SessionState, WorkingMemory
from agent_runtime.tools.base import LedgerEntry


class TestFormatWorkingMemory:
    def test_empty(self):
        wm = WorkingMemory()
        assert format_working_memory(wm) == ""

    def test_with_task_state(self):
        wm = WorkingMemory(task_state="Reading config files")
        result = format_working_memory(wm)
        assert "Reading config files" in result

    def test_with_all_fields(self):
        wm = WorkingMemory(
            task_state="Fixing bug",
            files_touched=["main.py", "utils.py"],
            errors_and_corrections=["TypeError fixed"],
            key_results=["Found root cause"],
            worklog=["Read main.py", "Found bug", "Applied fix"],
        )
        result = format_working_memory(wm)
        assert "main.py" in result
        assert "TypeError" in result
        assert "root cause" in result
        assert "Applied fix" in result

    def test_worklog_limited_to_recent(self):
        wm = WorkingMemory(worklog=[f"step {i}" for i in range(20)])
        result = format_working_memory(wm)
        assert "step 19" in result
        assert "step 10" in result
        # step 0-9 should be excluded (only last 10)
        assert "step 0\n" not in result


class TestBuildTaskContext:
    def test_empty_state(self):
        state = SessionState()
        result = build_task_context(state)
        assert result == ""

    def test_with_working_memory(self):
        state = SessionState()
        state.working_memory.task_state = "Testing"
        result = build_task_context(state)
        assert "Working Memory" in result
        assert "Testing" in result

    def test_with_topic_content(self):
        state = SessionState()
        result = build_task_context(state, topic_content="OAuth2 details here")
        assert "Loaded Topics" in result
        assert "OAuth2" in result

    def test_with_ledger(self):
        state = SessionState()
        state.ledger.append(LedgerEntry(
            tool_name="read_file",
            tool_input={"file_path": "test.py"},
            status="ok",
            summary="Read 50 lines",
        ))
        result = build_task_context(state)
        assert "Recent Tool Results" in result
        assert "read_file: ok" in result

    def test_with_compact_summary(self):
        state = SessionState()
        state.compact_summary = "Previously read 3 files and fixed a bug."
        result = build_task_context(state)
        assert "Prior Context Summary" in result
        assert "fixed a bug" in result
