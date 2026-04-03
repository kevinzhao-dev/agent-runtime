# Agent Design Philosophy

## Lessons from Claude Code's Harness Engineering

> **System first, model second.**
> A system's integrity is not measured by how well it speaks,
> but by who picks up the pieces when things go sideways.

---

## Principle 1: The Query Loop Is the Heartbeat

**The agent is not a function call. It is a stateful execution loop.**

Claude Code's `query.ts` is not a "receive message → call model → return result" function. It is a continuous execution loop that maintains an explicit `State` object across iterations — carrying `toolUseContext`, `autoCompactTracking`, `maxOutputTokensRecoveryCount`, `stopHookActive`, `turnCount`, and more between turns.

This means the system treats "what happens after this step fails, and whether the next step can inherit the world left behind" as a first-class concern.

### The critical insight: input governance precedes inference

Before the model is ever called, the loop runs a long chain of context preparation:

1. Memory prefetch
2. Skill discovery prefetch
3. Compact boundary truncation
4. Tool result budget enforcement
5. History snip
6. Microcompact
7. Context collapse
8. Autocompact

This ordering is itself an architectural declaration: **context governance comes before model reasoning**. The system does not delegate the responsibility of extracting order from chaos to the model. Instead, the runtime cleans the input first, then hands a tidier context to the model.

### What this means for us

- Every agent needs explicit cross-turn state — not scattered booleans and local variables.
- Input governance is not optional. The loop must clean context before calling the model.
- Interrupts must be structurally accounted for: Claude Code injects synthetic `tool_result` messages to maintain the assistant→user alternation contract even after a user abort. This is not defensive coding — it is causal closure.
- The loop must distinguish between completion, failure, recovery, and continuation. A system that cannot tell these apart is a script, not a runtime.

---

## Principle 2: The Prompt Is a Control Plane, Not a Personality Costume

**Prompt engineering is system engineering.**

Claude Code treats its system prompt as a layered, prioritized, cacheable configuration system — not a paragraph of instructions.

### Layered assembly with explicit priority

`systemPrompt.ts` defines a clear hierarchy: agent prompt > system prompt override > default prompt. Different sources — `CLAUDE.md`, project instructions, team memory, auto memory — each have designated positions, and `buildEffectiveSystemPrompt()` assembles them into a unified structure.

When an agent prompt and proactive mode coexist, the agent prompt is *appended* to the default prompt rather than replacing it. This means the system knows that baseline constraints must not be discarded — new agent roles add domain behavior on top of institutional discipline, they do not replace it.

### Cache boundary as architecture

`SYSTEM_PROMPT_DYNAMIC_BOUNDARY` explicitly separates static instructions from dynamic context. Static sections are stable across turns and hit the prompt cache; dynamic sections (like MCP instructions) use `DANGEROUS_uncachedSystemPromptSection` and are recomputed every turn. This directly affects token cost, latency, and throughput.

A prompt system that does not account for its impact on caching is not a control plane — it is a text blob.

### Behavioral codification

`getSimpleDoingTasksSection()` codifies behavioral rules as institutional policy: do not add features the user did not request; do not over-abstract; read code before modifying it; report results honestly. These are not style guidelines — they are operational discipline baked into the prompt.

### What this means for us

- Our system prompt should be a structured configuration with priority levels, section registries, and cache boundaries — not a single string.
- Allow customization, but enforce structure. Users can override content; the system retains the layering.
- Prompt is not just about "how the model talks this turn" — it should also govern how long-term knowledge is formed, how memory is saved, and what behavioral constraints apply.

---

## Principle 3: Three-Layer Memory — Treat the Context Window as a Scarce Resource

**What you choose not to load matters as much as what you load.**

Most agent memory implementations dump everything into context every turn. This is expensive and introduces noise. Claude Code takes a fundamentally different approach with a three-layer index:

| Layer | Loading Strategy | Size |
|-------|-----------------|------|
| **Index** (MEMORY.md) | Always loaded | ~150 chars per line, pointers only |
| **Topic files** | Loaded on demand | Actual knowledge content |
| **Transcripts** | Never loaded, only grep'd | Full historical records |

### Write discipline

- Write to the topic file first, then update the index.
- Never dump content into the index.
- If a fact can be re-derived from the codebase, do not store it.

### Memory consolidation is isolated

`autoDream` runs a forked subagent with limited tool access to consolidate, deduplicate, and remove contradictions from memory. This subagent is deliberately restricted to prevent it from corrupting the main context during maintenance. Memory is treated as a hint, not as truth — the agent verifies before using it.

### Five-plus compaction strategies

Context overflow is a central engineering problem. Claude Code employs autocompact, reactive compact, context collapse, microcompact, and history snip — each addressing a different failure mode. When one strategy fails, the system has a circuit breaker (consecutive failure count) to stop hammering the API with doomed compaction attempts.

### What this means for us

- Design tiered memory: cheap always-on index, on-demand detail, never-loaded archives.
- Enforce write discipline. Not everything deserves to be in memory.
- Memory consolidation should run in an isolated process that cannot pollute the main context.
- Context overflow is not an edge case — it is a primary engineering concern that demands multiple strategies and circuit breakers.

---

## Principle 4: Tool Execution Requires Permission and Restraint

