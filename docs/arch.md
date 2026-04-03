# Architecture

## Five-Layer Design

```
                    User
                     |
    ============================================
    |          1. ENTRYPOINTS                  |
    |   cli.py (REPL)    sdk.py (AgentEngine)  |
    ============================================
                     |
    ============================================
    |          2. CONTROL PLANE                |
    |   prompt.py         roles/config.py      |
    |   (system prompt    (RoleConfig:         |
    |    assembly)         tools, limits,      |
    |                      permissions)        |
    ============================================
                     |
    ============================================
    |          3. QUERY LOOP (engine/loop.py)   |
    |                                           |
    |   while True:                             |
    |     +---------------------------------+   |
    |     | A. Pre-Model Governance         |   |
    |     |    - Check abort / max_turns    |   |
    |     |    - Token budget check         |   |
    |     |    - Autocompact if needed      |   |
    |     +---------------------------------+   |
    |                  |                        |
    |     +---------------------------------+   |
    |     | B. Call Model (streaming)       |   |
    |     |    -> yield TextEvent chunks    |   |
    |     +---------------------------------+   |
    |                  |                        |
    |     +---------------------------------+   |
    |     | C. Error Detection & Recovery   |   |
    |     |    - Prompt too long -> compact  |   |
    |     |    - Max tokens -> continue     |   |
    |     |    - API error -> retry/backoff |   |
    |     |    (all with circuit breakers)  |   |
    |     +---------------------------------+   |
    |                  |                        |
    |     +---------------------------------+   |
    |     | D. Tool Execution               |   |
    |     |    - Permission gate            |   |
    |     |    - Execute tool               |   |
    |     |    -> yield ToolUse/Result      |   |
    |     |    - Append to messages         |   |
    |     |    - continue (next turn)       |   |
    |     +---------------------------------+   |
    |                  |                        |
    |     +---------------------------------+   |
    |     | E. Stop Condition               |   |
    |     |    - No tool_use = end_turn     |   |
    |     |    -> yield DoneEvent           |   |
    |     +---------------------------------+   |
    |                                           |
    ============================================
                     |
    ============================================
    |          4. TOOLS                        |
    |                                          |
    |   read_file  write_file  edit            |
    |   bash       grep        agent_tool      |
    |                                          |
    |   Tool Protocol:                         |
    |     name, description, input_schema      |
    |     execute(input, context) -> Result    |
    |     is_read_only() / is_destructive()    |
    |                                          |
    |   Permission Gate:                       |
    |     DEFAULT: read=allow, write=ask       |
    |     YOLO: allow all                      |
    |     STRICT: ask all                      |
    ============================================
                     |
    ============================================
    |     5. CONTEXT GOVERNANCE                |
    |                                          |
    |   budget.py:  Token tracking             |
    |     effective_window = 200k - 40k        |
    |     autocompact_threshold = 147k         |
    |                                          |
    |   compact.py: LLM summarization          |
    |     strip images -> summarize ->         |
    |     rebuild working context              |
    |                                          |
    |   recovery.py: Error handlers            |
    |     prompt_too_long -> compact retry     |
    |     max_output_tokens -> continuation    |
    |     api_error -> exponential backoff     |
    ============================================
```

## State Flow

```
LoopState (frozen dataclass — new object each transition)
  |
  |-- messages: tuple[dict, ...]     # conversation history
  |-- turn_count: int                # how many model calls
  |-- compact_tracking               # compact count, failures
  |-- recovery_attempts              # circuit breaker counters
  |-- input_tokens_used              # from API response usage
  |-- last_transition                # why we got here
  |
  | evolve(state, field=new_value) -> new LoopState
  v
```

Every state transition creates a **new** LoopState. No mutation. The causal chain is:

```
LoopState(turn=0) --[NEXT_TURN]--> LoopState(turn=1) --[NEXT_TURN]--> LoopState(turn=2) --[DONE]--> end
```

## Multi-Agent Architecture

```
Coordinator (RoleConfig: tools=[read_file, grep, agent_tool])
  |
  |-- agent_tool(role="implementer", task="build X")
  |     |
  |     +-- Implementer (tools=[read_file, write_file, edit, bash, grep])
  |           runs query_loop independently, returns result as ToolResult
  |
  |-- agent_tool(role="verifier", task="check X")
  |     |
  |     +-- Verifier (tools=[read_file, grep, bash], read_only=True)
  |           "assume the code has bugs, find them"
  |
  |-- Synthesize results, respond to user
```

Key: **same engine, different RoleConfig**. No separate orchestration layer.

## Event Stream

The query loop is an `AsyncGenerator[Event, None]` that yields:

```
TextEvent(text)           # streaming model output
ToolUseEvent(name, id)    # model wants to call a tool
ToolResultEvent(id, content)  # tool execution result
CompactEvent(summary)     # context was compacted
ErrorEvent(error)         # something went wrong
DoneEvent(reason, turns)  # loop finished
```

Consumers (CLI, SDK, tests) all consume the same event stream.

## File Map

```
engine/
  loop.py        # The heart — async generator query loop
  state.py       # LoopState, Events, Transitions
  recovery.py    # Error recovery (pure functions)
  dry_run.py     # Mock client for testing

tools/
  base.py        # Tool protocol
  registry.py    # Registration + role filtering
  permission.py  # allow/deny/ask gate
  read_file.py, write_file.py, edit.py, bash.py, grep.py
  agent_tool.py  # Spawns sub-engine for delegation

context/
  prompt.py      # System prompt assembly
  budget.py      # Token budget tracking
  compact.py     # LLM-based conversation summarization

roles/
  config.py      # RoleConfig + DEFAULT/COORDINATOR/IMPLEMENTER/VERIFIER

verify/
  verifier.py    # PytestStrategy + LLMReviewStrategy

entrypoints/
  cli.py         # Interactive REPL
  sdk.py         # AgentEngine class

main.py          # CLI entry point
```
