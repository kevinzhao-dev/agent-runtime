"""End-to-end acceptance tests using mock model adapter.

These tests verify the full system integration without real API calls.
"""
import pytest

from agent_runtime.engine.compaction import compact
from agent_runtime.engine.models import SessionState, TurnConfig
from agent_runtime.provider import AssistantTurn
from agent_runtime.engine.loop import MockModelAdapter, run_query_loop


async def collect_events(gen) -> list:
    events = []
    async for event in gen:
        events.append(event)
    return events


class TestAT1_ToolCallAtTurn2:
    """AT1: Model requests read_file at turn 2 → ledger entry, loop continues."""

    @pytest.mark.asyncio
    async def test_tool_at_turn_2(self, tmp_path):
        f = tmp_path / "config.py"
        f.write_text("DEBUG = True\n")

        adapter = MockModelAdapter([
            # Turn 1: model responds with text only
            AssistantTurn("Let me look at the project.", [], 10, 5),
        ])
        state = SessionState()
        config = TurnConfig(max_turns=8)

        # First query — no tools
        events = await collect_events(
            run_query_loop("What's in this project?", state, config, model_adapter=adapter)
        )
        assert events[-1].type == "final"

        # Second query — with tool call
        adapter2 = MockModelAdapter([
            AssistantTurn(
                "Reading config...",
                [{"id": "t1", "name": "read_file", "input": {"file_path": str(f)}}],
                10, 5,
            ),
            AssistantTurn("DEBUG is True.", [], 10, 5),
        ])

        events2 = await collect_events(
            run_query_loop("Read config.py", state, config, model_adapter=adapter2)
        )

        # Verify
        assert len(state.ledger) == 1
        assert state.ledger[0].tool_name == "read_file"
        assert state.ledger[0].status == "ok"
        assert events2[-1].type == "final"
        assert state.turn_count == 3  # turn 1 + turn 2 (tool) + turn 3 (response)


class TestAT2_CompactionWithWorkingMemory:
    """AT2: Context exceeds threshold → compact, working memory preserved."""

    @pytest.mark.asyncio
    async def test_compaction_preserves_working_memory(self):
        adapter = MockModelAdapter([
            AssistantTurn(
                "",
                [{"id": "t1", "name": "read_file", "input": {"file_path": "x"}}],
                10, 5,
            ),
            AssistantTurn("Done reading.", [], 10, 5),
        ])

        def large_executor(name, tool_input, state, config):
            return "x" * 50_000

        state = SessionState()
        state.working_memory.task_state = "Important task"
        state.working_memory.key_results = ["Critical finding"]
        config = TurnConfig(max_turns=4, compact_threshold_tokens=200)

        events = await collect_events(
            run_query_loop(
                "read large file", state, config,
                model_adapter=adapter,
                tool_executor=large_executor,
                permission_callback=lambda n, i: True,
                compact_handler=compact,
            )
        )

        # Working memory intact
        assert state.working_memory.task_state == "Important task"
        assert "Critical finding" in state.working_memory.key_results

        # Recovery event was emitted
        recovery_events = [e for e in events if e.type == "recovery"]
        assert any(r.reason == "context_too_long" for r in recovery_events)


class TestAT4_LongSession:
    """AT4: 10+ turn session → at least one compaction, task completes."""

    @pytest.mark.asyncio
    async def test_10_turn_session(self):
        turns = []
        for i in range(10):
            turns.append(AssistantTurn(
                f"Step {i}",
                [{"id": f"t{i}", "name": "read_file", "input": {"file_path": f"f{i}"}}],
                10, 5,
            ))
        turns.append(AssistantTurn("All 10 steps complete.", [], 10, 5))

        adapter = MockModelAdapter(turns)

        def executor(name, tool_input, state, config):
            return "data " * 500  # moderate output

        state = SessionState()
        state.working_memory.task_state = "10-step task"
        config = TurnConfig(
            max_turns=15,
            compact_threshold_tokens=500,  # low to trigger compaction
        )

        compact_count = []

        def counting_compact(s, c):
            compact_count.append(True)
            return compact(s, c)

        events = await collect_events(
            run_query_loop(
                "do 10 things", state, config,
                model_adapter=adapter,
                tool_executor=executor,
                permission_callback=lambda n, i: True,
                compact_handler=counting_compact,
            )
        )

        # Task completed
        assert events[-1].type == "final"
        assert "complete" in events[-1].text.lower()

        # At least one compaction occurred
        assert len(compact_count) >= 1

        # Working memory survived
        assert state.working_memory.task_state == "10-step task"

        # Turn count is correct (10 tool turns + 1 final)
        assert state.turn_count == 11


class TestAT6_MalformedToolCall:
    """AT6: Model emits malformed tool call → recovery, no crash."""

    @pytest.mark.asyncio
    async def test_unknown_tool_no_crash(self):
        """Model requests a nonexistent tool → error handled gracefully."""
        adapter = MockModelAdapter([
            AssistantTurn(
                "Calling unknown tool.",
                [{"id": "t1", "name": "nonexistent_tool", "input": {"bad": "data"}}],
                10, 5,
            ),
            AssistantTurn("OK, that didn't work.", [], 10, 5),
        ])

        state = SessionState()
        config = TurnConfig(max_turns=4)

        events = await collect_events(
            run_query_loop(
                "do something", state, config,
                model_adapter=adapter,
                permission_callback=lambda n, i: True,
            )
        )

        # No crash — loop completed
        assert events[-1].type == "final"

        # Error in ledger
        assert len(state.ledger) == 1
        assert state.ledger[0].status == "error"

        # Recovery event emitted
        recovery = [e for e in events if e.type == "recovery"]
        assert len(recovery) == 1
        assert "nonexistent_tool" in recovery[0].detail


class TestMultiToolWorkflow:
    """Multi-tool workflow: read → grep → write."""

    @pytest.mark.asyncio
    async def test_read_grep_write(self, tmp_path):
        src = tmp_path / "src.py"
        src.write_text("def hello():\n    print('hello')\n\ndef world():\n    pass\n")

        adapter = MockModelAdapter([
            # Step 1: read
            AssistantTurn(
                "Reading source...",
                [{"id": "t1", "name": "read_file", "input": {"file_path": str(src)}}],
                10, 5,
            ),
            # Step 2: grep
            AssistantTurn(
                "Searching for functions...",
                [{"id": "t2", "name": "grep_search", "input": {
                    "pattern": "def \\w+",
                    "path": str(tmp_path),
                }}],
                10, 5,
            ),
            # Step 3: write result
            AssistantTurn(
                "Writing summary...",
                [{"id": "t3", "name": "write_file", "input": {
                    "file_path": str(tmp_path / "summary.txt"),
                    "content": "Found 2 functions: hello, world",
                }}],
                10, 5,
            ),
            # Final
            AssistantTurn("Done! Found 2 functions.", [], 10, 5),
        ])

        state = SessionState()
        config = TurnConfig(max_turns=8)

        events = await collect_events(
            run_query_loop("find all functions", state, config, model_adapter=adapter)
        )

        # All tools executed
        assert len(state.ledger) == 3
        assert all(e.status == "ok" for e in state.ledger)

        # File was written
        summary = (tmp_path / "summary.txt").read_text()
        assert "2 functions" in summary

        # Final event
        assert events[-1].type == "final"
