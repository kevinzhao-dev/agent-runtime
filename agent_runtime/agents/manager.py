"""Agent manager — spawn child agents with role enforcement and nested streaming.

Spawn = new query loop with scoped config. Not a new process.
Child events are wrapped in ChildEvent and yielded to the parent.
"""
from __future__ import annotations

from typing import Any, AsyncGenerator

from agent_runtime.agents.config import MAX_DEPTH, AgentConfig, AgentResult
from agent_runtime.engine.loop import MockModelAdapter, run_query_loop
from agent_runtime.engine.models import (
    ChildEvent,
    Event,
    SessionState,
    TurnConfig,
)
from agent_runtime.roles.policy import can_verify, get_policy
from agent_runtime.tools.base import ToolRegistry, ToolSpec, registry as global_registry


def _build_scoped_registry(
    allowed_tools: list[str],
    source: ToolRegistry | None = None,
) -> ToolRegistry:
    """Create a new registry containing only the allowed tools."""
    source = source or global_registry
    scoped = ToolRegistry()
    for name in allowed_tools:
        spec = source.get(name)
        if spec is not None:
            scoped.register(spec)
    return scoped


class AgentManager:
    """Manages spawning and tracking of child agents."""

    def __init__(self, source_registry: ToolRegistry | None = None) -> None:
        self._source_registry = source_registry or global_registry
        self._results: dict[str, AgentResult] = {}

    def validate_spawn(
        self,
        config: AgentConfig,
        parent_role: str | None = None,
    ) -> str | None:
        """Validate spawn request. Returns error string or None if valid."""
        if config.depth >= MAX_DEPTH:
            return f"Max agent depth ({MAX_DEPTH}) exceeded."
        if parent_role and parent_role == config.role == "implementation":
            # Implementation cannot spawn implementation as verifier
            # (but can spawn research or verification)
            pass  # allowed — they're not verifying
        if parent_role == config.role and config.role == "verification":
            return "Verification agent cannot spawn another verification agent."
        return None

    async def spawn(
        self,
        prompt: str,
        config: AgentConfig,
        *,
        system_prompt: str = "",
        model_adapter: MockModelAdapter | None = None,
    ) -> AsyncGenerator[Event, None]:
        """Spawn a child agent and yield its events wrapped in ChildEvent.

        This is an async generator — the parent loop can yield from it
        to stream child events to the caller in real time.

        After all events, yields a FinalEvent-like ChildEvent with the result.
        """
        # Validate
        error = self.validate_spawn(config)
        if error:
            result = AgentResult(
                agent_id=config.agent_id,
                role=config.role,
                error=error,
            )
            self._results[config.agent_id] = result
            yield ChildEvent(
                agent_id=config.agent_id,
                role=config.role,
                inner=type("ErrorEvent", (), {"type": "error", "text": error})(),
            )
            return

        # Build scoped tool registry based on role
        policy = get_policy(config.role)
        allowed = config.allowed_tools or list(policy.allowed_tools)
        scoped_registry = _build_scoped_registry(allowed, self._source_registry)

        # Fresh state for child
        child_state = SessionState()
        child_config = TurnConfig(
            model_name=config.model_name,
            max_turns=config.max_turns,
        )

        # Run child loop, forwarding events as ChildEvents
        final_text = ""
        async for event in run_query_loop(
            prompt,
            child_state,
            child_config,
            system_prompt=system_prompt,
            model_adapter=model_adapter,
            tool_registry=scoped_registry,
        ):
            yield ChildEvent(
                agent_id=config.agent_id,
                role=config.role,
                inner=event,
            )
            if hasattr(event, "type") and event.type == "final":
                final_text = event.text

        # Store result
        result = AgentResult(
            agent_id=config.agent_id,
            role=config.role,
            output=final_text,
            turn_count=child_state.turn_count,
            input_tokens=child_state.total_input_tokens,
            output_tokens=child_state.total_output_tokens,
        )
        self._results[config.agent_id] = result

    def get_result(self, agent_id: str) -> AgentResult | None:
        return self._results.get(agent_id)
