"""CLI entry point for agent-engine.

Usage:
    python main.py                          # Interactive REPL
    python main.py "Build a hello server"   # One-shot mode
    python main.py --dry-run                # Dry run (no API calls)
    python main.py --verbose                # Debug logging
    python main.py --dry-run --verbose      # Best for understanding workflow
"""

import argparse
import asyncio
import logging
import sys

from entrypoints.cli import run_repl
from engine.state import DoneEvent, ErrorEvent, TextEvent, ToolUseEvent
from roles.config import ROLE_REGISTRY
from tools.permission import PermissionMode


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Agent Engine — AI coding agent",
        prog="agent-engine",
    )
    parser.add_argument(
        "prompt",
        nargs="?",
        help="Task description (omit for interactive REPL mode)",
    )
    parser.add_argument(
        "--role",
        choices=list(ROLE_REGISTRY.keys()),
        default="default",
        help="Agent role (default: default)",
    )
    parser.add_argument(
        "--permission",
        choices=["default", "yolo", "strict"],
        default="default",
        help="Permission mode for tool execution",
    )
    parser.add_argument(
        "--working-dir",
        default=None,
        help="Working directory (default: current directory)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Use a mock client (no real API calls)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging to stderr",
    )
    args = parser.parse_args()

    _setup_logging(args.verbose)

    client = None
    if args.dry_run:
        from engine.dry_run import DryRunClient
        client = DryRunClient()

    if args.prompt:
        asyncio.run(_run_one_shot(args, client=client))
    else:
        asyncio.run(run_repl(
            role_config=ROLE_REGISTRY[args.role],
            permission_mode=PermissionMode(args.permission),
            working_dir=args.working_dir,
            client=client,
        ))


async def _run_one_shot(args, client=None):
    """Run a single prompt and exit."""
    from entrypoints.sdk import AgentEngine

    role = ROLE_REGISTRY[args.role]
    engine = AgentEngine(
        role=role,
        working_dir=args.working_dir,
        permission_mode=args.permission,
    )

    async for event in engine.run(args.prompt, client=client):
        match event:
            case TextEvent(text=text):
                print(text, end="", flush=True)
            case ToolUseEvent(tool_name=name):
                print(f"\n[Tool: {name}]", file=sys.stderr)
            case ErrorEvent(error=err):
                print(f"\n[Error: {err}]", file=sys.stderr)
            case DoneEvent():
                pass

    print()  # Final newline


if __name__ == "__main__":
    main()
