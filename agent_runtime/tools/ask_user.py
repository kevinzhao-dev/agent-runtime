"""ask_user tool — request input from the user.

Yields a suspend event. The caller is responsible for resuming
with the user's response.
"""
from __future__ import annotations

from agent_runtime.tools.base import ToolSpec, registry


class UserInputRequired(Exception):
    """Raised to signal the loop should suspend and wait for user input."""

    def __init__(self, question: str) -> None:
        self.question = question
        super().__init__(question)


def _ask_user(params: dict) -> str:
    question = params["question"]
    raise UserInputRequired(question)


registry.register(ToolSpec(
    name="ask_user",
    description="Ask the user a question and wait for their response.",
    input_schema={
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "Question to ask the user"},
        },
        "required": ["question"],
    },
    executor=_ask_user,
    risk="low",
))
