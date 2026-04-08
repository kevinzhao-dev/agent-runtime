"""Tests for async multi-agent: background spawn, check, abort, lifecycle tools."""
import asyncio

import pytest

from agent_runtime.agents.config import AgentConfig, AgentResult
from agent_runtime.agents.manager import AgentManager
from agent_runtime.engine.loop import MockModelAdapter, run_query_loop
from agent_runtime.engine.models import SessionState, TurnConfig
from agent_runtime.provider import AssistantTurn
from agent_runtime.tools.spawn_task import create_spawn_executor


async def collect_events(gen) -> list:
    events = []
    async for event in gen:
        events.append(event)
    return events


class TestBackgroundSpawn:
    @pytest.mark.asyncio
    async def test_spawn_background_returns_immediately(self):
        """spawn_background returns agent_id without waiting for completion."""
        child_adapter = MockModelAdapter([
            AssistantTurn("Background result.", [], 10, 5),
        ])
        mgr = AgentManager()
        config = AgentConfig(role="research", depth=0)

        agent_id = await mgr.spawn_background(
            "do research", config, model_adapter=child_adapter,
        )

        assert agent_id == config.agent_id
        # Give the task time to complete
        await asyncio.sleep(0.1)

        result = mgr.get_result(agent_id)
        assert result is not None
        assert result.output == "Background result."

    @pytest.mark.asyncio
    async def test_check_agent_running(self):
        """check_agent reports 'running' while agent is executing."""
        # Create a slow adapter
        child_adapter = MockModelAdapter([
            AssistantTurn(
                "",
                [{"id": "t1", "name": "read_file", "input": {"file_path": "/dev/null"}}],
                10, 5,
            ),
            AssistantTurn("Done.", [], 10, 5),
        ])
        mgr = AgentManager()
        config = AgentConfig(role="research", depth=0)

        agent_id = await mgr.spawn_background(
            "slow task", config, model_adapter=child_adapter,
        )

        # Immediately check — may still be running or just completed
        status = mgr.check_agent(agent_id)
        assert status["agent_id"] == agent_id
        assert status["status"] in ("running", "completed")

        # Wait and check again
        await asyncio.sleep(0.2)
        status = mgr.check_agent(agent_id)
        assert status["status"] == "completed"

    @pytest.mark.asyncio
    async def test_check_agent_not_found(self):
        mgr = AgentManager()
        status = mgr.check_agent("nonexistent")
        assert status["status"] == "not_found"

    @pytest.mark.asyncio
    async def test_abort_agent(self):
        """Abort sets cancel flag, agent reports aborted."""
        # Agent that would run many turns
        turns = [
            AssistantTurn(
                f"Step {i}",
                [{"id": f"t{i}", "name": "read_file", "input": {"file_path": "/dev/null"}}],
                10, 5,
            )
            for i in range(10)
        ]
        turns.append(AssistantTurn("Done.", [], 10, 5))
        child_adapter = MockModelAdapter(turns)

        mgr = AgentManager()
        config = AgentConfig(role="research", depth=0, max_turns=10)

        agent_id = await mgr.spawn_background(
            "long task", config, model_adapter=child_adapter,
        )

        # Abort immediately
        msg = mgr.abort_agent(agent_id)
        assert "Abort" in msg

        await asyncio.sleep(0.2)
        result = mgr.get_result(agent_id)
        assert result is not None
        assert result.error == "aborted"

    @pytest.mark.asyncio
    async def test_abort_nonexistent(self):
        mgr = AgentManager()
        msg = mgr.abort_agent("ghost")
        assert "not found" in msg

    @pytest.mark.asyncio
    async def test_list_agents(self):
        child_adapter = MockModelAdapter([
            AssistantTurn("Done.", [], 10, 5),
        ])
        mgr = AgentManager()

        c1 = AgentConfig(role="research", depth=0)
        c2 = AgentConfig(role="verification", depth=0)

        await mgr.spawn_background("task 1", c1, model_adapter=child_adapter)
        await mgr.spawn_background("task 2", c2, model_adapter=MockModelAdapter([
            AssistantTurn("Also done.", [], 10, 5),
        ]))

        await asyncio.sleep(0.2)
        agents = mgr.list_agents()
        assert len(agents) == 2
        ids = {a["agent_id"] for a in agents}
        assert c1.agent_id in ids
        assert c2.agent_id in ids

    @pytest.mark.asyncio
    async def test_depth_exceeded_background(self):
        mgr = AgentManager()
        config = AgentConfig(role="research", depth=3)

        agent_id = await mgr.spawn_background("fail", config)
        result = mgr.get_result(agent_id)
        assert result is not None
        assert result.error != ""


class TestSpawnExecutorIntegration:
    @pytest.mark.asyncio
    async def test_background_spawn_via_executor(self):
        """Model calls spawn_task with wait=false → gets agent_id back."""
        child_adapter = MockModelAdapter([
            AssistantTurn("Background answer.", [], 10, 5),
        ])

        executor, mgr = create_spawn_executor()

        # Manually inject mock adapter for child spawns
        _original_spawn_bg = mgr.spawn_background

        async def patched_spawn_bg(prompt, config, **kw):
            return await _original_spawn_bg(prompt, config, model_adapter=child_adapter, **kw)

        mgr.spawn_background = patched_spawn_bg

        parent_adapter = MockModelAdapter([
            AssistantTurn(
                "Spawning background agent...",
                [{"id": "t1", "name": "spawn_task", "input": {
                    "prompt": "research in background",
                    "role": "research",
                    "wait": False,
                }}],
                10, 5,
            ),
            AssistantTurn(
                "Let me check...",
                [{"id": "t2", "name": "check_agent", "input": {
                    "agent_id": "",  # will be filled by examining events
                }}],
                10, 5,
            ),
            AssistantTurn("All done.", [], 10, 5),
        ])

        state = SessionState()
        config = TurnConfig(max_turns=6)

        events = await collect_events(
            run_query_loop(
                "use background agent", state, config,
                model_adapter=parent_adapter,
                tool_executor=executor,
                permission_callback=lambda n, i: True,
            )
        )

        # First tool_result should contain "spawned in background"
        tool_results = [e for e in events if e.type == "tool_result"]
        assert any("spawned in background" in tr.output for tr in tool_results)

    @pytest.mark.asyncio
    async def test_list_agents_via_executor(self):
        """Model calls list_agents tool."""
        executor, mgr = create_spawn_executor()

        parent_adapter = MockModelAdapter([
            AssistantTurn(
                "",
                [{"id": "t1", "name": "list_agents", "input": {}}],
                10, 5,
            ),
            AssistantTurn("No agents running.", [], 10, 5),
        ])

        state = SessionState()
        config = TurnConfig(max_turns=4)

        events = await collect_events(
            run_query_loop(
                "list agents", state, config,
                model_adapter=parent_adapter,
                tool_executor=executor,
                permission_callback=lambda n, i: True,
            )
        )

        tool_results = [e for e in events if e.type == "tool_result"]
        assert len(tool_results) == 1
        assert "[]" in tool_results[0].output  # empty list


class TestSpawnTaskToolRegistered:
    def test_spawn_task_in_registry(self):
        from agent_runtime.tools import registry
        assert registry.get("spawn_task") is not None

    def test_check_agent_in_registry(self):
        from agent_runtime.tools import registry
        assert registry.get("check_agent") is not None

    def test_abort_agent_in_registry(self):
        from agent_runtime.tools import registry
        assert registry.get("abort_agent") is not None

    def test_list_agents_in_registry(self):
        from agent_runtime.tools import registry
        assert registry.get("list_agents") is not None
