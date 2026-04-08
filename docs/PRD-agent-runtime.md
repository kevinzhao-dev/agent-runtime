# Agentic Workflow OS — MVP PRD

## One-liner

A minimal agent runtime kernel in modern Python. Query Loop as heartbeat. Prompt as control plane. Context as scarce resource. Tools as managed syscalls. Recovery as first-class semantics.

---

## 1. Product Thesis

This is not a chatbot. This is an **agent runtime kernel** — analogous to what an OS kernel is to a process:

- A persistent execution loop
- Context budget management
- Managed side effects (tools)
- Interrupt and recovery semantics
- Memory loading and compaction
- Lifecycle primitives for future multi-agent coordination

### Why now

Most agent implementations fail not because the model is weak, but because the runtime is hollow:

- No real execution loop — just single-shot request/response
- Prompt assembled ad hoc — no layering, no caching, no precedence
- Memory dumped into context until it overflows
- Tool calls fire-and-forget — no ledger, no interrupt semantics
- "Multi-agent" means more parallel noise, not responsibility separation

The goal is a **small runtime that stays alive** — not a large platform that demos well.

### Problems this MVP solves

| Priority | Problem |
|----------|---------|
| P0 | **Context blowup in long sessions.** No compaction, no memory layering — transcript accumulates until the model hallucinates or truncates. |
| P1 | **Tool side effects are invisible.** No ledger, no status tracking — when something breaks at turn 7, there's no audit trail. |
| P2 | **Prompt/rules/memory are one blob.** No layering, no cache boundaries — debugging means reading the entire concatenated string. |

Not addressed in MVP: high autonomy, browser-centric workflows, full multi-agent orchestration, multi-provider routing.

### Assumptions & Constraints

**Assumes:** single technical builder as user; local single-machine runtime; model API already exists (Anthropic SDK); primary workflows are file/code-centric, not browser-centric.

**Constrains to:** Python 3.12+; single process; serial tool execution; no background daemon; no fine-grained policy DSL; transcripts never in prompt.

---

## 2. Target User

**Primary:** Builder-researcher who writes code, wants an inspectable and evolvable agent runtime, and refuses to pay platform overhead before the kernel is right.

**Secondary:** Advanced builders who later plug in domain rules, memory stores, verification strategies, or embed this kernel into larger systems (coding agents, asset pipelines, workflow automation).

---

## 3. Design Principles

**P1. Query Loop is the heartbeat.**
The system is a `while` loop in `query_loop.py`. The model call is one step inside it, not the system itself.

**P2. Prompt is the control plane.**
Not a freeform string. A layered, precedence-aware, cache-conscious structure that composes base rules, project rules, runtime mode, and task context.

**P3. Context window is a scarce resource.**
Long-term memory in three layers (rules, index, topic files) plus a session working memory that survives compaction. Transcripts never enter the prompt.

**P4. Tools are managed syscalls.**
Every tool call passes through a registry, executes under policy, and lands in a ledger. `bash` is the high-risk special case.

**P5. Recovery is not an afterthought.**
Output overflow → continue. Context overflow → compact. Tool failure → ledger + report. Abort → cleanup path. These are loop branches, not exception handlers.

**P6. Multi-agent means responsibility separation.**
Implementation ≠ verification. Coordinator synthesizes, not relays. The value is in role boundaries, not agent count. MVP defines the model; full spawning comes later.

---

## 4. MVP Scope

### 4.1 In Scope

#### A. Core Runtime

- Single async query loop (`query_loop.py`)
- `AsyncGenerator[Event, None]` event stream
- Event types: `thinking`, `assistant_message`, `tool_call`, `tool_result`, `recovery`, `final`

#### B. Turn Configuration

```python
@dataclass(slots=True)
class TurnConfig:
    max_turns: int = 8
    allow_tools: bool = True
    model_name: str = "default"
    compact_threshold_tokens: int = 24_000
    system_mode: str = "default"
```

Minimal surface. Advanced knobs (`activeSkills`, `verificationRequired`, `modelProfile`) stay as internal defaults — no config entry point yet.

#### C. Tool System — 5 tools, no more

| Tool | Risk |
|------|------|
| `read_file` | low |
| `write_file` | low |
| `bash` | **high** |
| `grep_search` | low |
| `ask_user` | low |

One future slot reserved (`spawn_task` or `inspect_memory`).

**Permission model (MVP):** `read_file`, `write_file`, `grep_search`, `ask_user` = auto-allow. `bash` = ask. All side-effecting tools must pass through ledger.

#### D. Tool Specification

```python
@dataclass(slots=True)
class ToolSpec:
    name: str
    description: str
    risk: Literal["low", "high"] = "low"
    concurrency_safe: bool = False
    side_effecting: bool = False
```

Serial execution by default. No concurrency scheduler in MVP.

