# Agent Engine

An AI Agent Engine featuring a core Query Loop as the system heartbeat, prompt control, a three-layer memory architecture with context window management, multi-agent support with role assignment, and tool execution.

## WHY
Learning from Claude Code's engineering practices, this project aims to build a production-grade AI Agent Engine that serves as a template for rapid adaptation to future projects.

## HOW
### Architecture - `@docs/arch.md`
**Read when:** Read arch.md when you need a holistic understanding of the system.

### Design Philosophy - `@docs/AGENT_DESIGN_PHILOSOPHY.md`
**Read when:** Planning features or discussing future design decisions. This document is extensive and covers core design principles for building effective coding agents.

### Run
```bash
# Interactive REPL
python main.py

# One-shot mode
python m

### Test
Run all tests
```bash
python -m pytest tests/ -v
```

### Project Structure
- `engine/` — Core query loop, agent runtime, session logging
- `context/` — Memory and context window management
- `roles/` — Multi-agent role definitions
- `tools/` — Tool registry and execution
- `commands/` — Modular slash commands (dual-use: user REPL + system programmatic)
- `verify/` — Verification and output validation
- `entrypoints/` — CLI, Rich display renderer, and SDK entry points
- `docs/` — Architecture and design documentation