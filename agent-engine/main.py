"""CLI entry point for agent-engine."""

import argparse
import asyncio

from entrypoints.cli import run_repl
from roles.config import ROLE_REGISTRY
from tools.permission import PermissionMode


def main():
    parser = argparse.ArgumentParser(description="Agent Engine")
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
    args = parser.parse_args()

    asyncio.run(run_repl(
        role_config=ROLE_REGISTRY[args.role],
        permission_mode=PermissionMode(args.permission),
        working_dir=args.working_dir,
    ))


if __name__ == "__main__":
    main()
