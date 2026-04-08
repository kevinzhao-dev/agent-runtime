"""Tests for the core query loop using mock model adapter."""
import pytest

from agent_runtime.models import (
    FinalEvent,
    RecoveryEvent,
    SessionState,
    TextDeltaEvent,
    ToolCallEvent,
    ToolResultEvent,
    TurnConfig,
)
from agent_runtime.provider import AssistantTurn
from agent_runtime.query_loop import (
    MockModelAdapter,
    estimate_tokens,
    run_query_loop,
    should_compact,
)


async def collect_events(gen) -> list:
    """Collect all events from an async generator."""
    events = []
    async for event in gen:
        events.append(event)
    return events


class TestEstimateTokens:
    def test_simple_text(self):
        msgs = [{"role": "user", "content": "hello world"}]
        tokens = estimate_tokens(msgs)
        assert tokens == int(len("hello world") / 3.5)

    def test_empty(self):
        assert estimate_tokens([]) == 0

    def test_list_content(self):
        msgs = [{"role": "user", "content": [{"text": "hello"}]}]
        tokens = estimate_tokens(msgs)
        assert tokens > 0


class TestShouldCompact:
    def test_below_threshold(self):
        state = SessionState()
        state.messages = [{"role": "user", "content": "short"}]
        config = TurnConfig(compact_threshold_tokens=1000)
        assert should_compact(state, config) is False

    def test_above_threshold(self):
        state = SessionState()
        state.messages = [{"role": "user", "content": "x" * 10000}]
        config = TurnConfig(compact_threshold_tokens=100)
        assert should_compact(state, config) is True


class TestMockModelAdapter:
    def test_yields_text_chunk_then_turn(self):
        turn = AssistantTurn("hello", [], 10, 5)
        adapter = MockModelAdapter([turn])
        chunks = list(adapter.stream("model", "", []))
        assert len(chunks) == 2  # TextChunk + AssistantTurn

    def test_exhausted_turns(self):
        adapter = MockModelAdapter([])
        chunks = list(adapter.stream("model", "", []))
        assert len(chunks) == 1  # fallback AssistantTurn


class TestQueryLoopSingleTurn:
    @pytest.mark.asyncio
    async def test_simple_response(self):
        """Model responds with text, no tool calls → FinalEvent."""
        adapter = MockModelAdapter([
            AssistantTurn("Hello!", [], 10, 5),
        ])
        state = SessionState()
        config = TurnConfig(max_turns=4)

        events = await collect_events(
            run_query_loop("Hi", state, config, model_adapter=adapter)
        )

        types = [e.type for e in events]
        assert "text_delta" in types
        assert types[-1] == "final"
        assert events[-1].text == "Hello!"
        assert state.turn_count == 1
        assert len(state.messages) == 2  # user + assistant

    @pytest.mark.asyncio
    async def test_token_counts_updated(self):
        adapter = MockModelAdapter([
            AssistantTurn("ok", [], 100, 50),
        ])
        state = SessionState()
        config = TurnConfig()

        await collect_events(
            run_query_loop("test", state, config, model_adapter=adapter)
        )

        assert state.total_input_tokens == 100
        assert state.total_output_tokens == 50