#### E. Tool Ledger

Every tool execution produces a ledger entry:

```python
@dataclass(slots=True)
class LedgerEntry:
    tool_name: str
    tool_input: dict[str, Any]
    status: Literal["ok", "error", "interrupted"]
    started_at: float
    ended_at: float | None = None
    summary: str = ""
    error: str = ""
```

#### F. Prompt Control Plane — 4 layers

| Layer | Cacheable | Content |
|-------|-----------|---------|
| 1. Base system prompt | ✓ | Identity, constraints, tool descriptions |
| 2. Project rules | ✓ | `AGENT.md`, `PROJECT.md` |
| 3. Runtime mode | ✗ | Mode-specific additions |
| 4. Task context | ✗ | Current state, recent tool outcomes |

#### G. Memory Model

Long-term memory (3 layers) + short-term working memory (1 layer):

| Layer | Lifetime | Load policy | Content |
|-------|----------|-------------|---------|
| Rules | Static | Every turn | `AGENT.md`, `PROJECT.md` |
| Memory index | Persistent | Every turn (cheap) | `MEMORY.md` — short lines, pointers only |
| Topic files | Persistent | On demand | Domain knowledge, loaded by retrieval logic |
| **Session working memory** | **Per-session** | **Every turn (survives compaction)** | **See below** |
| Transcripts | Per-session | **Never in prompt** | Stored separately; accessible via grep/inspect/summarize |

**Session working memory** is the critical short-term layer that keeps the agent functional across compaction boundaries. It is not transcript — it is a structured artifact the loop maintains and updates:

- **Current task state** — what the agent is doing right now
- **Files/functions touched** — active working set
- **Errors & corrections** — what failed and how it was resolved
- **Key results** — intermediate outputs that downstream steps depend on
- **Worklog** — brief ordered record of completed steps

This layer is what makes compaction survivable. Without it, compaction destroys continuity.

#### H. Compaction

When context exceeds threshold:

- Generate compact summary
- **Preserve intact: session working memory** (task state, files touched, errors, key results, worklog)
- Preserve: recent tool outcomes, active file references
- Discard: full transcript history

#### I. Recovery Paths (MVP)

| Trigger | Response |
|---------|----------|
| Output too long | Continue generation |
| Context too long | Compact |
| Tool failure/interrupt | Ledger entry + report to loop |
| Task abort | Cleanup path executes; ledger and transcript finalized |

#### J. Role Model (skeleton only)

Four roles defined: `research`, `implementation`, `verification`, `synthesis`.

MVP constraint: implementation ≠ verification. The boundary is architectural, even before spawning is real.

### 4.2 Out of Scope

- Subagent cache sharing / git worktree isolation
- Background async workers / daemon
- Distributed event bus
- UI / dashboard
- Browser automation
- Multi-model router
- Prompt fragment DSL / execution policy language
- Scheduling / long-running orchestration

---

## 5. Session State

```python
@dataclass(slots=True)
class WorkingMemory:
    task_state: str = ""
    files_touched: list[str] = field(default_factory=list)
    errors_and_corrections: list[str] = field(default_factory=list)
    key_results: list[str] = field(default_factory=list)
    worklog: list[str] = field(default_factory=list)

@dataclass(slots=True)
class SessionState:
    session_id: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    ledger: list[LedgerEntry] = field(default_factory=list)
    loaded_topics: list[Path] = field(default_factory=list)
    working_memory: WorkingMemory = field(default_factory=WorkingMemory)
    compact_summary: str = ""
```

---

## 6. Core Control Flow

No pipeline objects. One loop.

```python
async def run_query_loop(
    user_input: str,
    state: SessionState,
    config: TurnConfig,
):
    turn = 0
    while turn < config.max_turns:
        prompt = build_prompt(state, config, user_input)
        context = build_context(state, config)

        async for event in model_stream(prompt, context):
            yield event

            if event["type"] == "tool_call":
                result = await execute_tool(event, state, config)
                yield result

            if event["type"] == "final":
                persist_state(state)
                return

        if should_compact(state, config):
            yield compact_state(state)

        turn += 1
```

---

## 7. Directory Layout

```
agent_os/
  app.py
  query_loop.py
  prompt_builder.py
  context_builder.py
  memory.py
  compaction.py
  tools.py
  ledger.py
  models.py
  storage.py
  roles.py
  tests/
```

---

## 8. Functional Requirements

| ID | Requirement |
|----|-------------|
| FR1 | Async query loop: receive input → build prompt → call model → parse tool calls → execute → ledger → compact/recover → repeat until stop |
| FR2 | Event stream as `AsyncGenerator[Event, None]` with typed events |
| FR3 | Tool registry with name, description, schema, risk, executor |
| FR4 | Ledger entry for every tool execution (input, timestamps, status, summary/error) |
| FR5 | Per-turn context assembly: rules (always) + index (always) + working memory (always) + topics (on demand) + transcripts (never) |
| FR6 | Compaction: summarize, preserve working memory, drop transcript |
| FR7 | Abort/cleanup: interrupt current tool if possible, finalize ledger and transcript |
| FR8 | Working memory maintained by loop: updated after tool results and compaction; survives compaction as first-class state |

