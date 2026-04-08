"""Core runtime engine — loop, state, compaction."""
from agent_runtime.engine.loop import MockModelAdapter, run_query_loop
from agent_runtime.engine.models import (
    ChildEvent,
    Event,
    FinalEvent,
    RecoveryEvent,
    SessionState,
    TextDeltaEvent,
    ThinkingEvent,
    ToolCallEvent,
    ToolResultEvent,
    TurnConfig,
    WorkingMemory,
    assistant_message,
    tool_result_message,
    user_message,
)

# compaction imported lazily to avoid circular import with prompt.context


def compact(state: SessionState, config: TurnConfig, **kwargs) -> str:
    from agent_runtime.engine.compaction import compact as _compact
    return _compact(state, config, **kwargs)


def update_working_memory(wm: WorkingMemory, **kwargs) -> None:
    from agent_runtime.engine.compaction import update_working_memory as _update
    _update(wm, **kwargs)
