"""Tests for compaction and recovery paths."""
import pytest

from agent_runtime.compaction import (
    compact,
    estimate_messages_tokens,
    estimate_tokens,
    update_working_memory,
)
from agent_runtime.models import (
    SessionState,
    TurnConfig,
    WorkingMemory,
    assistant_message,
    tool_result_message,
    user_message,
)
from agent_runtime.provider import AssistantTurn
from agent_runtime.query_loop import MockModelAdapter, run_query_loop


async def collect_events(gen) -> list:
    events = []
    async for event in gen:
        events.append(event)
    return events


class TestEstimateTokens:
    def test_simple(self):
        assert estimate_tokens("hello") == int(5 / 3.5)

    def test_empty(self):
        assert estimate_tokens("") == 0


class TestEstimateMessagesTokens:
    def test_simple_messages(self):
        msgs = [user_message("hello world")]
        tokens = estimate_messages_tokens(msgs)
        assert tokens == int(len("hello world") / 3.5)


class TestCompact:
    def _build_long_session(self, n_turns: int = 10) -> SessionState:
        state = SessionState()
        for i in range(n_turns):
            state.messages.append(user_message(f"User message {i}"))
            state.messages.append(assistant_message(f"Response {i}"))
        state.working_memory.task_state = "Testing compaction"
        state.working_memory.files_touched = ["main.py", "utils.py"]
        state.working_memory.worklog = ["step 1", "step 2"]
        return state

    def test_compact_preserves_working_memory(self):
        state = self._build_long_session()
        config = TurnConfig()

        summary = compact(state, config, preserve_recent=4)

        # Working memory should be in the compact message
        assert "Testing compaction" in state.messages[0]["content"]
        assert "main.py" in state.messages[0]["content"]

        # Working memory object unchanged
        assert state.working_memory.task_state == "Testing compaction"
        assert state.working_memory.files_touched == ["main.py", "utils.py"]

    def test_compact_keeps_recent_messages(self):
        state = self._build_long_session(10)
        original_recent = [m["content"] for m in state.messages[-4:]]
        config = TurnConfig()

        compact(state, config, preserve_recent=4)

        # Should have: 1 compact msg + 4 recent = 5 messages
        assert len(state.messages) == 5
        # Recent messages preserved
        for i, msg in enumerate(state.messages[1:]):
            assert msg["content"] == original_recent[i]

    def test_compact_summary_stored(self):
        state = self._build_long_session()
        config = TurnConfig()

        summary = compact(state, config)

        assert summary != ""
        assert state.compact_summary == summary

    def test_compact_no_op_on_short_session(self):
        state = SessionState()
        state.messages = [user_message("hi"), assistant_message("hello")]
        config = TurnConfig()

        compact(state, config, preserve_recent=4)

        # Messages unchanged
        assert len(state.messages) == 2

    def test_compact_summary_contains_old_content(self):
        state = self._build_long_session()
        config = TurnConfig()

        summary = compact(state, config, preserve_recent=2)

        assert "User message" in summary


class TestUpdateWorkingMemory:
    def test_add_file(self):
        wm = WorkingMemory()
        update_working_memory(wm, file_path="main.py")
        assert "main.py" in wm.files_touched

    def test_no_duplicate_files(self):
        wm = WorkingMemory(files_touched=["main.py"])
        update_working_memory(wm, file_path="main.py")
        assert wm.files_touched.count("main.py") == 1

    def test_add_error(self):
        wm = WorkingMemory()
        update_working_memory(wm, error="FileNotFound", correction="Created the file")
        assert "FileNotFound" in wm.errors_and_corrections[0]
        assert "Created the file" in wm.errors_and_corrections[0]

    def test_add_result(self):
        wm = WorkingMemory()
        update_working_memory(wm, result="Found 3 bugs")
        assert "Found 3 bugs" in wm.key_results

    def test_add_worklog(self):
        wm = WorkingMemory()
        update_working_memory(wm, worklog_entry="Read config files")
        assert "Read config files" in wm.worklog