---

## 9. Non-functional Requirements

| ID | Requirement |
|----|-------------|
| NFR1 | Core runtime readable in one sitting; centered on `query_loop.py` |
| NFR2 | Full main-path trace in ≤30 minutes; print/log/debugger friendly |
| NFR3 | Observability: every turn has transcript, every tool has ledger, every error classified, every compaction bounded |
| NFR4 | Python 3.12+, `dataclasses`, `typing`/`Protocol`/`TypedDict`/`Literal`, `asyncio`, `pathlib`; `ruff` + `pyright` + `pytest` |

---

## 10. Milestones

| # | Name | Deliverables | Exit Criteria |
|---|------|--------------|---------------|
| M1 | Heartbeat | `query_loop.py`, `models.py`, event stream, mock model adapter | Mock model multi-turn loop produces typed event stream |
| M2 | Tools + Ledger | 5 tools, registry, ledger, bash policy | Every tool call has ledger entry; bash requires approval |
| M3 | Prompt + Context | 4-layer prompt builder, memory loader, context assembler | Layers have source labels; cache/dynamic split verifiable |
| M4 | Compaction + Recovery | Threshold-based compact, working memory survival, transcript separation, abort cleanup | 3 recovery paths have integration tests; working memory intact post-compact |
| M5 | Role Model | `roles.py`, impl/verify boundary, spawn API placeholder | `RolePolicy` type exists with test assertions |

---

## 11. Success Criteria

MVP succeeds when:

1. A multi-turn task completes end-to-end: read → grep → bash → ask user → write file
2. A 10+ turn session survives at least one compaction and continues correctly
3. Every tool action has a ledger entry
4. Transcript is complete and traceable
5. Rules / memory index / working memory / transcript are provably separate layers
6. Main flow is readable in `query_loop.py` alone

---

## 12. Risks & Mitigations

| ID | Risk | Mitigation |
|----|------|------------|
| R1 | Query loop becomes a mud ball of if/else as recovery paths accumulate | Cap MVP branch types; every new recovery path requires a matching test |
| R2 | Compaction destroys task continuity | Working memory is a separate structure, never derived from transcript summary alone |
| R3 | `bash` becomes an unsafe catch-all that erodes other tool boundaries | `bash` is `high` risk by default; `read_file`/`write_file`/`grep_search` always preferred for their domain |
| R4 | Prompt layers degrade into ad hoc concatenation | Each layer carries a source label and cacheability flag; builder enforces ordering |
| R5 | "Role model only" becomes meaningless without enforcement | `RolePolicy` type + test assertions exist from M5, even before real spawning |

---

## 13. Acceptance Tests

| ID | Scenario | Expected |
|----|----------|----------|
| AT1 | Model requests `read_file` at turn 2 | Tool result in ledger; loop continues to turn 3 |
| AT2 | Context exceeds `compact_threshold_tokens` | Compaction triggers; working memory preserved; task resumes |
| AT3 | `bash` command is interrupted mid-execution | Ledger status = `interrupted`; transcript records cleanup |
| AT4 | 10+ turn session | At least one compaction occurs; task still completes |
| AT5 | Implementation role attempts self-verification | Policy rejects or flags invalid flow |
| AT6 | Model emits malformed tool call JSON | Recovery event emitted; loop does not crash |

---

## 14. Open Questions

Decisions deferred to implementation phase:

- Working memory format: structured dataclass, markdown file on disk, or both?
- `ask_user`: does it block the loop, or yield a suspend event and await resume?
- Token counting: API-reported usage, local tiktoken estimate, or char heuristic?
- Sixth tool slot: `spawn_task` or `inspect_memory`?
- Role boundary enforcement: type system, runtime assertion, or test convention only?
- Storage backend: flat files or SQLite?

---

## 15. Roadmap

| Version | Scope |
|---------|-------|
| **MVP** | Single-loop kernel — this PRD |
| **v1.5** | Session working memory persistence + role enforcement with real policy |
| **v2** | Spawned verification agent; isolated task execution |
| **vNext** | Worktree isolation, teammate/background agents, proactive loop |

---

## 16. What This Is

> An agent runtime kernel that treats Query Loop, Prompt, Memory, Tools, and Recovery as OS-level responsibilities.

**Not** a Claude Code clone. **Not** a chatbot wrapper. **Not** an orchestration platform.

The product boundary: **kernel first, city later.** Lifecycle and resource governance before features. Make it survive before making it impressive.
