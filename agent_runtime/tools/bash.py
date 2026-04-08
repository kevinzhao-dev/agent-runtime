"""bash tool — execute shell commands. High risk, requires approval."""
from __future__ import annotations

import subprocess

from agent_runtime.tools.base import ToolSpec, registry

_DEFAULT_TIMEOUT = 30


def _bash(params: dict) -> str:
    command = params["command"]
    timeout = params.get("timeout", _DEFAULT_TIMEOUT)

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = result.stdout
        if result.stderr:
            output += f"\n[stderr]\n{result.stderr}"
        if result.returncode != 0:
            output += f"\n[exit code: {result.returncode}]"
        return output or "(no output)"
    except subprocess.TimeoutExpired:
        return f"Error: Command timed out after {timeout}s"
    except Exception as e:
        return f"Error: {e}"


registry.register(ToolSpec(
    name="bash",
    description="Execute a shell command. Use for system operations.",
    input_schema={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to execute"},
            "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 30},
        },
        "required": ["command"],
    },
    executor=_bash,
    risk="high",
    side_effecting=True,
))
