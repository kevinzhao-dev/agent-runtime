"""4-layer prompt builder — the control plane.

Not a freeform string. A layered, precedence-aware, cache-conscious
structure that composes base rules, project rules, runtime mode, and task context.

Each layer carries a source label and cacheability flag.
Builder enforces ordering: base > project > mode > task.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class PromptLayer:
    """A single prompt layer with metadata."""
    name: str
    content: str
    source: str  # e.g. "base", "AGENT.md", "runtime", "task"
    cacheable: bool = True


@dataclass(slots=True)
class PromptConfig:
    """Assembled prompt with layer tracking."""
    layers: list[PromptLayer] = field(default_factory=list)

    @property
    def system_prompt(self) -> str:
        """Concatenate all layers into the final system prompt."""
        parts: list[str] = []
        for layer in self.layers:
            if layer.content.strip():
                parts.append(f"<!-- [{layer.source}] {layer.name} -->\n{layer.content}")
        return "\n\n".join(parts)

    @property
    def cacheable_prefix(self) -> str:
        """Return the cacheable portion (for prompt caching)."""
        parts: list[str] = []
        for layer in self.layers:
            if layer.cacheable and layer.content.strip():
                parts.append(layer.content)
        return "\n\n".join(parts)

    def get_layer(self, name: str) -> PromptLayer | None:
        for layer in self.layers:
            if layer.name == name:
                return layer
        return None


# ── Base System Prompt ────────────────────────────────────────────────────

_BASE_SYSTEM_PROMPT = """\
You are an AI agent operating within a runtime kernel.
You have access to tools for reading files, writing files, searching, and executing commands.

## Behavioral Rules
- Read code before modifying it.
- Do not add features the user did not request.
- Report results honestly. If something failed, say so.
- Prefer using specific tools (read_file, grep_search) over bash for their domains.
- bash is high-risk. Use it only for operations that require shell execution.
"""


def build_prompt(
    *,
    project_rules: str = "",
    runtime_mode: str = "",
    task_context: str = "",
    tool_descriptions: str = "",
    base_prompt: str = _BASE_SYSTEM_PROMPT,
) -> PromptConfig:
    """Build a 4-layer prompt configuration.

    Args:
        project_rules: Content from AGENT.md / PROJECT.md.
        runtime_mode: Mode-specific instructions (e.g. "plan mode").
        task_context: Current task state, recent tool outcomes.
        tool_descriptions: Formatted tool descriptions.
        base_prompt: Override for the base system prompt.
    """
    config = PromptConfig()

    # Layer 1: Base system prompt (cacheable)
    full_base = base_prompt
    if tool_descriptions:
        full_base += f"\n\n## Available Tools\n{tool_descriptions}"
    config.layers.append(PromptLayer(
        name="base",
        content=full_base,
        source="base",
        cacheable=True,
    ))

    # Layer 2: Project rules (cacheable)
    if project_rules:
        config.layers.append(PromptLayer(
            name="project_rules",
            content=project_rules,
            source="project",
            cacheable=True,
        ))

    # Layer 3: Runtime mode (dynamic, not cacheable)
    if runtime_mode:
        config.layers.append(PromptLayer(
            name="runtime_mode",
            content=runtime_mode,
            source="runtime",
            cacheable=False,
        ))

    # Layer 4: Task context (dynamic, not cacheable)
    if task_context:
        config.layers.append(PromptLayer(
            name="task_context",
            content=task_context,
            source="task",
            cacheable=False,
        ))

    return config