**A model saying the wrong thing wastes time. A model executing the wrong command destroys your repository.**

Claude Code's tool system is built on a multi-layer permission architecture:

```
Tool Request
  → Rules Layer (allow / deny / ask)
    → Mode Layer (bypass / plan / auto / default)
      → Automated Checks (classifier / hooks / policy gates)
        → Interactive Approval (last resort, only when runtime cannot decide)
          → Final Decision: ALLOW or DENY
```

### Key design decisions

**Bash gets special treatment.** `bashPermissions.ts` applies additional safety logic to shell commands. High-risk commands trigger a classifier side-query — a separate model call that asks "Is this command safe?" — providing context-aware security that replaces brittle allowlists.

**Streaming tool execution with intelligent batching.** `StreamingToolExecutor` partitions `tool_use` blocks into serial batches and concurrency-safe batches. What can run in parallel does; what must be sequential stays sequential.

**Interrupts preserve causal integrity.** When the user aborts mid-execution, the system injects synthetic `tool_result` messages to maintain the API's required message alternation. This is not error handling — it is bookkeeping for causal continuity.

**Subagent permission isolation.** Worker agents get their own `permissionMode` (e.g., `acceptEdits`). Parent allow-rules do not leak to child agents. Permission scoping is explicit and intentional.

**Defense in depth.** Internal-only fields like `_simulatedSedEdit` are stripped from model-provided input as a safeguard, even though schema validation should already reject them. The system does not trust a single layer of defense.

### What this means for us

- Tools are not "model says call, system calls." Every tool invocation passes through a decision pipeline.
- Intent is not authorization. The model wanting to do something does not mean it should.
- Design for interruption. When a user cancels, the system must still close the books cleanly.
- Permission boundaries between parent and child agents must be explicit. Inheritance of trust is a security risk.

---

## Principle 5: Multi-Agent Means Role Separation and Independent Verification

**If all your agents do the same thing, you are just parallelizing chaos.**

Claude Code offers three subagent models: **fork** (byte-identical copy of parent context), **teammate** (async collaboration), and **worktree** (Git worktree isolation). But the real insight is not in how agents are spawned — it is in why they are separated.

### Prompt cache economics drive architecture

Forked subagents inherit parent context as byte-identical copies, so spawning five agents costs barely more than one in prompt cache terms. This is not an accident — it is a deliberate economic optimization that makes multi-agent viable at scale.

### Verification must be independent from implementation

The system explicitly distinguishes four roles: **research**, **implementation**, **verification**, and **synthesis**. The agent that writes the code and the agent that verifies it must not be the same. Otherwise, the system conflates "I finished changing it" with "it is actually correct."

This is a structural guarantee, not a suggestion. Verification is a separate phase with its own context and tools.

### Coordination is synthesis, not forwarding

The coordinator agent does not simply concatenate worker outputs. It performs genuine synthesis — understanding, reconciling, and integrating results. A coordinator that only forwards is a router, not a thinker.

### Lifecycle management is non-negotiable

- Parent abort propagates to child agents, preventing orphan tasks.
- Async agents have observable transcripts.
- Cleanup runs on every code path — not just the happy path.
- Agents have explicit lifecycle hooks for spawn, progress, and completion.

### What this means for us

- Before spawning agents, define who is responsible for what and who verifies whom.
- Optimize for prompt cache sharing across agents — it determines whether multi-agent is economically viable.
- Verification agents must have independent context. They cannot share the implementation agent's confirmation bias.
- Every agent must be observable, abortable, and cleanable. An agent you cannot stop or inspect is a liability.

---

## Summary: The Five Commitments

| # | Principle | Core Question |
|---|-----------|---------------|
| 1 | **Query Loop as Heartbeat** | Can the system survive the next turn after a failure? |
| 2 | **Prompt as Control Plane** | Is the prompt a structured, cacheable, layered configuration — or a text blob? |
| 3 | **Three-Layer Memory** | Does the system treat its context window as a scarce resource? |
| 4 | **Tool Permission & Restraint** | Does every tool call pass through an explicit decision pipeline? |
| 5 | **Role Separation & Verification** | Are implementation and verification structurally independent? |

---

## The Harness Thesis

> Drop a different model into the same well-built harness, and you may get
> comparable or better results. But drop the best model into a system with
> no loop discipline, no context governance, no permission boundaries, and
> no recovery paths — and you get an impressive demo that breaks in production.

The harness is not scaffolding to be removed later. It is the product. The model is a component — powerful, essential, but insufficient on its own. What makes a system reliable is not how smart the model is, but how hard the constraints are.

**System first. Model second.**

---

## References & Further Reading

- **Architecture overview:** [deepwiki.com/zackautocracy/claude-code](https://deepwiki.com/zackautocracy/claude-code)
- **Unpacked analysis:** [ccunpacked.dev](https://ccunpacked.dev/)
- **Source code analysis:** [VentureBeat coverage](https://venturebeat.com/technology/claude-codes-source-code-appears-to-have-leaked-heres-what-we-know)
- **Xiao Tan's deep dive:** Claude Code 源碼架構深度解析 V2.0
- **Harness Engineering books:** *Claude Code 設計指南* & *Comparative Harness Notes* (agentway.dev)
