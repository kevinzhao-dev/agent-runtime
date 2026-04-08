# Agent Runtime Kernel — Implementation Plan

## Goal
Build a minimal, clean agent runtime kernel in Python. Query Loop as heartbeat. Prompt as control plane. Context as scarce resource. Tools as managed syscalls. Recovery as first-class semantics.

Key constraint: **simplicity**. This kernel is a template for future agent tasks.

---

## Decisions Log

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Working memory format | dataclass in memory + JSON on disk | Programmatic + human-readable |
| Token counting | char heuristic (`len/3.5`) | Good enough for MVP, upgrade later |
| `ask_user` | yield suspend event + await resume | Consistent with async generator |
| Storage | flat files (JSON + markdown) | No premature optimization |
| Provider | Anthropic + OpenAI-compatible (2 adapters) | Covers 90% of use cases |
| Code style | Simple, readable, minimal | Template for future projects |

---

## Directory Layout

```
agent_runtime/
  __init__.py
  query_loop.py         # Core async loop (M1)
  models.py             # Event types, State, TurnConfig, dataclasses (M1)
  provider.py           # Model provider abstraction + streaming (M1)
  tools/                # Tool system (M2)
    __init__.py
    base.py             # ToolSpec, ToolRegistry, LedgerEntry
    bash.py
    read_file.py
    write_file.py
    grep_search.py
    ask_user.py
  prompt.py             # 4-layer prompt builder (M3)
  context.py            # Context assembler (M3)
  memory.py             # 3-layer memory loader (M3)
  compaction.py         # Compact + working memory survival (M4)
  roles.py              # Role model skeleton (M5)
  storage.py            # Flat file persistence
  app.py                # CLI entrypoint (thin)
  tests/
```

---

## Milestones

### M1 — Heartbeat (Loop + Events + Provider)
> Goal: Mock model multi-turn loop produces typed event stream

- [ ] **M1.1** Define core data models (`models.py`)
  - Event types: `ThinkingEvent`, `TextDeltaEvent`, `ToolCallEvent`, `ToolResultEvent`, `RecoveryEvent`, `FinalEvent`
  - Tagged union with `Literal` discriminator field
  - `TurnConfig` dataclass (frozen)
  - `WorkingMemory` dataclass
  - `SessionState` dataclass (mutable)
  - Neutral message format types

- [ ] **M1.2** Model provider abstraction (`provider.py`)
  - Provider registry (dict of provider metadata)
  - `detect_provider(model_name)` auto-detection
  - `stream()` unified entry point → yields `TextChunk | ThinkingChunk | AssistantTurn`
  - Anthropic streaming adapter
  - OpenAI-compatible streaming adapter
  - Neutral message format converters (`to_anthropic`, `to_openai`)
  - Tool schema converter (`to_openai_tools`)

- [ ] **M1.3** Core query loop (`query_loop.py`)
  - `async def run_query_loop()` as `AsyncGenerator[Event, None]`
  - Explicit `State` object carried across iterations
  - Immutable params (`TurnConfig`) + mutable state (`SessionState`) separation
  - Turn counting + max_turns guard
  - Mock model adapter for testing
  - Placeholder hooks for tool execution, compaction, recovery

- [ ] **M1.4** Tests for M1
  - Mock model multi-turn loop produces typed event stream
  - Event ordering is correct
  - Turn counting works
  - Provider auto-detection works

---

### M2 — Tools + Ledger
> Goal: Every tool call has ledger entry; bash requires approval

- [ ] **M2.1** Tool base system (`tools/base.py`)
  - `ToolSpec` dataclass: name, description, input_schema, risk, side_effecting
  - `ToolRegistry`: register, lookup, get_schemas, execute
  - `LedgerEntry` dataclass: tool_name, input, status, timestamps, summary, error
  - Permission model: low-risk = auto, high-risk = ask

- [ ] **M2.2** Implement 5 tools
  - `read_file` — low risk, read file content
  - `write_file` — low risk, write file content
  - `bash` — **high risk**, shell execution with approval gate
  - `grep_search` — low risk, regex file search
  - `ask_user` — low risk, yield suspend event

- [ ] **M2.3** Wire tools into query loop
  - Tool call parsing from model response
  - Permission check before execution
  - Ledger entry creation (start/end timestamps, status)
  - Tool result injection back into conversation
  - Output truncation for large results

- [ ] **M2.4** Tests for M2
  - Every tool call produces a ledger entry
  - `bash` requires approval (permission gate works)
  - Tool result appears in conversation history
  - Malformed tool call JSON → recovery event, no crash

---

### M3 — Prompt + Context
> Goal: Layers have source labels; cache/dynamic split verifiable

- [ ] **M3.1** 4-layer prompt builder (`prompt.py`)
  - Layer 1: Base system prompt (identity, constraints, tool descriptions) — cacheable
  - Layer 2: Project rules (`AGENT.md`, `PROJECT.md`) — cacheable
  - Layer 3: Runtime mode additions — dynamic
  - Layer 4: Task context (current state, recent tool outcomes) — dynamic
  - Each layer carries source label + cacheability flag
  - Builder enforces ordering

