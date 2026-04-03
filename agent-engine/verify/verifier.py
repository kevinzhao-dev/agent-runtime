"""Verification strategies — independent checking of implementation results.

Provides a pluggable VerificationStrategy protocol with two built-in
implementations: PytestStrategy and LLMReviewStrategy.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class Verdict(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    PARTIAL = "partial"


@dataclass(frozen=True)
class VerifyResult:
    verdict: Verdict
    reason: str
    details: dict[str, Any] | None = None


@dataclass(frozen=True)
class VerifyContext:
    task_description: str
    working_dir: str
    implementation_summary: str = ""
    files_changed: list[str] = field(default_factory=list)


@runtime_checkable
class VerificationStrategy(Protocol):
    async def verify(self, context: VerifyContext) -> VerifyResult: ...


class PytestStrategy:
    """Run pytest and parse the results."""

    def __init__(self, test_command: str = "python -m pytest -v"):
        self.test_command = test_command

    async def verify(self, context: VerifyContext) -> VerifyResult:
        try:
            proc = await asyncio.create_subprocess_shell(
                self.test_command,
                cwd=context.working_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        except asyncio.TimeoutError:
            return VerifyResult(
                verdict=Verdict.FAIL,
                reason="Tests timed out after 120s",
            )
        except OSError as e:
            return VerifyResult(
                verdict=Verdict.FAIL,
                reason=f"Could not run tests: {e}",
            )

        output = stdout.decode("utf-8", errors="replace")
        err_output = stderr.decode("utf-8", errors="replace")

        if proc.returncode == 0:
            return VerifyResult(
                verdict=Verdict.PASS,
                reason="All tests passed",
                details={"output": output, "exit_code": 0},
            )
        else:
            return VerifyResult(
                verdict=Verdict.FAIL,
                reason=f"Tests failed (exit code {proc.returncode})",
                details={
                    "output": output,
                    "stderr": err_output,
                    "exit_code": proc.returncode,
                },
            )


class LLMReviewStrategy:
    """Spawn a verifier agent to do code review."""

    def __init__(self, model: str = "claude-sonnet-4-6"):
        self.model = model

    async def verify(self, context: VerifyContext) -> VerifyResult:
        from context.prompt import build_system_prompt
        from engine.loop import ToolResult as LoopToolResult
        from engine.loop import query_loop
        from engine.state import TextEvent
        from roles.config import VERIFIER_ROLE
        from tools.base import ToolContext
        from tools.permission import PermissionGate, PermissionMode
        from tools.registry import create_default_registry

        review_prompt = self._build_review_prompt(context)

        registry = create_default_registry()
        tool_schemas = registry.get_api_schemas(VERIFIER_ROLE)

        # Verifier uses strict-read-only: yolo for read-only tools only
        gate = PermissionGate(mode=PermissionMode.YOLO)
        tool_ctx = ToolContext(
            working_dir=context.working_dir,
            permission_gate=gate,
        )

        async def executor(
            name: str, tid: str, inp: dict[str, Any]
        ) -> LoopToolResult:
            tool = registry.get(name)
            if tool is None:
                return LoopToolResult(content=f"Unknown tool: {name}", is_error=True)
            result = await tool.execute(input=inp, context=tool_ctx)
            return LoopToolResult(content=result.content, is_error=result.is_error)

        collected: list[str] = []
        async for event in query_loop(
            messages=[{"role": "user", "content": review_prompt}],
            role_config=VERIFIER_ROLE,
            tools=tool_schemas,
            tool_executor=executor,
            max_turns=VERIFIER_ROLE.max_turns,
        ):
            if isinstance(event, TextEvent):
                collected.append(event.text)

        review_text = "".join(collected)
        return self._parse_review(review_text)

    def _build_review_prompt(self, context: VerifyContext) -> str:
        parts = [
            f"Review this implementation. The original task was:\n{context.task_description}",
        ]
        if context.implementation_summary:
            parts.append(f"The implementer reports:\n{context.implementation_summary}")
        if context.files_changed:
            parts.append(f"Files changed: {', '.join(context.files_changed)}")
        parts.append(
            "Read the relevant files and assess correctness. "
            "Respond with VERDICT: PASS, FAIL, or PARTIAL followed by your reasoning."
        )
        return "\n\n".join(parts)

    def _parse_review(self, review_text: str) -> VerifyResult:
        text_upper = review_text.upper()
        if "VERDICT: PASS" in text_upper or "VERDICT:PASS" in text_upper:
            verdict = Verdict.PASS
        elif "VERDICT: FAIL" in text_upper or "VERDICT:FAIL" in text_upper:
            verdict = Verdict.FAIL
        elif "VERDICT: PARTIAL" in text_upper or "VERDICT:PARTIAL" in text_upper:
            verdict = Verdict.PARTIAL
        else:
            # Heuristic fallback
            if "ALL CORRECT" in text_upper or "LOOKS GOOD" in text_upper:
                verdict = Verdict.PASS
            elif "BUG" in text_upper or "ERROR" in text_upper or "FAIL" in text_upper:
                verdict = Verdict.FAIL
            else:
                verdict = Verdict.PARTIAL

        return VerifyResult(
            verdict=verdict,
            reason=review_text[:500],
            details={"full_review": review_text},
        )
