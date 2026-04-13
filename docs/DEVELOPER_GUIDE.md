# Agent Runtime — Developer Guide

A practical, end-to-end guide to the codebase. If you're forking this repo to build a new agent (coding, layout, 3D, planning, anything), start here.

For *why* the system is shaped the way it is, read `AGENT_DESIGN_PHILOSOPHY.md` first — it's the source of all the engineering decisions here. This document is the *what* and *how*.

---

## Table of contents

1. [TL;DR](#tldr)
2. [Design philosophy — the short version](#design-philosophy--the-short-version)
3. [Architecture map](#architecture-map)
4. [The query loop — heartbeat](#the-query-loop--heartbeat)
5. [The prompt — control plane](#the-prompt--control-plane)
6. [Session state & storage](#session-state--storage)
7. [Tools](#tools)
8. [Packs — the fork point](#packs--the-fork-point)
9. [Multi-agent support](#multi-agent-support)
10. [The REPL — developer UX](#the-repl--developer-ux)
11. [Extending the system](#extending-the-system)
12. [Testing](#testing)
13. [Known carry-forwards](#known-carry-forwards)

---

## TL;DR

**What is it.** A Python agent runtime kernel — a query loop, a layered prompt builder, a three-layer memory model, a tool registry with permissioning, session persistence, and a developer-first REPL. Built to be **forked** into new agent applications.

**Who it's for.** Engineers building a new agent who want the harness pre-solved: state, prompt assembly, streaming, recovery, observability. You bring the tools and the AGENT.md.

**Quick start.**

```bash
# Install deps (uv creates .venv and installs from pyproject.toml)
uv sync
uv pip install pytest pytest-asyncio   # tests only

# Set an API key for at least one provider
export OPENAI_API_KEY=sk-...            # or ANTHROPIC_API_KEY, GEMINI_API_KEY, etc.

# Run the REPL (default pack: coding)
uv run python -m agent_runtime

# Or pick a model + pack
uv run python -m agent_runtime claude-sonnet-4-6 --pack coding
uv run python -m agent_runtime gpt-5.4-mini --pack minimal

# Type `/help` once inside to see every slash command.
```

**Fork a new agent in 60 seconds.** Copy `agent_runtime/packs/coding/` to `agent_runtime/packs/my_agent/`, edit `AGENT.md` and `ALLOWED_TOOLS` in `pack.py`, run `python -m agent_runtime --pack my_agent`. Done. See [Packs](#packs--the-fork-point) for the full story.

---

## Design philosophy — the short version

Five principles shape every module. Full treatment lives in `docs/AGENT_DESIGN_PHILOSOPHY.md`.

1. **The query loop is the heartbeat.** The agent is not `message → model → response`. It's a stateful `while` loop with explicit cross-turn state, explicit recovery paths, and explicit completion semantics. The model call is *one step inside* the loop, not the loop itself.

2. **The prompt is a control plane.** Not a paragraph of instructions. A layered, cache-conscious, debuggable configuration: base → project rules → runtime mode → task context. Each layer carries metadata you can inspect.

3. **Context is scarce.** Tokens are budget. Three-layer memory (rules always loaded, index always loaded, topic files on demand, transcripts never in the prompt) + compaction with **preserved working memory** (the thing that survives when history gets summarized).

4. **Tools are managed syscalls.** Not ad-hoc function calls. Every tool goes through a registry, a permission callback, a ledger entry, and has output truncation. A high-risk flag is a runtime policy, not a doc comment.

5. **Recovery is first-class.** `FinalEvent`, `RecoveryEvent`, `ToolResultEvent(status=error)` — the runtime distinguishes completion, failure, compaction, and continuation structurally. A system that can't tell these apart is a script, not a runtime.

---

## Architecture map

```
agent_runtime/
├── engine/                 # The kernel. No agent-specific logic.
│   ├── loop.py             # run_query_loop — async generator, yields Events
│   ├── models.py           # Event types, SessionState, TurnConfig, WorkingMemory
│   └── compaction.py       # Context-overflow recovery (preserves working memory)
│
├── prompt/                 # The control plane.
│   ├── builder.py          # 4-layer PromptConfig (base / project / runtime / task)
│   ├── memory.py           # load_rules, load_memory_index, load_topic
│   └── context.py          # build_task_context — working memory + recent ledger
│
├── provider.py             # Model provider adapters (Anthropic + OpenAI-compat).
│                           #   Unified stream() entrypoint. Auto-detects by model prefix.
│                           #   Neutral message format + converters.
│
├── tools/                  # Tool "stdlib" — shared primitives.
│   ├── base.py             # ToolSpec, ToolRegistry, LedgerEntry, global `registry`
│   ├── read_file.py  write_file.py  grep_search.py  bash.py
│   ├── ask_user.py         # Suspend-event-based human-in-the-loop
│   └── spawn_task.py  agent_ops.py   # Multi-agent primitives (M7–M8)
│
├── roles/
│   └── policy.py           # RolePolicy — allowed_tools per role (research/impl/verif/synth)
│
├── agents/                 # Multi-agent — spawn/coordinate child query loops.
│   ├── config.py           # AgentConfig / AgentResult / MAX_DEPTH
│   ├── manager.py          # AgentManager.spawn / spawn_background
│   └── coordinator.py      # Coordinator pattern (higher-level orchestration)
│
├── packs/                  # Agent identity = a pack. Forking happens here.
│   ├── loader.py           # load_pack, get_active_pack, pack_registry
│   ├── coding/             # Default pack — all stdlib tools + coding AGENT.md
│   └── minimal/            # Proof pack — no tools, conversation only
│
├── cli/                    # The REPL — developer UX lives here.
│   ├── app.py              # Entrypoint: async session loop + --pack flag
│   ├── commands.py         # @register slash-command dispatcher + ReplContext
│   ├── bus.py              # In-process EventBus (fan-out to subscribers)
│   ├── prompt_view.py      # build_current_prompt — single source of truth
│   ├── display.py          # Spinner + DisplayRenderer
│   └── dev.py              # Offline session analyzer (legacy entrypoint)
│
├── storage.py              # Flat-file persistence (schema v2):
│                           #   state.json / transcript.jsonl / meta.json / snapshots/
└── tests/                  # 196 unit + integration tests (pytest, pytest-asyncio)
```

### Data flow at runtime (one user turn)

```
 User types message
         │
         ▼
 ┌─────────────────────────────────────────────────────────────────┐
 │ cli/app.py _run_session                                         │
 │   1. Check for slash command / shell escape → short-circuit    │
 │   2. (M9.5) Turn breakpoint? → _pause_for_inspection            │
 │   3. build_current_prompt(state, config)                        │
 │        └─ pack rules + memory index + task context + tool schemas
 │   4. append_transcript(user_input + system_prompt)              │
 │   5. run_query_loop(...) ───────────────┐                       │
 └─────────────────────────────────────────┼───────────────────────┘
                                           │
                                           ▼
                              ┌──────────────────────────┐
                              │ engine/loop.py           │
                              │   while turn < max:      │
                              │     provider.stream(...) │──► Anthropic / OpenAI-compat
                              │     for chunk in stream: │
                              │       yield TextDelta    │
                              │       yield Thinking     │
                              │     if tool_calls:       │
                              │       permission_cb()    │──► ctx.step_mode / break_tools
                              │       registry.execute() │──► ledger entry
                              │       yield ToolResult   │
                              │       if compact needed: │
                              │         compact_handler()│──► preserves working memory
                              │         yield Recovery   │
                              │     else:                │
                              │       yield Final        │
                              └──────────────┬───────────┘
                                             │ events
                                             ▼
 ┌────────────────────────────────────────────────────────────────┐
 │ cli/bus.py EventBus.publish(event)                             │
 │   → DisplayRenderer.on_event  (spinner + stdout)               │
 │   → transcript subscriber     (full-payload JSONL)             │
 └────────────────────────────────────────────────────────────────┘
                                             │
                                             ▼
                         save_session + save_snapshot(user_turn)
                                             │
                                             ▼
                                  ctx.user_turn += 1
```

---

## The query loop — heartbeat

**File**: `agent_runtime/engine/loop.py`

`run_query_loop` is an **async generator** that yields typed `Event` objects. The caller (the REPL, tests, another agent) decides how to render them. This is the foundational design choice: rendering is not the loop's responsibility.

### Signature

```python
async def run_query_loop(
    user_input: str,
    state: SessionState,
    config: TurnConfig,
    *,
    system_prompt: str = "",
    model_adapter: MockModelAdapter | None = None,
    tool_executor: ToolExecutor | None = None,
    tool_registry: ToolRegistry | None = None,
    permission_callback: PermissionCallback = _auto_permission,
    compact_handler: Callable[[SessionState, TurnConfig], str] | None = None,
) -> AsyncGenerator[Event, None]:
    ...
```

### What it does

1. Appends `user_input` to `state.messages`.
2. Enters `while turn < config.max_turns:` — each iteration = one model invocation.
3. Calls the provider (or a `MockModelAdapter` for tests) to **stream** chunks: `TextChunk` / `ThinkingChunk` / final `AssistantTurn`.
4. Re-emits each chunk as a typed event (`TextDeltaEvent`, `ThinkingEvent`).
5. If the assistant requested tool calls:
   - For each call: `ToolCallEvent` → `permission_callback(name, input)` → `registry.execute(...)` → `ToolResultEvent`.
   - Appends the tool result to `state.messages` so the next iteration shows it to the model.
   - Increments `state.turn_count`, `continue`s — the model **must** see tool results, so another loop iteration runs.
6. If no tool calls: final assistant message goes into history, yields `FinalEvent`, returns.
7. After tool execution, checks `should_compact(state, config)`. If yes and a `compact_handler` is wired, compaction runs and yields `RecoveryEvent(reason="context_too_long")`.

### The event taxonomy (`engine/models.py`)

| Event | When | Key fields |
|---|---|---|
| `ThinkingEvent` | Streaming reasoning token | `text` |
| `TextDeltaEvent` | Streaming response token | `text` |
| `ToolCallEvent` | Model requests a tool | `tool_call_id`, `tool_name`, `tool_input` |
| `ToolResultEvent` | Tool finished (or was denied) | `tool_call_id`, `output`, `status` (`ok`/`error`/`interrupted`) |
| `RecoveryEvent` | Runtime took a recovery action | `reason` (`output_too_long` / `context_too_long` / `tool_failure` / `abort`), `detail` |
| `FinalEvent` | Turn is done | `text` — full assistant reply |
| `ChildEvent` | Event from a spawned child agent | `agent_id`, `role`, `inner` (the child's actual Event) |

### Important: `turn_count` vs `user_turn`

- `state.turn_count` = **model-iteration** count. Increments inside the loop every time the model responds, including intermediate tool-calling iterations.
- `ctx.user_turn` (REPL-side) = **user-interaction** count. Increments only after a complete user query resolves.

A user asking *"read file X and summarize"* that triggers 3 tool calls then a final reply advances `turn_count` by 4 but `user_turn` by 1. **Snapshots use `user_turn`** — you fork / rewind at the granularity users think in.

### Recovery semantics

- **Tool failure** → `ToolResultEvent(status="error")` + `RecoveryEvent(reason="tool_failure")`. The error text goes back into message history so the model can see what happened and react.
- **Context overflow** → `compact_handler` runs, `state.messages` are rewritten in-place (summary + recent), `compact_summary` is set, `RecoveryEvent(reason="context_too_long")` fires.
- **Permission denied** → a synthetic "Permission denied" tool result is injected so the assistant/user turn alternation stays intact. (This is the *causal closure* idea from the philosophy doc.)
- **Max turns** → final event with whatever text is available, no exception.

### The MockModelAdapter

`MockModelAdapter` (in `loop.py`) is how tests exercise the loop without hitting an API. Pass it a list of `AssistantTurn` objects and it replays them in sequence. Every unit test that touches the loop uses this — read `tests/test_query_loop.py` for patterns.

---

## The prompt — control plane

**Files**: `agent_runtime/prompt/builder.py`, `cli/prompt_view.py`

The system prompt is built from **four ordered layers**:

| # | Layer | Source | Cacheable | Purpose |
|---|---|---|---|---|
| 1 | `base` | hardcoded in `builder.py` | ✓ | Behavioral rules + auto-appended tool descriptions |
| 2 | `project_rules` | active pack's `AGENT.md` | ✓ | Pack-specific instructions |
| 3 | `runtime_mode` | injected per call | ✗ | Mode-specific overrides (e.g. "plan mode") |
| 4 | `task_context` | `build_task_context(state)` | ✗ | Working memory + recent ledger + compact summary |

The builder returns a `PromptConfig` holding a `list[PromptLayer]`. Each layer carries `name`, `content`, `source`, `cacheable`. This metadata is what makes `/prompt layers` and `/tokens` possible — **inspection is a first-class concern**.

### The single source of truth

`cli/prompt_view.build_current_prompt(state, config)` is **the one place** in the codebase that knows how to assemble the live prompt. Both `app.py` (sending to the model) and `commands.py` (the `/prompt` inspector) call it. If you need to add another prompt layer, change it once, here.

```python
def build_current_prompt(state, config) -> PromptConfig:
    pack = get_active_pack()
    if pack is not None:
        rules = load_rules(*pack.rules_files)
        memory_index = load_memory_index(pack.path / "MEMORY.md")
        reg = pack_registry(pack)
    else:
        rules = load_rules("AGENT.md", "PROJECT.md")  # CWD fallback
        memory_index = load_memory_index("MEMORY.md")
        reg = global_registry

    task_context = build_task_context(state, rules_content=rules, memory_index=memory_index)
    tool_descs = "\n".join(f"- **{s['name']}**: {s['description']}" for s in reg.get_schemas())

    return build_prompt(
        project_rules=rules,
        runtime_mode="",
        task_context=task_context,
        tool_descriptions=tool_descs,
    )
```

### The 3-layer memory model

Rules and index are **always loaded** (cheap, small, critical). Topic files are **loaded on demand** only when retrieval logic asks for them. Transcripts **never** enter the prompt — they live in storage.

```
prompt/
├── AGENT.md          ← Layer 1 (rules, always)
├── PROJECT.md        ← Layer 1 (rules, always, optional)
├── MEMORY.md         ← Layer 2 (index, always — short pointer lines)
└── topic_*.md        ← Layer 3 (on-demand — full knowledge content)
```

MEMORY.md is an index of pointers: "here's what exists, where to find it". It's capped at 200 lines (enforced in `memory.py`). Topic files get loaded on demand by retrieval logic — but the retrieval plumbing itself is a carry-forward; right now topics are accessible via `load_topic(path)` but not wired into the live loop. When you build out topic-on-demand retrieval, do it in `prompt/context.py`'s `build_task_context`.

---

## Session state & storage

**Files**: `engine/models.py`, `storage.py`

### `SessionState`

```python
@dataclass(slots=True)
class SessionState:
    session_id: str
    messages: list[dict[str, Any]]      # neutral message format
    ledger: list[LedgerEntry]           # audit log of every tool call
    working_memory: WorkingMemory       # survives compaction
    compact_summary: str
    total_input_tokens: int
    total_output_tokens: int
    turn_count: int                     # model-iteration count (not user-turn)

    def replace_from(self, other): ...  # in-place swap — used by fork/rewind/replay
```

### `WorkingMemory` — the anti-amnesia layer

```python
@dataclass(slots=True)
class WorkingMemory:
    task_state: str
    files_touched: list[str]
    errors_and_corrections: list[str]
    key_results: list[str]
    worklog: list[str]
```

**This is the insight from Claude Code.** When compaction runs, it discards old transcript messages, but working memory survives intact. That's how the agent remembers what it was actually doing across compaction events. The `compact()` function in `engine/compaction.py` formats working memory into a system message so the model keeps its bearings.

Update working memory via `update_working_memory()` in `compaction.py` (though the current codebase doesn't wire this into the loop — it's a hook you extend when your agent needs persistent task tracking).

### On-disk layout (schema v2)

```
.agent_sessions/
└── <session_id>/
    ├── state.json              Latest SessionState (overwritten each turn)
    ├── meta.json               {schema_version, created_at, parent_session, parent_turn, replayed_from}
    ├── transcript.jsonl        Full-payload event log (see below)
    └── snapshots/
        ├── turn_0000.json      SessionState after user_turn 0 completed
        ├── turn_0001.json
        └── ...
```

### Transcript schema (v2)

Each JSONL line is one record. Records carry a `user_turn` key for fork/rewind alignment.

| `type` | Extra fields |
|---|---|
| `user_input` | `text` |
| `system_prompt` | `prompt` (full), `layers` (per-layer `{name, source, cacheable, chars, tokens}`) |
| `tool_call` | `tool_call_id`, `tool_name`, `tool_input` |
| `tool_result` | `tool_call_id`, `tool_name`, `status`, `output` |
| `final` | `text` |
| `recovery` | `reason`, `detail` |

`text_delta` and `thinking` events are **not persisted** (noise — `final.text` carries the complete reply). If you need streaming-accurate playback later, re-enable persistence in `cli/app.py` `_event_to_record`.

### Legacy v1 sessions

Sessions created before M9.3 have no `meta.json` and `{type, turn}`-only transcript lines. `load_meta()` defaults to `{"schema_version": 1}` for them. `/replay` on a v1 session falls back to reading `role=user` messages from `state.json` because `user_input` transcript events don't exist there. `/tree` renders v1 sessions as orphan roots.

---

## Tools

**Files**: `agent_runtime/tools/`

### Anatomy of a tool

A tool is a `ToolSpec` registered on a `ToolRegistry`. Minimum definition:

```python
# agent_runtime/tools/my_tool.py
from agent_runtime.tools.base import ToolSpec, registry


def _my_tool(params: dict) -> str:
    # params is already validated against input_schema by the runtime
    return f"processed: {params['input']}"


registry.register(ToolSpec(
    name="my_tool",
    description="What this tool does, as seen by the model.",
    input_schema={
        "type": "object",
        "properties": {
            "input": {"type": "string", "description": "..."},
        },
        "required": ["input"],
    },
    executor=_my_tool,
    risk="low",              # "low" or "high" — high triggers permission prompt
    side_effecting=False,
))
```

### The registry contract

`ToolRegistry` in `tools/base.py` offers:

- `register(spec)` — typically called at module import time
- `get(name)` — lookup
- `list_names()` — all registered tools
- `get_schemas()` — export schemas for the model API
- `execute(name, input, *, max_output=32000)` — run a tool and return `(output, ledger_entry)`. Auto-truncates oversized output with `[... N chars truncated ...]` in the middle.
- `is_high_risk(name)` — used by the permission callback

The **global** `registry` instance is the "stdlib" — every built-in tool registers on it at import time. Packs build **scoped** registries from the global one (see [Packs](#packs--the-fork-point)).

### Risk model & permissions

A tool marked `risk="high"` (currently just `bash`) triggers `permission_callback` before execution. The default callback auto-denies high-risk tools when running outside a REPL (safe default for tests). In the REPL, the callback is a closure over `ReplContext` that also checks `ctx.step_mode` and `ctx.break_tools` — see [`/step`, `/break`](#debug--reload).

### The ledger

Every tool execution lands in `state.ledger` as a `LedgerEntry`:

```python
@dataclass(slots=True)
class LedgerEntry:
    tool_name: str
    tool_input: dict
    status: Literal["ok", "error", "interrupted"]
    started_at: float
    ended_at: float | None
    summary: str        # first 200 chars of output
    error: str
```

Inspect live with `/ledger` or offline with `python -m agent_runtime.cli.dev ledger <session_id>`.

### The ask_user tool — human-in-the-loop

`tools/ask_user.py` uses a *suspend event* pattern: the tool raises `UserInputRequired`, the loop catches it, the runtime yields a suspension event, the caller handles it, the loop resumes with the user's answer. This is how you bring humans into the execution graph without blocking the async machinery.

### Spawn tools — multi-agent

`tools/spawn_task.py` and `tools/agent_ops.py` let the agent spawn child agents (research / implementation / verification / synthesis). See [Multi-agent support](#multi-agent-support).

---

## Packs — the fork point

**Files**: `agent_runtime/packs/loader.py`, `agent_runtime/packs/coding/`, `agent_runtime/packs/minimal/`

A **pack** is a directory defining an agent's identity. Fork a pack, not the runtime.

### Pack layout

```
agent_runtime/packs/<name>/
├── pack.py         # Python manifest — NAME, ALLOWED_TOOLS, RULES_FILES, optional side-effect imports
├── AGENT.md        # Pack-specific system prompt rules
├── MEMORY.md       # (optional) pack-local memory index
├── topic_*.md      # (optional) topic files
└── __init__.py     # (can be empty)
```

### The manifest (`pack.py`)

```python
# agent_runtime/packs/coding/pack.py
import agent_runtime.tools  # side-effect: register stdlib tools on the global registry

NAME = "coding"
ALLOWED_TOOLS = [
    "read_file", "grep_search", "write_file", "bash", "ask_user", "spawn_task",
]
RULES_FILES = ["AGENT.md"]  # relative to pack dir; can list multiple
```

That's it. A pack declares which tools the agent is allowed to see, which rule files compose the `project_rules` layer, and (optionally) runs side-effect imports to register pack-local tools on the global registry.

### How the runtime uses a pack

`packs/loader.py` provides:

- `load_pack(name_or_path)` — imports `pack.py`, reads its constants, installs as active. Accepts either a pack name (`"coding"`) or a filesystem path.
- `get_active_pack()` — returns the currently installed `ActivePack`.
- `pack_registry(pack=None)` — returns a `ToolRegistry` scoped to `ALLOWED_TOOLS`. **Empty list = truly empty registry** (pack opted out of tools). **No active pack = global registry** (legacy fallback for tests).
- `available_packs()` — lists built-in packs under `agent_runtime/packs/`.

The REPL loop calls `pack_registry()` **every turn**, so `/pack switch` takes effect immediately without restart. `build_current_prompt` also reads the active pack each call, so `AGENT.md` hot-reloads via `/edit prompt`.

### Forking a pack — the full walkthrough

```bash
# 1. Copy the base pack
cp -R agent_runtime/packs/coding agent_runtime/packs/my_agent

# 2. Edit the rules
$EDITOR agent_runtime/packs/my_agent/AGENT.md
# Replace the coding-agent text with your agent's system prompt.

# 3. Pick which stdlib tools you want
$EDITOR agent_runtime/packs/my_agent/pack.py
# Adjust ALLOWED_TOOLS. Remove tools you don't need.
# Add pack-local tools: create agent_runtime/packs/my_agent/tools/foo.py
#   that calls registry.register(ToolSpec(...)), then import it from pack.py:
#   `from agent_runtime.packs.my_agent.tools import foo`

# 4. Run it
uv run python -m agent_runtime --pack my_agent
```

That's the entire fork flow. The core runtime does not know your pack exists until `load_pack("my_agent")` imports it.

### Packs outside the package tree

`--pack` also accepts a directory path, so a pack can live anywhere:

```bash
uv run python -m agent_runtime --pack /path/to/my_project/agent_pack
```

Useful when your pack is part of another repo that depends on `agent_runtime`.

---

## Multi-agent support

**Files**: `agent_runtime/agents/`, `agent_runtime/roles/policy.py`, `agent_runtime/tools/spawn_task.py`

The runtime supports spawning **child agents** from within a running agent. A spawned child is not a new process — it's a nested `run_query_loop` call with a scoped registry and its own `SessionState`. Child events are wrapped in `ChildEvent` and forwarded up to the parent.

### Roles

`roles/policy.py` defines four role policies:

| Role | Allowed tools | Can modify files | Can verify own work |
|---|---|---|---|
| `research` | read_file, grep_search, bash, ask_user | ✗ | ✗ |
| `implementation` | read_file, grep_search, write_file, bash | ✓ | ✗ |
| `verification` | read_file, grep_search, bash | ✗ | — |
| `synthesis` | read_file, ask_user | ✗ | — |

The hard invariant enforced by `agents/manager.py`: **a verification agent cannot spawn another verification agent**. Separation of concerns is structural.

### Spawning a child

Tools registered for this: `spawn_task`, `check_agent`, `abort_agent`, `list_agents`. They let the running agent launch and manage children through the normal tool interface.

```python
# From the model's perspective, this is just a tool call:
spawn_task(
    prompt="Read src/foo.py and summarize the main class",
    role="research",
    model_name="gpt-5.4-mini",
)
```

Under the hood, `AgentManager.spawn()` (`agents/manager.py`) builds a scoped registry from the role's `allowed_tools`, creates a child `SessionState`, runs `run_query_loop`, and wraps each child event in `ChildEvent`. The parent loop `yield from`s these children so the whole tree streams in real time.

### Fork mode vs fresh mode

`AgentConfig.fork=True` causes the child to inherit the parent's `state.messages` (prompt cache hit). `fork=False` (default) starts the child with a fresh context. Use fork mode when you want the child to see the conversation history; use fresh mode when you want an isolated reasoning context.

### Coordinator pattern

`agents/coordinator.py` implements a higher-level pattern where a top-level agent decomposes a task and dispatches to specialized children. Read the tests in `tests/test_coordinator.py` for usage examples.

### `MAX_DEPTH = 3`

Defined in `agents/config.py`. Agents can spawn agents that spawn agents, but only three levels deep. This is a circuit breaker — change it at your own risk.

---

## The REPL — developer UX

**Files**: `agent_runtime/cli/app.py`, `cli/commands.py`, `cli/bus.py`

The REPL is not a chat window. It's an interactive debugger for agents. Think `ipython` / `ipdb` / `psql`.

### Input routing

```
line starts with "/"   → slash command   (dispatched via commands.COMMANDS registry)
line starts with "!"   → shell escape    (subprocess.run with shell=True)
line == "quit"/"exit"  → leave
else                   → user input for the agent
```

### The 19 slash commands, grouped

#### Session inspection

| Command | What |
|---|---|
| `/help` | List every command with one-line descriptions (auto-generated from the registry) |
| `/sessions` | List every persisted session (id, turn count, message count, token count) |
| `/show [sid\|.]` | Session overview — `.` means current |
| `/messages [sid\|.]` | Print the message history |
| `/ledger [sid\|.]` | Print tool execution ledger with durations |
| `/transcript [sid\|.]` | Print the raw event log |

#### Prompt inspector (M9.2)

| Command | What |
|---|---|
| `/prompt` | Print the live system prompt with layer boundaries visible |
| `/prompt layers` | Table: per-layer name, source, cacheable, chars, token estimate |
| `/prompt diff A B` | Unified diff of system prompts between two user_turns (same session) |
| `/tokens` | Context window breakdown (system layers + history + tool results + total vs. compact threshold) |
| `/context` | One-line context summary: `[ctx 1234/24000 · sys 456 · hist 700 · tools 78]` |

#### Session tree (M9.3)

| Command | What |
|---|---|
| `/fork` | Fork the current session from its tip into a new session; switches the REPL to the new one |
| `/fork @N` | Fork from snapshot `user_turn=N` |
| `/rewind N` | Drop the last N user-turns in place (y/n confirm). Deletes later snapshots + truncates transcript |
| `/replay <sid> [--model X]` | Replay a session's user inputs into a fresh session, optionally overriding the model |
| `/tree` | ASCII fork tree of all sessions with `(forked @N)` / `(replayed from …)` tags |

#### Pack control (M9.4)

| Command | What |
|---|---|
| `/pack` | Show the active pack, its rules, its tools, and all available packs |
| `/pack switch <name>` | Hot-swap to another pack. Next turn uses the new rules + scoped registry |

#### Debug & reload (M9.5)

| Command | What |
|---|---|
| `/step [on\|off]` | Toggle: when on, pause (y/n) before *every* tool call, not just high-risk |
| `/break tool:<name>` | Pause (y/n) before any call to the named tool |
| `/break turn:<n>` | Pause into an inspector mini-REPL at user_turn N, before the model runs |
| `/break list` / `/break clear` | Show / clear breakpoints |
| `/dry-run <message>` | Print exactly what would be sent to the model (prompt + tools + input) without calling it |
| `/edit prompt` | Open `$EDITOR` on the active pack's `AGENT.md`. Next turn re-reads from disk |
| `/reload tools` | `importlib.reload()` all `agent_runtime.tools.*` modules + re-run the pack's `pack.py` |

### Turn-breakpoint inspector

When a turn breakpoint fires, the REPL drops into a mini-REPL with a different prompt:

```
[Break: turn:3]  slash commands available; 'continue' to resume, 'abort' to skip
(paused)> /prompt layers
... prints current prompt layers ...
(paused)> /tokens
... prints token breakdown ...
(paused)> continue
```

From inside the paused state you can run **any** slash command — including `/fork`, `/rewind`, `/pack switch`. That's intentional: the paused turn becomes a full debugging checkpoint, and if you swap session mid-pause the aborted turn is simply discarded.

### The event bus

`cli/bus.py` is a ~20-line `EventBus` that fans published events out to subscribers. The default wiring is:

- `DisplayRenderer.on_event` — prints to stdout with a spinner
- a transcript writer — appends full-payload records to `transcript.jsonl`

Adding a third subscriber (custom logger, TUI renderer, metrics collector) is one line. Subscriber exceptions are caught so one bad subscriber can't crash the loop.

### `ReplContext`

Holds every mutable REPL-side concept so commands can read/swap live:

```python
@dataclass
class ReplContext:
    state: SessionState
    config: TurnConfig
    user_turn: int = 0
    pending_inputs: list[str] = field(default_factory=list)   # /replay queue
    step_mode: bool = False
    break_tools: set[str] = field(default_factory=set)
    break_turns: set[int] = field(default_factory=set)
```

The REPL's `_run_session` reads `ctx.state` / `ctx.config` **every iteration**, which is why `/fork`, `/replay`, `/pack switch`, and config overrides take effect without restart.

### Offline analyzer

`python -m agent_runtime.cli.dev <subcommand>` still exists for scripted session inspection:

```bash
python -m agent_runtime.cli.dev sessions
python -m agent_runtime.cli.dev show <session_id>
python -m agent_runtime.cli.dev messages <session_id>
python -m agent_runtime.cli.dev ledger <session_id>
python -m agent_runtime.cli.dev prompt <session_id>
python -m agent_runtime.cli.dev transcript <session_id>
python -m agent_runtime.cli.dev compare <id1> <id2>
```

The live slash commands delegate to `cli/dev.py`'s formatters, so there's one source of truth for output format. If you add a new inspector, add it to both surfaces (or refactor them together — noted as a carry-forward).

---

## Extending the system

### Add a new tool

1. Create `agent_runtime/tools/my_tool.py` with a `registry.register(ToolSpec(...))` call at module scope.
2. Add the import in `agent_runtime/tools/__init__.py` so it's auto-loaded: `from agent_runtime.tools import my_tool` (alongside the others).
3. Add `"my_tool"` to the `ALLOWED_TOOLS` list of any pack that should see it.
4. Run the REPL, try `/prompt layers` — the tool schema should appear in the base layer.

**Pack-local tools** don't need step 2 — put the registration in a module inside the pack directory and import it from `pack.py`. Pack-local tools don't pollute the global stdlib.

### Add a new pack

See [Forking a pack — the full walkthrough](#forking-a-pack--the-full-walkthrough) above.

### Add a new slash command

```python
# agent_runtime/cli/commands.py

@register("greet", "Say hello to the user")
def _greet(args: list[str], ctx: ReplContext) -> None:
    name = args[0] if args else "world"
    print(f"Hello, {name}!")
```

`/help` will pick it up automatically from the `COMMANDS` registry. No other changes needed.

### Add a new prompt layer

Modify `prompt/builder.build_prompt` to accept + emit a new `PromptLayer`. Update `cli/prompt_view.build_current_prompt` (the single source of truth) to populate it. `/prompt layers` will show the new layer automatically because it iterates `pc.layers`.

### Add a new provider

Add an entry to `PROVIDERS` and a prefix to `_PREFIXES` in `provider.py`. If the provider speaks OpenAI-compatible, you're done — `stream_openai_compat` handles it. If it speaks a different protocol, write a new `stream_<name>` function mirroring the shape of `stream_anthropic` or `stream_openai_compat` (yielding `TextChunk` / `ThinkingChunk` / final `AssistantTurn`).

### Add a new role

Define a `RolePolicy` in `roles/policy.py` and register it in the `_POLICIES` dict. `spawn_task` and `AgentManager` will pick it up via `get_policy(role_name)`.

### Replace the token counter

`engine/loop.estimate_tokens` uses `len/3.5` as a heuristic. Swap it for a real tokenizer by editing that one function. `cli/prompt_view.estimate_tokens_str` uses the same ratio for string inputs — update it in tandem. Everything else (`/tokens`, `/context`, compaction threshold) re-derives from these two functions.

### Replace the compaction strategy

`engine/compaction.compact()` currently does heuristic summarization of old messages (first 100 chars per message). Replace `_summarize_messages` with an LLM call if you want higher-fidelity compaction. The preservation contract — working memory survives, recent N messages survive, everything else is summarizable — stays the same.

---

## Testing

```bash
uv run pytest agent_runtime/tests/ -q
```

**196 tests** at the time of this guide, covering: query loop mechanics, compaction, prompt assembly, context building, memory loading, tool registry, tool execution, provider message converters, storage round-trips, agent spawning (sync + async), coordinator pattern, role policy enforcement, e2e multi-turn flows.

Most tests use `MockModelAdapter` to drive the loop deterministically — read `tests/test_query_loop.py` and `tests/test_e2e.py` for the canonical patterns. No test hits a real API.

**No tests exist for the REPL layer yet** (slash commands, bus, session fork). Everything added in M9 was verified via end-to-end stdin-piped smoke tests. If you grow the REPL further, consider adding `tests/test_commands.py` that exercises `dispatch()` against a temporary session directory.

---

## Known carry-forwards

Kept for honesty — none of these block day-to-day use, but they'll matter if you push the system.

1. **Spinner overlap bug.** After a `tool_result` event, `DisplayRenderer` restarts the spinner with `first_chunk=False`, so the next `text_delta` prints on top of the spinning line. Pre-existing (pre-M9). One-line fix, deferred to avoid opportunistic refactoring.

2. **Base prompt name-drops specific tools.** `prompt/builder._BASE_SYSTEM_PROMPT` hardcodes behavioral rules that mention `bash` / `read_file` / `grep_search`. Under `--pack minimal` (no tools) those names leak into the system prompt. Fix: move that paragraph into `packs/coding/AGENT.md` and make the base prompt truly tool-agnostic.

3. **`cli/dev.py` vs `cli/commands.py` duplication.** Live slash commands delegate to `dev.cmd_*` functions, which keeps one source of truth for formatting, but the two modules now carry adjacent concerns (inspection). Consider unifying into `cli/inspect.py` next time either is touched.

4. **`/prompt diff` is same-session only.** Cross-session diff is a ~5-line change (read both transcripts, not one). Waiting for a real need.

5. **`/replay --pack Y`** not implemented. `--model X` is. Add `--pack` with one `load_pack(args[i+1])` call in `commands._replay`.

6. **Tool-level pauses are y/n, not inspector-aware.** Step mode and tool breakpoints ask a simple y/n; you can't run `/tokens` from inside a tool pause. Turn-level pauses *do* get the full inspector. Bridging the gap requires interleaving stdin with the running async loop — deferred.

7. **`tools/__init__.py` still auto-imports all stdlib tools.** Preserved for test compatibility. Running the REPL with `--pack minimal` registers all stdlib tools globally but only exposes zero to the agent (the pack's scoped registry has none). This is fine at runtime but would matter if someone wanted a truly minimal import footprint.

8. **`update_working_memory()` is defined but not called by the loop.** It's a hook — wire it in when your agent needs persistent task tracking across compaction events.

9. **Topic-on-demand retrieval is plumbed but not wired.** `prompt/memory.load_topic()` exists and works; `prompt/context.build_task_context()` has a `topic_content` parameter. Nothing decides *when* to call it yet. Add retrieval logic where it makes sense for your agent.

10. **No unit tests for the REPL layer.** See [Testing](#testing).

---

## Where to read next

- `docs/AGENT_DESIGN_PHILOSOPHY.md` — the *why*. Read this before making any non-trivial architectural change.
- `docs/PRD-agent-runtime.md` — the original PRD with acceptance criteria.
- `tasks/todo.md` — the implementation log. Review sections at the end of each milestone explain what actually shipped vs. what was planned.
- `agent_runtime/engine/loop.py` — read the whole thing. It's ~290 lines and it *is* the system. Everything else serves this loop.