- [ ] **M3.2** Memory loader (`memory.py`)
  - 3-layer memory model:
    - Rules: always loaded (AGENT.md, PROJECT.md)
    - Memory index: always loaded (MEMORY.md — pointers only)
    - Topic files: loaded on demand
  - Transcripts: never in prompt, stored separately
  - Write discipline: index is pointers, not content

- [ ] **M3.3** Context assembler (`context.py`)
  - Assemble per-turn context: rules + index + working memory + topics (on demand)
  - Working memory always included (survives compaction)
  - Source labels on each section

- [ ] **M3.4** Tests for M3
  - Prompt layers have correct ordering and labels
  - Cache/dynamic split is verifiable
  - Memory index loaded every turn
  - Topic files loaded only on demand

---

### M4 — Compaction + Recovery
> Goal: 3 recovery paths have integration tests; working memory intact post-compact

- [ ] **M4.1** Compaction (`compaction.py`)
  - Char heuristic token estimation (`len/3.5`)
  - Threshold-based compact trigger
  - Generate compact summary (LLM call)
  - Preserve intact: session working memory
  - Preserve: recent tool outcomes, active file references
  - Discard: full transcript history

- [ ] **M4.2** Recovery paths
  - Output too long → continue generation
  - Context too long → compact
  - Tool failure/interrupt → ledger entry + report to loop
  - Task abort → cleanup path (finalize ledger + transcript)

- [ ] **M4.3** Working memory maintenance
  - Updated after tool results
  - Survives compaction as first-class state
  - Tracks: task state, files touched, errors/corrections, key results, worklog

- [ ] **M4.4** Tests for M4
  - Compaction triggers at threshold
  - Working memory preserved after compaction
  - 10+ turn session with at least one compaction completes
  - Each recovery path has integration test

---

### M5 — Role Model (skeleton)
> Goal: `RolePolicy` type exists with test assertions

- [ ] **M5.1** Role definitions (`roles.py`)
  - 4 roles: research, implementation, verification, synthesis
  - `RolePolicy` dataclass with allowed_tools, constraints
  - Architectural boundary: implementation != verification

- [ ] **M5.2** Tests for M5
  - Implementation role cannot self-verify (policy assertion)
  - Role boundaries are enforced at type level

---

### M6 — Integration + CLI
> Goal: End-to-end task completes

- [ ] **M6.1** Storage (`storage.py`)
  - Session save/load (JSON)
  - Transcript storage (separate file)
  - Working memory persistence (JSON on disk)

- [ ] **M6.2** CLI entrypoint (`app.py`)
  - Thin REPL: input → query loop → render events
  - Session management (new/resume)
  - Ctrl+C handling (abort path)

- [ ] **M6.3** End-to-end acceptance tests
  - AT1: Model requests `read_file` at turn 2 → ledger entry, loop continues
  - AT2: Context exceeds threshold → compact, working memory preserved
  - AT4: 10+ turn session completes with compaction
  - AT6: Malformed tool call → recovery, no crash

---

## Review

### Summary
All 6 milestones completed. **163 tests, all passing, 0 API calls required.**

### What was built
| Module | Lines | Purpose |
|--------|-------|---------|
| `models.py` | 120 | Event types, TurnConfig, SessionState, WorkingMemory, message helpers |
| `provider.py` | 260 | Provider registry, auto-detection, 2 streaming adapters, message converters |
| `query_loop.py` | 185 | AsyncGenerator loop with State, mock adapter, permission, ledger integration |
| `tools/base.py` | 110 | ToolSpec, ToolRegistry, LedgerEntry, output truncation |
| `tools/*.py` | 130 | 5 tools: read_file, write_file, bash, grep_search, ask_user |
| `prompt.py` | 100 | 4-layer prompt builder with source labels and cache/dynamic split |
| `memory.py` | 75 | 3-layer memory: rules (always), index (always), topics (on demand) |
| `context.py` | 65 | Context assembler with working memory + ledger + compact summary |
| `compaction.py` | 100 | Heuristic compaction with working memory survival |
| `roles.py` | 80 | 4 roles, RolePolicy type, impl!=verify boundary |
| `storage.py` | 85 | Flat file persistence (JSON state + JSONL transcript) |
| `app.py` | 95 | Thin CLI REPL |
| **Total** | **~1,400** | |

### Key design decisions
1. **Async generator loop** — yields typed events, caller controls rendering
2. **Immutable TurnConfig + mutable SessionState** — clean separation
3. **Tool registry pattern** — add a tool = add a file + register()
4. **Permission callback** — injected, not hardcoded. Default: auto for low-risk, deny for high-risk
5. **Compaction preserves working memory** — the critical insight from Claude Code
6. **Provider abstraction** — neutral message format, 2 adapters cover all providers

### PRD success criteria status
- [x] Multi-turn task end-to-end (read → grep → write)
- [x] 10+ turn session survives compaction
- [x] Every tool action has a ledger entry
- [x] Rules / memory index / working memory / transcript are separate layers
- [x] Main flow readable in query_loop.py alone (~185 lines)
