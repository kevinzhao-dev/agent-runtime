"""Prompt assembly + inspection helpers shared by the REPL and commands.

One place that knows how to turn live state + config into a PromptConfig.
Both `app.py` (to send to the model) and `commands.py` (to inspect) call it.
"""
from __future__ import annotations

from agent_runtime.engine.models import SessionState, TurnConfig
from agent_runtime.packs import get_active_pack, pack_registry
from agent_runtime.prompt import (
    PromptConfig,
    build_prompt,
    build_task_context,
    load_memory_index,
    load_rules,
)
from agent_runtime.tools import registry as global_registry


def build_current_prompt(state: SessionState, config: TurnConfig) -> PromptConfig:
    """Assemble the PromptConfig for the *current* session state.

    When a pack is active, its `AGENT.md` + `MEMORY.md` and its scoped
    tool registry drive the prompt. Otherwise we fall back to CWD-relative
    files and the full global registry (legacy behavior).
    """
    pack = get_active_pack()
    if pack is not None:
        rules = load_rules(*pack.rules_files)
        memory_index = load_memory_index(pack.path / "MEMORY.md")
        reg = pack_registry(pack)
    else:
        rules = load_rules("AGENT.md", "PROJECT.md")
        memory_index = load_memory_index("MEMORY.md")
        reg = global_registry

    task_context = build_task_context(
        state, rules_content=rules, memory_index=memory_index
    )

    tool_descs = "\n".join(
        f"- **{s['name']}**: {s['description']}"
        for s in reg.get_schemas()
    )

    return build_prompt(
        project_rules=rules,
        runtime_mode="",
        task_context=task_context,
        tool_descriptions=tool_descs,
    )


def estimate_tokens_str(s: str) -> int:
    """Same char/3.5 heuristic used by engine.loop.estimate_tokens."""
    return int(len(s) / 3.5)


def layer_stats(pc: PromptConfig) -> list[dict]:
    """Per-layer breakdown suitable for printing or stashing in a transcript."""
    return [
        {
            "name": layer.name,
            "source": layer.source,
            "cacheable": layer.cacheable,
            "chars": len(layer.content),
            "tokens": estimate_tokens_str(layer.content),
        }
        for layer in pc.layers
    ]