class TestQueryLoopWithTools:
    @pytest.mark.asyncio
    async def test_tool_call_and_result(self):
        """Model calls a tool, gets result, then responds with text."""
        adapter = MockModelAdapter([
            # Turn 1: model requests a tool
            AssistantTurn(
                "Let me read that file.",
                [{"id": "t1", "name": "read_file", "input": {"path": "a.py"}}],
                10, 5,
            ),
            # Turn 2: model responds with final text
            AssistantTurn("The file contains hello.", [], 10, 5),
        ])

        def mock_executor(name, tool_input, state, config):
            return "hello world"

        state = SessionState()
        config = TurnConfig(max_turns=4)

        events = await collect_events(
            run_query_loop("Read a.py", state, config,
                           model_adapter=adapter, tool_executor=mock_executor)
        )

        types = [e.type for e in events]
        assert "tool_call" in types
        assert "tool_result" in types
        assert types[-1] == "final"

        # Check tool events
        tc_event = next(e for e in events if e.type == "tool_call")
        assert tc_event.tool_name == "read_file"

        tr_event = next(e for e in events if e.type == "tool_result")
        assert tr_event.output == "hello world"
        assert tr_event.status == "ok"

    @pytest.mark.asyncio
    async def test_tool_failure_recovery(self):
        """Tool executor raises → recovery event + error status."""
        adapter = MockModelAdapter([
            AssistantTurn(
                "",
                [{"id": "t1", "name": "bash", "input": {"cmd": "rm -rf /"}}],
                10, 5,
            ),
            AssistantTurn("OK, that failed.", [], 10, 5),
        ])

        def failing_executor(name, tool_input, state, config):
            raise RuntimeError("Permission denied")

        state = SessionState()
        config = TurnConfig(max_turns=4)

        events = await collect_events(
            run_query_loop("delete everything", state, config,
                           model_adapter=adapter, tool_executor=failing_executor)
        )

        types = [e.type for e in events]
        assert "recovery" in types

        recovery = next(e for e in events if e.type == "recovery")
        assert recovery.reason == "tool_failure"

        tr_event = next(e for e in events if e.type == "tool_result")
        assert tr_event.status == "error"


class TestQueryLoopMultiTurn:
    @pytest.mark.asyncio
    async def test_multi_tool_turns(self):
        """Model calls tools across multiple turns."""
        adapter = MockModelAdapter([
            AssistantTurn(
                "Reading...",
                [{"id": "t1", "name": "read_file", "input": {"path": "a.py"}}],
                10, 5,
            ),
            AssistantTurn(
                "Searching...",
                [{"id": "t2", "name": "grep_search", "input": {"pattern": "def"}}],
                10, 5,
            ),
            AssistantTurn("Found 3 functions.", [], 10, 5),
        ])

        def mock_executor(name, tool_input, state, config):
            return f"result of {name}"

        state = SessionState()
        config = TurnConfig(max_turns=8)

        events = await collect_events(
            run_query_loop("find functions", state, config,
                           model_adapter=adapter, tool_executor=mock_executor)
        )

        tool_calls = [e for e in events if e.type == "tool_call"]
        assert len(tool_calls) == 2
        assert tool_calls[0].tool_name == "read_file"
        assert tool_calls[1].tool_name == "grep_search"
        assert state.turn_count == 3

    @pytest.mark.asyncio
    async def test_max_turns_limit(self):
        """Loop stops at max_turns even if model keeps requesting tools."""
        adapter = MockModelAdapter([
            AssistantTurn("", [{"id": f"t{i}", "name": "bash", "input": {"cmd": "ls"}}], 10, 5)
            for i in range(10)
        ])

        def mock_executor(name, tool_input, state, config):
            return "ok"

        state = SessionState()
        config = TurnConfig(max_turns=3)

        events = await collect_events(
            run_query_loop("loop forever", state, config,
                           model_adapter=adapter, tool_executor=mock_executor)
        )

        assert state.turn_count == 3
        assert events[-1].type == "final"


class TestQueryLoopEventOrdering:
    @pytest.mark.asyncio
    async def test_event_order_with_tool(self):
        """Events should follow: text_delta → tool_call → tool_result → ... → final."""
        adapter = MockModelAdapter([
            AssistantTurn(
                "Let me check.",
                [{"id": "t1", "name": "read_file", "input": {"path": "x"}}],
                10, 5,
            ),
            AssistantTurn("Done.", [], 10, 5),
        ])

        def mock_executor(name, tool_input, state, config):
            return "content"

        state = SessionState()
        config = TurnConfig()

        events = await collect_events(
            run_query_loop("check x", state, config,
                           model_adapter=adapter, tool_executor=mock_executor)
        )

        types = [e.type for e in events]
        # First turn: text_delta, tool_call, tool_result
        # Second turn: text_delta, final
        td_idx = types.index("text_delta")
        tc_idx = types.index("tool_call")
        tr_idx = types.index("tool_result")
        final_idx = types.index("final")
        assert td_idx < tc_idx < tr_idx < final_idx
