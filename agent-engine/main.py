"""CLI entry point for agent-engine."""

import asyncio

from entrypoints.cli import run_repl


def main():
    asyncio.run(run_repl())


if __name__ == "__main__":
    main()
