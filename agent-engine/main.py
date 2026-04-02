"""CLI entry point for agent-engine."""

import argparse
import asyncio

from entrypoints.cli import run_repl
from tools.permission import PermissionMode


def main():
    parser = argparse.ArgumentParser(description="Agent Engine")
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
    args = parser.parse_args()

    asyncio.run(run_repl(
        permission_mode=PermissionMode(args.permission),
        working_dir=args.working_dir,
    ))


if __name__ == "__main__":
    main()
