"""Pack loader — discover, import, and scope a pack for the runtime.

A pack directory is resolved in this order:
  1. If the name is an existing directory path, use it directly.
  2. Else search under `agent_runtime/packs/<name>/`.

Packs declare their surface via module-level constants in `pack.py`:
  - NAME          : str (defaults to directory name)
  - ALLOWED_TOOLS : list[str]
  - RULES_FILES   : list[str] (relative to the pack dir, default ["AGENT.md"])

A pack.py may also perform side-effect imports to register pack-local tools
on the global stdlib registry before ALLOWED_TOOLS is consulted.
"""
from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_runtime.tools.base import ToolRegistry, registry as global_registry

PACKS_DIR = Path(__file__).parent


@dataclass
class ActivePack:
    name: str
    path: Path
    allowed_tools: list[str] = field(default_factory=list)
    rules_files: list[Path] = field(default_factory=list)
    module: Any = None


_active: ActivePack | None = None


def available_packs() -> list[str]:
    """Enumerate built-in packs under agent_runtime/packs/."""
    if not PACKS_DIR.is_dir():
        return []
    return sorted(
        p.name for p in PACKS_DIR.iterdir()
        if p.is_dir() and (p / "pack.py").is_file() and not p.name.startswith("_")
    )


def resolve_pack_path(name_or_path: str) -> Path:
    """Resolve a pack name or path to an actual directory containing pack.py."""
    p = Path(name_or_path)
    if p.is_dir() and (p / "pack.py").is_file():
        return p.resolve()
    candidate = PACKS_DIR / name_or_path
    if candidate.is_dir() and (candidate / "pack.py").is_file():
        return candidate.resolve()
    raise FileNotFoundError(
        f"Pack not found: {name_or_path!r}. Available: {available_packs()}"
    )


def load_pack(name_or_path: str) -> ActivePack:
    """Import a pack's pack.py and install it as the active pack."""
    path = resolve_pack_path(name_or_path)
    pack_py = path / "pack.py"

    spec = importlib.util.spec_from_file_location(f"_agent_pack_{path.name}", pack_py)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load pack module: {pack_py}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    name = getattr(module, "NAME", path.name)
    allowed_tools = list(getattr(module, "ALLOWED_TOOLS", []))
    rules_rel = list(getattr(module, "RULES_FILES", ["AGENT.md"]))
    rules_files = [path / r for r in rules_rel]

    pack = ActivePack(
        name=name,
        path=path,
        allowed_tools=allowed_tools,
        rules_files=rules_files,
        module=module,
    )
    set_active_pack(pack)
    return pack


def set_active_pack(pack: ActivePack | None) -> None:
    global _active
    _active = pack


def get_active_pack() -> ActivePack | None:
    return _active


def pack_registry(pack: ActivePack | None = None) -> ToolRegistry:
    """Return a tool registry scoped to a pack's ALLOWED_TOOLS.

    - No active pack → the global stdlib registry (legacy behavior).
    - Pack with allowed_tools → a fresh registry holding only those names.
    - Pack with empty allowed_tools → a genuinely empty registry (the pack
      has opted out of tools).
    Missing tool names are silently skipped.
    """
    pack = pack if pack is not None else _active
    if pack is None:
        return global_registry

    scoped = ToolRegistry()
    for name in pack.allowed_tools:
        spec = global_registry.get(name)
        if spec is not None:
            scoped.register(spec)
    return scoped
