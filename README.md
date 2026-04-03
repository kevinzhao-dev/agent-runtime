# Agent Template

A Python agent engine template that learns from production-grade coding agent patterns.

The core idea: **treat the model as an unreliable component, build reliability into the runtime** — state management, context governance, error recovery, permission gates. The model is just one heartbeat inside a disciplined loop.

## Quick Start

### Prerequisites

- Python 3.11+
- An Anthropic API key

### Install

```bash
cd agent-engine
pip install -e ".[dev]"
export ANTHROPIC_API_KEY="your-key-here"
```

### Run

```bash
# Interactive REPL (Rich TUI with streaming markdown, spinners)
python main.py

# One-shot mode
python main.py "Create a hello world in python"

# Debug mode (agent_engine.* logs only, no third-party noise)
python main.py --verbose

# Dry run (no API calls, mock responses)
python main.py --dry-run
```

### Slash Commands

In the interactive REPL, type `/help` to see available commands:

| Command    | Description                        |
|------------|------------------------------------|
| `/help`    | Show available commands             |
| `/history` | Show conversation turns             |
| `/log`     | Show path to session log file       |
| `/compact` | Show context compaction stats       |

Commands are modular (one file per command in `commands/`) and dual-use — invocable from the REPL or programmatically by the system.

### Test

```bash
# All tests (no API key needed)
python -m pytest tests/ -v

# Single module
python -m pytest tests/test_grep.py -v

# Single test
python -m pytest tests/test_grep.py::test_grep_basic -v
```

## License

MIT
