"""Tests for multi-agent system: spawn, role enforcement, nested streaming."""
import pytest

from agent_runtime.agents.config import MAX_DEPTH, AgentConfig, AgentResult
from agent_runtime.agents.manager import AgentManager, _build_scoped_registry
from agent_runtime.engine.loop import MockModelAdapter, run_query_loop
from agent_runtime.engine.models import ChildEvent, SessionState, TurnConfig
from agent_runtime.provider import AssistantTurn
from agent_runtime.tools.base import ToolRegistry, ToolSpec, registry


async def collect_events(gen) -> list:
    events = []
    async for event in gen:
        events.append(event)
    return events


class TestAgentConfig:
    def test_defaults(self):
        config = AgentConfig(role="research")
        assert config.role == "research"
        assert config.depth == 0
        assert config.agent_id.startswith("agent-")

    def test_frozen(self):
        config = AgentConfig(role="research")
        with pytest.raises(AttributeError):
            config.role = "implementation"  # type: ignore

    def test_unique_ids(self):
        c1 = AgentConfig(role="research")
        c2 = AgentConfig(role="research")
        assert c1.agent_id != c2.agent_id


class TestScopedRegistry:
    def test_filters_tools(self):
        scoped = _build_scoped_registry(["read_file", "grep_search"])
        names = scoped.list_names()
        assert "read_file" in names
        assert "grep_search" in names
        assert "bash" not in names
        assert "write_file" not in names

    def test_empty_allowed(self):
        scoped = _build_scoped_registry([])
        assert scoped.list_names() == []


class TestAgentManagerValidation:
    def test_depth_limit(self):
        mgr = AgentManager()
        config = AgentConfig(role="research", depth=MAX_DEPTH)
        error = mgr.validate_spawn(config)
        assert error is not None
        assert "depth" in error.lower()

    def test_valid_spawn(self):
        mgr = AgentManager()
        config = AgentConfig(role="research", depth=0)
        assert mgr.validate_spawn(config) is None

    def test_verification_cannot_spawn_verification(self):
        mgr = AgentManager()
        config = AgentConfig(role="verification", depth=1)
        error = mgr.validate_spawn(config, parent_role="verification")
        assert error is not None


class TestAgentSpawn:
    @pytest.mark.asyncio
    async def test_spawn_research_agent(self):
        """Spawn a research agent that reads a file."""
        child_adapter = MockModelAdapter([
            AssistantTurn("I found the answer: 42.", [], 10, 5),
        ])

        mgr = AgentManager()
        config = AgentConfig(role="research", depth=0)

        events = await collect_events(
            mgr.spawn("What is the answer?", config, model_adapter=child_adapter)
        )

        # All events should be ChildEvents
        assert all(isinstance(e, ChildEvent) for e in events)
        assert events[0].agent_id == config.agent_id
        assert events[0].role == "research"

        # Should contain text_delta and final from child
        inner_types = [e.inner.type for e in events]
        assert "text_delta" in inner_types
        assert "final" in inner_types

        # Result stored
        result = mgr.get_result(config.agent_id)
        assert result is not None
        assert result.output == "I found the answer: 42."
        assert result.turn_count == 1

    @pytest.mark.asyncio
    async def test_spawn_with_tool_call(self):
        """Child agent uses a tool scoped by role."""
        child_adapter = MockModelAdapter([
            AssistantTurn(
                "Reading...",
                [{"id": "t1", "name": "read_file", "input": {"file_path": "/dev/null"}}],
                10, 5,
            ),
            AssistantTurn("File is empty.", [], 10, 5),
        ])

        mgr = AgentManager()
        config = AgentConfig(role="research", depth=0)

        events = await collect_events(
            mgr.spawn("Read /dev/null", config, model_adapter=child_adapter)
        )

        inner_types = [e.inner.type for e in events]
        assert "tool_call" in inner_types
        assert "tool_result" in inner_types
        assert "final" in inner_types

    @pytest.mark.asyncio
    async def test_spawn_depth_exceeded(self):
        """Spawn at max depth → error event."""
        mgr = AgentManager()
        config = AgentConfig(role="research", depth=MAX_DEPTH)

        events = await collect_events(
            mgr.spawn("do something", config, model_adapter=MockModelAdapter([]))
        )

        assert len(events) == 1
        assert events[0].inner.type == "error"

        result = mgr.get_result(config.agent_id)
        assert result.error != ""

    @pytest.mark.asyncio
    async def test_verification_gets_read_only_tools(self):
        """Verification agent should not have write_file."""
        child_adapter = MockModelAdapter([
            AssistantTurn(
                "Trying to write...",
                [{"id": "t1", "name": "write_file", "input": {"file_path": "x", "content": "y"}}],
                10, 5,
            ),
            AssistantTurn("Write failed as expected.", [], 10, 5),
        ])

        mgr = AgentManager()
        config = AgentConfig(role="verification", depth=0)

        events = await collect_events(
            mgr.spawn("try writing", config, model_adapter=child_adapter)
        )

        # write_file should fail because verification role doesn't have it
        tool_results = [
            e for e in events
            if isinstance(e, ChildEvent)
            and hasattr(e.inner, "type")
            and e.inner.type == "tool_result"
        ]
        assert len(tool_results) == 1
        assert "Unknown tool" in tool_results[0].inner.output