class TestRecoveryPaths:
    @pytest.mark.asyncio
    async def test_context_too_long_triggers_compact(self):
        """When context exceeds threshold, compaction triggers."""
        # Create a mock that generates large tool output
        adapter = MockModelAdapter([
            AssistantTurn(
                "",
                [{"id": "t1", "name": "read_file", "input": {"file_path": "x"}}],
                10, 5,
            ),
            AssistantTurn("Done.", [], 10, 5),
        ])

        def big_output_executor(name, tool_input, state, config):
            return "x" * 100_000  # large output

        state = SessionState()
        config = TurnConfig(
            max_turns=4,
            compact_threshold_tokens=100,  # very low threshold
        )

        compact_called = []

        def compact_handler(s, c):
            compact_called.append(True)
            return compact(s, c)

        events = await collect_events(
            run_query_loop(
                "read big file", state, config,
                model_adapter=adapter,
                tool_executor=big_output_executor,
                permission_callback=lambda n, i: True,
                compact_handler=compact_handler,
            )
        )

        types = [e.type for e in events]
        assert "recovery" in types
        recovery = [e for e in events if e.type == "recovery"]
        assert any(r.reason == "context_too_long" for r in recovery)
        assert len(compact_called) > 0

    @pytest.mark.asyncio
    async def test_tool_failure_recovery_event(self):
        """Tool failure produces recovery event with detail."""
        adapter = MockModelAdapter([
            AssistantTurn(
                "",
                [{"id": "t1", "name": "fail", "input": {}}],
                10, 5,
            ),
            AssistantTurn("That failed.", [], 10, 5),
        ])

        def failing_executor(name, tool_input, state, config):
            raise ValueError("disk full")

        state = SessionState()
        config = TurnConfig(max_turns=4)

        events = await collect_events(
            run_query_loop(
                "do thing", state, config,
                model_adapter=adapter,
                tool_executor=failing_executor,
                permission_callback=lambda n, i: True,
            )
        )

        recovery = [e for e in events if e.type == "recovery"]
        assert len(recovery) == 1
        assert "disk full" in recovery[0].detail

    @pytest.mark.asyncio
    async def test_working_memory_survives_compaction(self):
        """Working memory remains intact after compaction."""
        turns = []
        for i in range(6):
            turns.append(AssistantTurn(
                f"Step {i}",
                [{"id": f"t{i}", "name": "read_file", "input": {"file_path": f"f{i}.py"}}],
                10, 5,
            ))
        turns.append(AssistantTurn("All done.", [], 10, 5))

        adapter = MockModelAdapter(turns)

        def executor(name, tool_input, state, config):
            return "x" * 5000

        state = SessionState()
        state.working_memory.task_state = "Multi-step task"
        state.working_memory.key_results = ["important result"]

        config = TurnConfig(
            max_turns=10,
            compact_threshold_tokens=500,
        )

        def compact_handler(s, c):
            return compact(s, c)

        await collect_events(
            run_query_loop(
                "do many things", state, config,
                model_adapter=adapter,
                tool_executor=executor,
                permission_callback=lambda n, i: True,
                compact_handler=compact_handler,
            )
        )

        # Working memory should survive
        assert state.working_memory.task_state == "Multi-step task"
        assert "important result" in state.working_memory.key_results

    @pytest.mark.asyncio
    async def test_max_turns_is_final(self):
        """Max turns reached → FinalEvent emitted."""
        adapter = MockModelAdapter([
            AssistantTurn(
                "",
                [{"id": f"t{i}", "name": "read_file", "input": {"file_path": "x"}}],
                10, 5,
            )
            for i in range(5)
        ])

        state = SessionState()
        config = TurnConfig(max_turns=2)

        events = await collect_events(
            run_query_loop(
                "loop", state, config,
                model_adapter=adapter,
                tool_executor=lambda n, i, s, c: "ok",
                permission_callback=lambda n, i: True,
            )
        )

        assert events[-1].type == "final"
        assert state.turn_count == 2
