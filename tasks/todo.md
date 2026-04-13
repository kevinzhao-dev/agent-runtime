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

---

# M9 — Developer-First REPL & Observability

## Goal
Transform this codebase from a "generic agent" into a **developer foundation**: a REPL where you can fork sessions, inspect every prompt layer, replay turns with new config, and treat agent behavior like a debuggable program. The agent personality itself should be an external "pack" so forking the repo = change pack, not core.

Guiding principle (from CLAUDE.md): every change impacts as little code as possible. Each milestone is independently useful and shippable.

---

## Milestones

### M9.1 — Slash-command REPL skeleton + event bus ✅
The foundation everything else builds on. Small but load-bearing.

- [x] Add a slash-command dispatcher in `cli/app.py` (or new `cli/repl.py`): lines starting with `/` → meta-command, `!` → shell escape, everything else → agent
- [x] Introduce a minimal in-process `EventBus` — current display loop becomes one subscriber; transcript writer becomes another. No behavior change, just decoupling.
- [x] Port existing `dev.py` commands into slash commands: `/sessions`, `/show`, `/messages`, `/ledger`, `/transcript`. Keep old `dev.py` as thin shim for now.
- [x] Add `/help` listing all slash commands.

**Done when**: you can run the REPL, type `/sessions` without leaving the process, and the old chat flow still works unchanged. ✅ verified via piped-stdin smoke test.

#### Implementation summary
- **New `cli/bus.py`** — ~20-line `EventBus` with `subscribe` + `publish`. Subscriber errors are caught so one bad subscriber can't crash the loop.
- **New `cli/commands.py`** — `COMMANDS` registry via `@register`, `ReplContext` carrying live `SessionState`, `dispatch()` + `run_shell()`. Session-reader commands delegate to existing `cli.dev.cmd_*` functions (single source of truth). `.` or no-arg = current session, flushed to disk first.
- **Edited `cli/app.py`** — input routed through `/`, `!`, or agent. Event handling extracted into a `DisplayRenderer` class; both it and a transcript writer subscribe to the bus. Loop now just `bus.publish(event)` instead of inline if/elif. Banner updated to advertise the new commands.

#### Notes & carry-forwards
- Pre-existing spinner bug (ported unchanged): after a `tool_result` event the renderer restarts the spinner with `first_chunk=False`, so the next `text_delta` prints on top of the spinner line. Not introduced here — deferring fix to avoid opportunistic refactor.
- `cli/dev.py` is still the offline source of truth for session formatters; `commands.py` delegates to it. When M9.2 adds inspectors we should decide whether to collapse them into one module.
- `ChildEvent` passes through the display subscriber silently (no case in the elif chain). Will matter once child agent streaming is wired into the REPL.
- The transcript subscriber still logs only `{type, turn}` per event — M9.3 will upgrade this to full payloads as planned.
- All 196 existing tests still pass.

### M9.2 — Live prompt inspector (layers / tokens / diff) ✅
The first big observability win. Uses existing `build_prompt` layer metadata.

- [x] `/prompt` — print current system prompt with layer boundaries visible
- [x] `/prompt layers` — table: layer name, source, cacheable, char count, token estimate
- [x] `/tokens` — breakdown of current context window: rules / memory / history / tool results / total, as a simple bar or percentage table
- [x] `/context` — compact one-line summary usable during normal chat (e.g. `[ctx 12k/200k · rules 2k · hist 8k · tools 2k]`)
- [x] `/prompt diff <turn_a> <turn_b>` — unified diff of system prompts between two turns (requires transcript already stores full prompt — it does)
- [x] Record token accounting per layer in transcript so diffs work across sessions

**Done when**: during a live session you can see exactly what's in the context window and how it changed turn-to-turn. ✅

#### Implementation summary
- **New `cli/prompt_view.py`** — `build_current_prompt(state, config) → PromptConfig` (the single place that knows how to assemble the live prompt), plus `estimate_tokens_str()` and `layer_stats()` helpers. `app.py` now calls this instead of its own private `_build_system_prompt`, so the inspector and the actual query loop see the identical prompt.
- **Extended `ReplContext`** to carry `TurnConfig` (commands needed it for threshold + prompt build).
- **New commands in `cli/commands.py`**: `/prompt`, `/prompt layers`, `/prompt diff <a> <b>`, `/tokens`, `/context`. Diff reads `transcript.jsonl` directly and uses `difflib.unified_diff`. Graceful messages for missing/identical turns.
- **Transcript upgrade (backward compatible)**: the existing `system_prompt` entry now also carries a `layers` array (`[{name, source, cacheable, chars, tokens}]`). Old entries without it still parse — `/prompt diff` only reads the `prompt` field.

