"""Coordinator pattern — orchestrate multi-agent workflows.

A coordinator is a synthesis-role agent that spawns workers,
collects results, and synthesizes a final output.
It does NOT just forward — it understands and integrates.

Provides high-level workflow primitives built on AgentManager.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

from agent_runtime.agents.config import AgentConfig, AgentResult
from agent_runtime.agents.manager import AgentManager
from agent_runtime.engine.loop import MockModelAdapter
from agent_runtime.engine.models import ChildEvent, Event


@dataclass(slots=True)
class WorkflowStep:
    """A single step in a coordinated workflow."""
    prompt: str
    role: str  # RoleName
    name: str = ""  # human-readable label
    depends_on: str = ""  # name of prior step whose output feeds into this one


async def run_workflow(
    steps: list[WorkflowStep],
    manager: AgentManager | None = None,
    *,
    model_name: str = "gpt-5.4-mini",
    parent_depth: int = 0,
    system_prompt: str = "",
    model_adapter_factory: Any | None = None,
) -> AsyncGenerator[Event, None]:
    """Execute a sequence of workflow steps, piping results forward.

    Each step runs as a child agent. If a step has `depends_on`,
    the prior step's output is appended to its prompt.

    Yields ChildEvents from each step in order.

    Args:
        steps: Ordered list of workflow steps.
        manager: AgentManager instance (created if None).
        model_name: Model to use for all steps.
        parent_depth: Current nesting depth.
        system_prompt: Shared system prompt prefix.
        model_adapter_factory: Callable(step_index) → MockModelAdapter, for testing.
    """
    mgr = manager or AgentManager()
    results: dict[str, AgentResult] = {}

    for i, step in enumerate(steps):
        # Inject dependency output into prompt
        prompt = step.prompt
        if step.depends_on and step.depends_on in results:
            prior = results[step.depends_on]
            prompt = f"{prompt}\n\n## Prior result from '{step.depends_on}':\n{prior.output}"

        config = AgentConfig(
            role=step.role,
            model_name=model_name,
            depth=parent_depth + 1,
        )

        adapter = model_adapter_factory(i) if model_adapter_factory else None

        async for event in mgr.spawn(
            prompt, config,
            system_prompt=system_prompt,
            model_adapter=adapter,
        ):
            yield event

        # Collect result for downstream steps
        result = mgr.get_result(config.agent_id)
        if result and step.name:
            results[step.name] = result


def impl_then_verify(
    impl_prompt: str,
    verify_prompt: str = "Review the implementation above. Check for correctness and report issues.",
    *,
    model_name: str = "gpt-5.4-mini",
) -> list[WorkflowStep]:
    """Create a standard implement → verify workflow.

    Returns a list of WorkflowSteps ready for run_workflow().
    """
    return [
        WorkflowStep(
            prompt=impl_prompt,
            role="implementation",
            name="implementation",
        ),
        WorkflowStep(
            prompt=verify_prompt,
            role="verification",
            name="verification",
            depends_on="implementation",
        ),
    ]
