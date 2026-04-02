"""Bash tool — execute shell commands."""

from __future__ import annotations

import asyncio
from typing import Any

from tools.base import BaseTool, ToolContext, ToolResult

DEFAULT_TIMEOUT = 120  # seconds


class BashTool(BaseTool):
    @property
    def name(self) -> str:
        return "bash"

    @property
    def description(self) -> str:
        return "Execute a shell command and return its output (stdout + stderr)."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default: 120)",
                    "default": DEFAULT_TIMEOUT,
                },
            },
            "required": ["command"],
        }

    def is_read_only(self) -> bool:
        return False

    async def execute(self, *, input: dict[str, Any], context: ToolContext) -> ToolResult:
        command = input["command"]
        timeout = input.get("timeout", DEFAULT_TIMEOUT)

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=context.working_dir,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            return ToolResult(
                content=f"Command timed out after {timeout}s: {command}",
                is_error=True,
            )
        except OSError as e:
            return ToolResult(content=f"Execution error: {e}", is_error=True)

        output_parts: list[str] = []
        if stdout:
            output_parts.append(stdout.decode("utf-8", errors="replace"))
        if stderr:
            output_parts.append(stderr.decode("utf-8", errors="replace"))

        output = "\n".join(output_parts).strip()

        if proc.returncode != 0:
            return ToolResult(
                content=f"Exit code {proc.returncode}\n{output}" if output else f"Exit code {proc.returncode}",
                is_error=True,
            )

        return ToolResult(content=output if output else "(no output)")