class TestNestedStreaming:
    @pytest.mark.asyncio
    async def test_parent_receives_child_events(self):
        """Parent loop yields ChildEvents when tool_executor returns async gen."""
        # Child adapter
        child_adapter = MockModelAdapter([
            AssistantTurn("Child says hello.", [], 10, 5),
        ])

        mgr = AgentManager()

        # Tool executor that spawns a child
        async def spawn_executor(name, tool_input, state, config):
            if name == "spawn_task":
                child_config = AgentConfig(
                    role=tool_input.get("role", "research"),
                    depth=1,
                )
                # Return async generator of child events
                return mgr.spawn(
                    tool_input["prompt"],
                    child_config,
                    model_adapter=child_adapter,
                )
            return f"Unknown tool: {name}"

        # Parent adapter: model calls spawn_task
        parent_adapter = MockModelAdapter([
            AssistantTurn(
                "Spawning research agent...",
                [{"id": "t1", "name": "spawn_task", "input": {
                    "prompt": "find the answer",
                    "role": "research",
                }}],
                10, 5,
            ),
            AssistantTurn("Child found the answer.", [], 10, 5),
        ])

        state = SessionState()
        config = TurnConfig(max_turns=4)

        events = await collect_events(
            run_query_loop(
                "use a sub-agent", state, config,
                model_adapter=parent_adapter,
                tool_executor=spawn_executor,
                permission_callback=lambda n, i: True,
            )
        )

        types = [e.type for e in events]

        # Should have child events in the stream
        assert "child_event" in types

        # Should still have parent's final
        assert types[-1] == "final"

        # Child events have correct agent_id
        child_events = [e for e in events if e.type == "child_event"]
        assert len(child_events) > 0
        assert child_events[0].role == "research"

    @pytest.mark.asyncio
    async def test_parent_gets_child_result_as_tool_output(self):
        """After child completes, parent receives result as tool_result."""
        child_adapter = MockModelAdapter([
            AssistantTurn("The answer is 42.", [], 10, 5),
        ])

        mgr = AgentManager()

        async def spawn_executor(name, tool_input, state, config):
            if name == "spawn_task":
                child_config = AgentConfig(role="research", depth=1)
                return mgr.spawn(
                    tool_input["prompt"], child_config,
                    model_adapter=child_adapter,
                )
            return "unknown"

        parent_adapter = MockModelAdapter([
            AssistantTurn(
                "",
                [{"id": "t1", "name": "spawn_task", "input": {
                    "prompt": "what is 6*7?",
                    "role": "research",
                }}],
                10, 5,
            ),
            AssistantTurn("Got it: 42.", [], 10, 5),
        ])

        state = SessionState()
        config = TurnConfig(max_turns=4)

        events = await collect_events(
            run_query_loop(
                "ask sub-agent", state, config,
                model_adapter=parent_adapter,
                tool_executor=spawn_executor,
                permission_callback=lambda n, i: True,
            )
        )

        # Find the tool_result for spawn_task
        tool_results = [e for e in events if e.type == "tool_result"]
        assert len(tool_results) == 1
        assert "The answer is 42" in tool_results[0].output
