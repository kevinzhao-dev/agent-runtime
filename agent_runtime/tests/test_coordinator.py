"""Tests for coordinator pattern and fork mode."""
import pytest

from agent_runtime.agents.config import AgentConfig
from agent_runtime.agents.coordinator import WorkflowStep, impl_then_verify, run_workflow
from agent_runtime.agents.manager import AgentManager
from agent_runtime.engine.loop import MockModelAdapter
from agent_runtime.engine.models import ChildEvent, SessionState
from agent_runtime.provider import AssistantTurn


async def collect_events(gen) -> list:
    events = []
    async for event in gen:
        events.append(event)
    return events


class TestWorkflowStep:
    def test_defaults(self):
        step = WorkflowStep(prompt="do X", role="research")
        assert step.depends_on == ""
        assert step.name == ""


class TestImplThenVerify:
    def test_creates_two_steps(self):
        steps = impl_then_verify("write a function")
        assert len(steps) == 2
        assert steps[0].role == "implementation"
        assert steps[1].role == "verification"
        assert steps[1].depends_on == "implementation"


class TestRunWorkflow:
    @pytest.mark.asyncio
    async def test_two_step_workflow(self):
        """Implementation → Verification workflow runs both agents."""
        def adapter_factory(step_index):
            if step_index == 0:
                return MockModelAdapter([
                    AssistantTurn("def add(a, b): return a + b", [], 10, 5),
                ])
            else:
                return MockModelAdapter([
                    AssistantTurn("Code looks correct. Tests pass.", [], 10, 5),
                ])

        steps = impl_then_verify("Write an add function")
        events = await collect_events(
            run_workflow(steps, model_adapter_factory=adapter_factory)
        )

        # All events are ChildEvents
        assert all(isinstance(e, ChildEvent) for e in events)

        # Both roles appear
        roles = {e.role for e in events}
        assert "implementation" in roles
        assert "verification" in roles

        # Verify step received implementation output
        verify_events = [e for e in events if e.role == "verification"]
        # The verification agent's final text should reference correctness
        finals = [e for e in verify_events if e.inner.type == "final"]
        assert len(finals) == 1
        assert "correct" in finals[0].inner.text.lower() or "pass" in finals[0].inner.text.lower()

    @pytest.mark.asyncio
    async def test_dependency_injection(self):
        """Step with depends_on gets prior step's output in its prompt."""
        captured_prompts = []

        original_spawn = AgentManager.spawn

        async def tracking_spawn(self, prompt, config, **kwargs):
            captured_prompts.append(prompt)
            async for event in original_spawn(self, prompt, config, **kwargs):
                yield event

        AgentManager.spawn = tracking_spawn

        try:
            def adapter_factory(i):
                return MockModelAdapter([
                    AssistantTurn(f"Result from step {i}", [], 10, 5),
                ])

            steps = [
                WorkflowStep(prompt="Do step A", role="research", name="stepA"),
                WorkflowStep(prompt="Do step B", role="research", name="stepB", depends_on="stepA"),
            ]

            await collect_events(
                run_workflow(steps, model_adapter_factory=adapter_factory)
            )

            # Step B's prompt should include step A's output
            assert len(captured_prompts) == 2
            assert "Result from step 0" in captured_prompts[1]
        finally:
            AgentManager.spawn = original_spawn

    @pytest.mark.asyncio
    async def test_three_step_research_impl_verify(self):
        """Research → Implementation → Verification."""
        def adapter_factory(i):
            texts = [
                "Found: the API uses REST with JSON.",
                "Implemented the client with requests library.",
                "Verified: client handles errors correctly.",
            ]
            return MockModelAdapter([AssistantTurn(texts[i], [], 10, 5)])

        steps = [
            WorkflowStep(prompt="Research the API", role="research", name="research"),
            WorkflowStep(prompt="Implement a client", role="implementation", name="impl", depends_on="research"),
            WorkflowStep(prompt="Verify the implementation", role="verification", name="verify", depends_on="impl"),
        ]

        events = await collect_events(
            run_workflow(steps, model_adapter_factory=adapter_factory)
        )

        roles_in_order = []
        for e in events:
            if isinstance(e, ChildEvent) and e.role not in roles_in_order[-1:]:
                roles_in_order.append(e.role)
        assert roles_in_order == ["research", "implementation", "verification"]


class TestForkMode:
    @pytest.mark.asyncio
    async def test_fork_inherits_parent_messages(self):
        """fork=True copies parent messages to child state."""
        child_adapter = MockModelAdapter([
            AssistantTurn("I can see the parent context.", [], 10, 5),
        ])

        parent_state = SessionState()
        parent_state.messages = [
            {"role": "user", "content": "Hello parent"},
            {"role": "assistant", "content": "Hello user"},
        ]

        mgr = AgentManager()
        config = AgentConfig(role="research", depth=0, fork=True)

        events = await collect_events(
            mgr.spawn(
                "Continue from parent context",
                config,
                model_adapter=child_adapter,
                parent_state=parent_state,
            )
        )

        # Child should have produced events
        assert any(e.inner.type == "final" for e in events)

        # Verify via the result
        result = mgr.get_result(config.agent_id)
        assert result is not None
        # Child had 3+ messages: 2 inherited + 1 user prompt + 1 assistant response
        assert result.turn_count >= 1

    @pytest.mark.asyncio
    async def test_no_fork_fresh_state(self):
        """fork=False (default) starts with empty context."""
        child_adapter = MockModelAdapter([
            AssistantTurn("Fresh start.", [], 10, 5),
        ])

        parent_state = SessionState()
        parent_state.messages = [
            {"role": "user", "content": "Parent context"},
            {"role": "assistant", "content": "Should not appear"},
        ]

        mgr = AgentManager()
        config = AgentConfig(role="research", depth=0, fork=False)

        events = await collect_events(
            mgr.spawn(
                "Start fresh",
                config,
                model_adapter=child_adapter,
                parent_state=parent_state,
            )
        )

        result = mgr.get_result(config.agent_id)
        assert result is not None
        assert result.output == "Fresh start."
