"""Integration tests: tools wired into query loop with ledger and permissions."""
import pytest

from agent_runtime.models import SessionState, TurnConfig
from agent_runtime.provider import AssistantTurn
from agent_runtime.query_loop import MockModelAdapter, run_query_loop


async def collect_events(gen) -> list:
    events = []
    async for event in gen:
        events.append(event)
    return events


class TestLoopWithRegistry:
    @pytest.mark.asyncio
    async def test_read_file_via_registry(self, tmp_path):
        """Tool executed via registry produces ledger entry."""
        f = tmp_path / "test.txt"
        f.write_text("hello world")

        adapter = MockModelAdapter([
            AssistantTurn(
                "Reading file.",
                [{"id": "t1", "name": "read_file", "input": {"file_path": str(f)}}],
                10, 5,
            ),
            AssistantTurn("File says hello world.", [], 10, 5),
        ])

        state = SessionState()
        config = TurnConfig(max_turns=4)

        events = await collect_events(
            run_query_loop("read test.txt", state, config, model_adapter=adapter)
        )

        # Ledger should have one entry
        assert len(state.ledger) == 1
        assert state.ledger[0].tool_name == "read_file"
        assert state.ledger[0].status == "ok"

        # Tool result should contain file content
        tr = next(e for e in events if e.type == "tool_result")
        assert "hello world" in tr.output

    @pytest.mark.asyncio
    async def test_bash_denied_by_default_permission(self):
        """bash is high-risk → denied by default auto-permission."""
        adapter = MockModelAdapter([
            AssistantTurn(
                "",
                [{"id": "t1", "name": "bash", "input": {"command": "ls"}}],
                10, 5,
            ),
            AssistantTurn("OK, bash was denied.", [], 10, 5),
        ])

        state = SessionState()
        config = TurnConfig(max_turns=4)

        events = await collect_events(
            run_query_loop("run ls", state, config, model_adapter=adapter)
        )

        tr = next(e for e in events if e.type == "tool_result")
        assert "Permission denied" in tr.output
        assert tr.status == "error"

    @pytest.mark.asyncio
    async def test_bash_allowed_with_custom_permission(self):
        """Custom permission callback can allow bash."""
        adapter = MockModelAdapter([
            AssistantTurn(
                "",
                [{"id": "t1", "name": "bash", "input": {"command": "echo hi"}}],
                10, 5,
            ),
            AssistantTurn("Done.", [], 10, 5),
        ])

        state = SessionState()
        config = TurnConfig(max_turns=4)

        events = await collect_events(
            run_query_loop(
                "echo hi", state, config,
                model_adapter=adapter,
                permission_callback=lambda name, inp: True,  # allow all
            )
        )

        tr = next(e for e in events if e.type == "tool_result")
        assert "hi" in tr.output
        assert tr.status == "ok"
        assert len(state.ledger) == 1
        assert state.ledger[0].status == "ok"

    @pytest.mark.asyncio
    async def test_unknown_tool_produces_error_ledger(self):
        """Unknown tool name → error in ledger."""
        adapter = MockModelAdapter([
            AssistantTurn(
                "",
                [{"id": "t1", "name": "nonexistent_tool", "input": {}}],
                10, 5,
            ),
            AssistantTurn("That tool doesn't exist.", [], 10, 5),
        ])

        state = SessionState()
        config = TurnConfig(max_turns=4)

        events = await collect_events(
            run_query_loop(
                "use unknown tool", state, config,
                model_adapter=adapter,
                permission_callback=lambda n, i: True,
            )
        )

        assert len(state.ledger) == 1
        assert state.ledger[0].status == "error"
        assert "Unknown tool" in state.ledger[0].error

    @pytest.mark.asyncio
    async def test_multiple_tools_multiple_ledger_entries(self, tmp_path):
        """Multiple tool calls → multiple ledger entries."""
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("aaa")
        f2.write_text("bbb")

        adapter = MockModelAdapter([
            AssistantTurn(
                "Reading both files.",
                [
                    {"id": "t1", "name": "read_file", "input": {"file_path": str(f1)}},
                    {"id": "t2", "name": "read_file", "input": {"file_path": str(f2)}},
                ],
                10, 5,
            ),
            AssistantTurn("Both read.", [], 10, 5),
        ])

        state = SessionState()
        config = TurnConfig(max_turns=4)

        await collect_events(
            run_query_loop("read both", state, config, model_adapter=adapter)
        )

        assert len(state.ledger) == 2
        assert all(e.status == "ok" for e in state.ledger)

    @pytest.mark.asyncio
    async def test_legacy_tool_executor_still_works(self):
        """Legacy tool_executor callable is still supported."""
        adapter = MockModelAdapter([
            AssistantTurn(
                "",
                [{"id": "t1", "name": "custom", "input": {"x": 1}}],
                10, 5,
            ),
            AssistantTurn("Done.", [], 10, 5),
        ])

        def legacy(name, tool_input, state, config):
            return f"legacy:{name}"

        state = SessionState()
        config = TurnConfig(max_turns=4)

        events = await collect_events(
            run_query_loop(
                "test", state, config,
                model_adapter=adapter,
                tool_executor=legacy,
                permission_callback=lambda n, i: True,
            )
        )

        tr = next(e for e in events if e.type == "tool_result")
        assert tr.output == "legacy:custom"
        assert len(state.ledger) == 1
