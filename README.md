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
# Interactive REPL
python main.py

# One-shot mode
python main.py "Create a hello world in python"
```

## License

MIT
