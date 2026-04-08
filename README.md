# Agent Runtime Kernel

A minimal agent runtime in modern Python. Query Loop as heartbeat. Prompt as control plane. Context as scarce resource. Tools as managed syscalls.

## Quick Start

```bash
# Install dependencies
pip install anthropic openai

# Run the agent REPL (default model: gpt-5.4-mini)
python -m agent_runtime.app

# Use a different model
python -m agent_runtime.app claude-sonnet-4-6
python -m agent_runtime.app deepseek-chat
```

Set your API key first:
```bash
export OPENAI_API_KEY="sk-..."
# or
export ANTHROPIC_API_KEY="sk-ant-..."
```

Expected output:
```
Agent Runtime v0.1.0 | Session: bf1520fa6d7d
Model: gpt-5.4-mini | Max turns: 8
Type 'quit' to exit.

You: read README.md
⠋ Thinking...
Reading the file...
[Tool: read_file]
  → ok
The README contains...
```

## Dev Tools

```bash
# List saved sessions
python -m agent_runtime.dev sessions

# Inspect a session
python -m agent_runtime.dev show <session_id>
python -m agent_runtime.dev messages <session_id>
python -m agent_runtime.dev ledger <session_id>

# View system prompt (current or from a past session)
python -m agent_runtime.dev prompt
python -m agent_runtime.dev prompt <session_id>

# Compare two sessions
python -m agent_runtime.dev compare <id1> <id2>
```

## Run Tests

```bash
pip install pytest pytest-asyncio
python -m pytest agent_runtime/tests/ -v
```

163 tests, 0 API calls.

## Architecture

```
agent_runtime/
  __main__.py          # Entry point: python -m agent_runtime
  engine/              # Core runtime kernel
    loop.py            #   Async query loop — the heartbeat
    models.py          #   Event types, TurnConfig, SessionState, WorkingMemory
    compaction.py      #   Context compaction with working memory survival
  provider.py          # Multi-provider streaming (Anthropic + OpenAI-compatible)
  prompt/              # Prompt control plane
    builder.py         #   4-layer prompt builder (base > project > mode > task)
    memory.py          #   3-layer memory (rules > index > topics)
    context.py         #   Per-turn context assembler
  tools/               # 5 tools: read_file, write_file, bash, grep_search, ask_user
  roles/               # Role model (research, implementation, verification, synthesis)
  storage.py           # Session persistence (JSON + JSONL)
  cli/                 # CLI layer
    app.py             #   Interactive REPL
    dev.py             #   Developer analysis tools
    display.py         #   Spinner, formatting
```
