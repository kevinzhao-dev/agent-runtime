# Multi-Agent Architecture Plan

## Current State

We have a single-loop kernel with:
- `engine/loop.py` — async generator query loop
- `roles/policy.py` — 4 roles defined but not enforced at runtime
- `tools/` — serial execution, no concurrency

## Design Goals

1. **Role separation is real, not decorative** — implementation cannot self-verify
2. **Agents are lightweight** — spawn = new loop with scoped config, not a new process
3. **Parent controls lifecycle** — spawn, observe, abort, collect results
4. **Prompt cache economics** — forked agents share parent context prefix
5. **Simple first** — serial spawning before concurrent, in-process before distributed

---

## Architecture

### Core Concept: Agent = Loop + Role + Scope

```python
@dataclass(frozen=True, slots=True)
class AgentConfig:
    """Configuration for a spawned agent."""
    agent_id: str
    role: RoleName                    # research | implementation | verification | synthesis
    model_name: str = "gpt-5.4-mini"
    max_turns: int = 8
    allowed_tools: list[str] | None = None   # None = use role default
    parent_id: str | None = None
    depth: int = 0                    # nesting depth, max 3
```

An agent is just a `run_query_loop()` call with a scoped `AgentConfig` that enforces:
- Which tools it can use (from RolePolicy)
- What role boundary it operates under
- Who its parent is (for lifecycle)

### New Module: `agent_runtime/agents/`

```
agents/
  __init__.py          # re-exports
  config.py            # AgentConfig dataclass
  manager.py           # AgentManager — spawn, track, collect
  coordinator.py       # Coordinator pattern — synthesize, not relay
```

---

## Milestones

### M7 — Agent Spawn (serial, in-process)

- [ ] **M7.1** `AgentConfig` dataclass
  - role, model, max_turns, allowed_tools, parent_id, depth
  - depth limit = 3 (prevent runaway nesting)

- [ ] **M7.2** `AgentManager`
  - `spawn(prompt, config) → AgentResult` — runs a child loop to completion
  - Child gets fresh `SessionState` (clean context)
  - Child inherits parent's system prompt prefix (cache sharing)
  - Role-based tool filtering: only `allowed_tools` from RolePolicy
  - Depth check: refuse to spawn if depth >= max

- [ ] **M7.3** `spawn_task` tool
  - Model can spawn a sub-agent via tool call
  - Returns: agent_id, result summary
  - Serial execution in MVP (blocks parent loop until child completes)

- [ ] **M7.4** Role enforcement at spawn
  - Implementation agent cannot spawn another implementation agent as verifier
  - `can_verify(parent_role, child_role)` checked at spawn time
  - Verification agent gets read-only tools

- [ ] **M7.5** Tests
  - Parent spawns child, child completes, parent gets result
  - Depth limit enforced
  - Role boundary enforced (impl cannot self-verify)
  - Child tool access scoped by role

### M8 — Async Agent Coordination

- [ ] **M8.1** Async spawn
  - `spawn(prompt, config, wait=False) → task_id`
  - Child runs in background (asyncio.Task or ThreadPoolExecutor)
  - Parent continues its loop

- [ ] **M8.2** Agent lifecycle tools
  - `check_agent(task_id) → status | result`
  - `abort_agent(task_id)` — cooperative cancellation
  - `send_message(agent_id, message)` — follow-up to running agent

- [ ] **M8.3** Coordinator role
  - Synthesis role can spawn research + implementation + verification
  - Coordinator synthesizes results, not just forwards them
  - Explicit handoff protocol: impl → verify → synthesize

- [ ] **M8.4** Shared context / isolation
  - Default: child gets fresh state (clean)
  - Option: `fork=True` — child inherits parent messages (prompt cache hit)
  - Future: `isolation="worktree"` — git worktree for file isolation

- [ ] **M8.5** Tests
  - Async spawn + check result
  - Abort propagates to child
  - Coordinator orchestrates impl → verify flow
  - Fork mode shares prompt cache prefix

### M9 — Observable Multi-Agent (future)

- [ ] Agent transcript accessible from parent
- [ ] Cross-agent event stream (unified timeline)
- [ ] Budget sharing (parent + children share token quota)
- [ ] Worktree isolation for parallel file edits

---

## Key Design Decisions

### Q: How does spawn work mechanically?

```python
# In AgentManager
async def spawn(self, prompt: str, config: AgentConfig) -> AgentResult:
    if config.depth >= MAX_DEPTH:
        return AgentResult(error="Max depth exceeded")

    # Enforce role boundaries
    policy = get_policy(config.role)
    tools = filter_tools(registry, policy.allowed_tools)

    # Build scoped prompt (inherits parent prefix for cache)
    system_prompt = build_agent_prompt(config, parent_prompt_prefix)

    # Fresh state for child
    child_state = SessionState()
    child_turn_config = TurnConfig(
        model_name=config.model_name,
        max_turns=config.max_turns,
    )

    # Run child loop
    result_text = ""
    async for event in run_query_loop(
        prompt, child_state, child_turn_config,
        system_prompt=system_prompt,
        tool_registry=tools,
    ):
        if event.type == "final":
            result_text = event.text

    return AgentResult(
        agent_id=config.agent_id,
        output=result_text,
        state=child_state,
    )
```

### Q: How does the model trigger a spawn?

Via `spawn_task` tool:
```python
# Model calls:
spawn_task(
    prompt="Verify that the tests pass",
    role="verification",
    model="gpt-5.4-nano",    # optional: cheaper model for sub-task
)
# Returns: "Agent v-abc123 completed: All 12 tests passing."
```

### Q: What about AsyncGenerator for streaming child events?

Two modes:
1. **Blocking spawn** (M7): parent waits, gets final result. Simple.
2. **Async spawn** (M8): parent gets task_id, checks later. Child events logged to transcript but not streamed to parent.
3. **Future**: streaming child events to parent for real-time observation.

### Q: Prompt cache sharing?

Parent's cacheable prompt prefix (Layer 1 + 2) is passed to child.
Child appends its own role-specific instructions (Layer 3 + 4).
Result: child API call hits cache on the shared prefix → cheaper.

---

## What This Unlocks

| Pattern | How |
|---------|-----|
| **Code + Verify** | impl agent writes code → verify agent runs tests → coordinator reports |
| **Research + Synthesize** | N research agents explore → synthesis agent combines findings |
| **Divide + Conquer** | coordinator splits large task → impl agents work in parallel → merge |
| **Iterative Refinement** | impl → verify → feedback → impl again (coordinator manages loop) |

---

## Not in Scope (yet)

- Distributed agents (multi-machine)
- Agent-to-agent direct communication (all through coordinator)
- Dynamic role assignment (roles fixed at spawn)
- Agent persistence across sessions (agents are ephemeral)