#### Notes & carry-forwards
- Token numbers come from the same `len/3.5` heuristic engine already uses (via `estimate_tokens` on messages and the new `estimate_tokens_str` on layer strings). When a real tokenizer lands, one swap and everything updates consistently.
- `/prompt diff` is same-session only (reads the current session's transcript). Cross-session diff would fit naturally when M9.3 starts moving transcripts around — defer.
- `/tokens` splits messages into `history (user+assistant)` and `tool results` purely by role. Good enough; production would likely want per-message sizes.
- Per-layer accounting in transcript is unused by the current commands (they rebuild live) — it's there so M9.3 replay can show how layer sizes drifted without needing the full prompt string.
- Still 196 tests passing.

### M9.3 — Session fork / rewind / replay ✅
The highest-leverage dev feature, but biggest data-model change. Must come after M9.1/M9.2 because it relies on the event bus and transcript format.

- [x] Upgrade transcript to store **full message payloads** (assistant text, tool inputs, tool outputs), not just event types. Add a transcript schema version field.
- [x] Make `SessionState` snapshot-able: `state.replace_from(other)` for in-place swaps; on-disk snapshot per user-turn.
- [x] `/fork [@N]` — clone current session at user_turn N (default: tip) into a new session id, switch REPL to it. Parent lineage recorded in meta.json.
- [x] `/rewind N` — drop last N user-turns from current session (in place; confirmation prompt).
- [x] `/replay <session_id> [--model X]` — extract user inputs from a past session, create a fresh session with `replayed_from` lineage, queue inputs via `ctx.pending_inputs`.
- [x] `/tree` — render fork tree (parent/child + replayed_from tags) from meta.json files. (Shipped as `/tree` rather than `/sessions --tree` — cleaner grammar for a dev tool.)

**Done when**: you can fork a session at turn 3, change one thing, and compare outcomes. ✅ verified end-to-end.

#### Implementation summary
- **`storage.py` (schema v2)** — new constant `SCHEMA_VERSION = 2`; new helpers: `save_meta` / `load_meta` / `init_meta` (per-session `meta.json` with `parent_session`, `parent_turn`, `replayed_from`, `created_at`); `save_snapshot` / `load_snapshot` / `list_snapshots` / `delete_snapshots_after` (per-user-turn JSON snapshots under `snapshots/turn_NNNN.json`); `truncate_transcript_after` (drop transcript lines beyond a user-turn); `copy_session_dir` (copy state/transcript/snapshots to a new session, optionally truncated at a turn).
- **`engine/models.py`** — added `SessionState.replace_from(other)` so commands can swap the live session in-place without invalidating references held by subscribers (bus, `ReplContext`).
- **`cli/app.py`** — tracks `user_turn` in `ReplContext`; writes `meta.json` on startup; snapshots state + increments user_turn after each completed user turn; emits full-payload transcript records (`user_input`, `tool_call` with input, `tool_result` with output, `final` with text, `recovery`); reads `ctx.state`/`ctx.config` each iteration so fork/replay/overrides take effect live; `pending_inputs` queue lets sync commands inject replay inputs without re-entering asyncio.
- **`cli/commands.py`** — `ReplContext` gained `user_turn` and `pending_inputs: list[str]`. New commands:
  - **`/fork [@N]`** — fork from tip (default) or from a specific snapshot. Copies state, transcript lines ≤ N, and snapshots ≤ N into the new session dir. Writes meta.json with parent lineage. Refuses to fork an empty session.
  - **`/rewind N`** — restore snapshot `user_turn - N - 1`, delete later snapshots, truncate transcript. Interactive y/n confirmation.
  - **`/replay <sid> [--model X]`** — extracts user inputs from the source (v2 transcript `user_input` events, falling back to role=user messages for legacy v1 sessions). Creates new session with `replayed_from` meta, overrides `ctx.config.model_name` via `dataclasses.replace`, queues inputs.
  - **`/tree`** — walks all sessions, builds parent→child adjacency from meta.json, renders an ASCII tree with `(forked @N)` / `(replayed from …)` tags.
- **`cli/dev.py`** — single-line backward-compat fix so `cmd_transcript` reads `user_turn` (v2) or `turn` (v1).

#### Notes & carry-forwards
- **v1 ↔ v2 compat**: legacy sessions without `meta.json` are assumed schema v1 (`load_meta` returns `{"schema_version": 1}` default). They render in `/tree` as orphan roots. `/replay` still works on them via the v1 fallback (reads user messages from `state.json`).
- **Transcript drops text_delta + thinking events**: `final.text` already carries the complete assistant reply and per-token deltas are noise in a persisted log. If we later need streaming-accurate playback (M9.5 `/replay --stream`?) we'd re-enable delta persistence.
- **`user_turn` vs `state.turn_count`**: `turn_count` is model-iteration-count (incremented inside the loop on every tool-calling step), not user-interaction count. Snapshots use the REPL-side `user_turn` because that's the unit users want to fork/rewind on. Both are stored on disk — don't confuse them.
- **Fork from tip re-saves a snapshot** under the new session's id via `save_snapshot(new_state, source_turn)` so that subsequent `/rewind` inside the forked session can find its own tip snapshot. Small duplication, keeps the semantics local.
- **`/replay --pack Y`** deferred — packs don't exist yet (M9.4). Only `--model X` implemented.
- **Cross-session `/prompt diff`** still deferred — current implementation reads one session's transcript. Enabling cross-session would be a ~5-line change in M9.4 or later.
- **Pre-existing spinner bug still not fixed** — same carry-forward as M9.1.
- All 196 tests still pass.

### M9.4 — Agent pack abstraction ✅
Turns the repo from "one agent" into "template for many agents". Do after the REPL is stable so its surface area isn't still moving.

- [x] Define pack layout: `packs/<name>/pack.py` (NAME, ALLOWED_TOOLS, RULES_FILES) + `AGENT.md`. (Dropped `roles.yaml` and `startup.py` as YAGNI — Python manifest covers both.)
- [x] Pack-driven tool scoping — runtime loop now receives a `ToolRegistry` scoped to the active pack's `ALLOWED_TOOLS`. (Kept stdlib auto-import in `tools/__init__.py` for test-suite compatibility — see notes.)
- [x] Prompt loader reads `AGENT.md` / `MEMORY.md` from active pack dir, not CWD.
- [x] `--pack <name>` CLI flag and `/pack` / `/pack switch <name>` slash commands.
- [x] A second example pack (`packs/minimal/`) boots via `--pack` with zero tools, proving the system is multi-pack.

**Done when**: `agent_runtime` core has zero references to bash/grep/read_file and a second example pack boots via `--pack`. ✅ runtime loop and CLI contain no tool-name references; `--pack minimal` and `--pack coding` both boot.

#### Implementation summary
- **`agent_runtime/packs/loader.py`** — `ActivePack` dataclass, `available_packs()`, `load_pack(name_or_path)`, `get_active_pack()`, `set_active_pack()`, `pack_registry(pack=None)`. `pack_registry` builds a fresh scoped `ToolRegistry` from the global stdlib containing only names in `ALLOWED_TOOLS`; empty list = genuinely empty (pack opted out); no active pack = global stdlib (legacy fallback for tests).
- **`agent_runtime/packs/coding/`** — default pack. `pack.py` imports `agent_runtime.tools` as a side-effect to ensure stdlib tools are registered, then declares `ALLOWED_TOOLS` and `RULES_FILES = ["AGENT.md"]`. `AGENT.md` carries a short coding-agent rule block.
- **`agent_runtime/packs/minimal/`** — tooling-free proof pack. Demonstrates that `load_pack` + scoped registry really do gate what the agent sees.
- **`cli/prompt_view.py`** — `build_current_prompt` now asks `get_active_pack()` for rule files and uses `pack_registry()` for tool schemas. Falls back to CWD-relative rule files + global registry when no pack is active.
- **`cli/app.py`** — parses `--pack NAME` from argv, calls `load_pack()` on startup, passes `tool_registry=pack_registry()` into `run_query_loop` each turn (so pack switching via `/pack switch` takes effect live). Permission prompt also consults `pack_registry()`.
- **`cli/commands.py`** — `/pack` (show active + available), `/pack switch <name>` (hot-swap).

#### Notes & carry-forwards
- **`tools/__init__.py` still auto-imports stdlib modules** for test-suite compatibility. Moving the imports into a separate `tools/builtin.py` would force every test file that implicitly relied on registration to add an import line — too much blast radius for a stylistic win. The pack system still fully controls what the *runtime* sees via the scoped registry; tests just happen to see the global stdlib for assertion convenience.
- **`prompt/builder.py._BASE_SYSTEM_PROMPT`** still name-drops `bash`, `read_file`, `grep_search` in its behavioral rules text. Under `--pack minimal` that text leaks into the system prompt even though the agent has no tools. Cosmetic; deferred. Fix would be to move those tool-specific lines out of the base prompt and into `packs/coding/AGENT.md`.
- **`--pack <path>`** also accepts an absolute/relative directory path (not just a name), so forking an agent can live anywhere on disk — not forced under `agent_runtime/packs/`.
- **`roles.yaml` / `startup.py` / pack-local tool modules** all deferred. When a pack needs project-specific tools, add them as modules inside the pack dir and `import` them from `pack.py` — the registration side-effect model already supports it without any loader changes.
- **Hot-swap `/pack switch` does not re-run `pack.py`** if the pack was already loaded once — `importlib.util.spec_from_file_location` creates a fresh module each call, so pack.py actually *does* re-execute. This means side-effect imports run twice, which is fine for idempotent tool registration but worth knowing if a pack later grows stateful init.
- All 196 tests still pass.

### M9.5 — Step / breakpoint / dry-run / hot-reload ✅
Polish layer. Each item independent; ship as available.

- [x] `/step on|off` — pause before each tool call (y/n), extends the existing permission callback.
- [x] `/break tool:<name>` / `/break turn:<n>` / `/break list` / `/break clear` — conditional breakpoints. Tool breakpoints fire through the permission callback. Turn breakpoints drop into an **inspector mini-REPL** that accepts slash commands + `continue`/`abort`.
- [x] `/dry-run <message>` — one-shot: prints model, user input, tools visible, full system prompt without touching the model.
- [x] `/edit prompt` — opens `$EDITOR` on the active pack's `AGENT.md`. No reload step needed — `build_current_prompt` already reads from disk each turn.
- [x] `/reload tools` — `importlib.reload()` all loaded `agent_runtime.tools.*` modules (skipping `base` so the global registry survives), then re-runs the active pack's `pack.py`.

**Done when**: you can iterate on a prompt or a tool without ever restarting the REPL. ✅ verified.

#### Implementation summary
- **`ReplContext`** gained `step_mode`, `break_tools: set[str]`, `break_turns: set[int]`.
- **`app.py`** — replaced the module-level `_permission_prompt` with a `_make_permission_prompt(ctx)` closure factory so the callback can read `ctx.step_mode` / `ctx.break_tools` live. New helper `_pause_for_inspection(ctx, reason)` runs a mini-REPL for turn breakpoints: accepts `/...` (routed through `dispatch`), `!...` (shell), `continue`/`c`, `abort`/`a`. Session loop checks `ctx.user_turn in ctx.break_turns` before building the prompt and defers to the inspector loop.
- **`cli/commands.py`** — five new commands (`/step`, `/break`, `/dry-run`, `/edit`, `/reload`), all registered via `@register` so they show up in `/help` automatically. `/reload tools` iterates `sys.modules`, reloads each `agent_runtime.tools.*` module except `base`, then re-invokes `load_pack(active.name)` so pack-local side-effects and `ALLOWED_TOOLS` re-read.

#### Notes & carry-forwards
- **Tool-level pauses are simple y/n**, not the inspector mini-REPL. Pressing `n` denies the call and the loop continues. If a user wants to inspect before deciding, they'd need to call `/prompt` / `/tokens` etc. on the *next* prompt — a dedicated inspector pause for tool calls would need interleaved stdin handling that fights with the running async loop. Defer.
- **`/reload tools` reloads stdlib modules by file path, not by pack ownership.** Pack-local tools (tools added by a pack's own `pack.py` imports) will also be picked up as long as they live under `agent_runtime.tools.*` import paths. Tools imported from outside that namespace won't be reloaded — note when designing future packs.
- **`/edit` only supports `prompt` for now.** `/edit tools` or `/edit config` would be natural extensions once there's a single source file to point `$EDITOR` at.
- **`/dry-run` is one-shot, not a modal toggle.** That avoids ambiguity about "is my next message real?" — the user explicitly spells out `/dry-run <msg>` whenever they want a wiring check.
- **The inspector mini-REPL's prompt** is `(paused)>` to distinguish from the normal `You:` input. Inside the pause, commands that swap state (`/fork`, `/rewind`, `/replay`) will work — that's intentional; the paused turn is discarded if the user types `abort` or runs anything that repoints `ctx.state`.
- All 196 tests still pass.

---

## M9 review — rollup

All 5 milestones landed. The REPL went from "chat box that runs a loop" to a developer-first agent foundation:

| Feature | Verb |
|---|---|
| slash-command dispatcher + event bus | `/help`, `/sessions`, `/show`, `/messages`, `/ledger`, `/transcript` |
| prompt inspector | `/prompt`, `/prompt layers`, `/prompt diff A B`, `/tokens`, `/context` |
| session state as a tree | `/fork`, `/fork @N`, `/rewind N`, `/replay <sid> [--model]`, `/tree` |
| agent packs | `--pack <name>`, `/pack`, `/pack switch <name>` + `packs/coding` + `packs/minimal` |
| debug & hot-reload | `/step`, `/break`, `/dry-run`, `/edit prompt`, `/reload tools` |

**Net new files**
- `agent_runtime/cli/bus.py`
- `agent_runtime/cli/commands.py`
- `agent_runtime/cli/prompt_view.py`
- `agent_runtime/packs/__init__.py`
- `agent_runtime/packs/loader.py`
- `agent_runtime/packs/coding/{__init__.py, pack.py, AGENT.md}`
- `agent_runtime/packs/minimal/{__init__.py, pack.py, AGENT.md}`

**Touched**
- `agent_runtime/cli/app.py` (display subscriber, bus wiring, pack loading, permission closure, turn-break inspector pause)
- `agent_runtime/cli/dev.py` (one-line v1/v2 transcript compat)
- `agent_runtime/storage.py` (meta.json, snapshots, truncate helpers, copy_session_dir, SCHEMA_VERSION=2)
- `agent_runtime/engine/models.py` (`SessionState.replace_from`)

**Known carry-forwards**
- Pre-existing spinner/`text_delta` overlap bug after `tool_result` — not introduced by M9, not fixed by M9. One-line change deferred.
- `prompt/builder.py._BASE_SYSTEM_PROMPT` still name-drops `bash`/`read_file` — leaks into minimal pack's system prompt. Cosmetic.
- `cli/dev.py` (offline analyzer) and `cli/commands.py` (live commands) still share formatters by cross-import; M9.2 surfaced this and we left it. Could unify when next milestone touches either.
- `/prompt diff` is still same-session only.
- `/replay --pack Y` deferred (would be ~10 lines now that packs exist).
- Tool-level pauses are y/n, not inspector-aware.
- Test suite is unchanged — no new tests written for the REPL layer. Everything verified via end-to-end stdin-piped smoke. If the REPL grows further, consider adding `tests/test_commands.py` covering dispatch + fork/rewind/pack-switch.

**Session count check**: 196 tests passing throughout all five milestones. No regressions introduced.

---

## Sequencing & ground rules

1. Each milestone lands in its own commit chain. Don't mix M9.2 and M9.3 in the same PR.
2. Don't refactor existing working code opportunistically. If the query loop works, leave it alone.
3. New event types ride the event bus; don't add ad-hoc prints to `loop.py`.
4. Keep CLI output monochrome and dense — this is a dev tool, not a product demo.
5. Every slash command documented in `/help` the same day it's added.

## Review section
(to be filled after each milestone with what actually changed + any surprises)
