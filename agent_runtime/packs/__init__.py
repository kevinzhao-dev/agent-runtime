"""Agent pack system.

A pack is a directory on disk defining an agent's identity:
  - `pack.py`     Python manifest (NAME, ALLOWED_TOOLS, RULES_FILES, optional register())
  - `AGENT.md`    Pack-specific prompt rules
  - (optional) `MEMORY.md`, topic files, pack-local tool modules

The core runtime stays agent-agnostic; packs pick which stdlib tools to
expose and can register their own. Forking an agent = copy a pack dir.
"""
from agent_runtime.packs.loader import (
    ActivePack,
    available_packs,
    get_active_pack,
    load_pack,
    pack_registry,
    set_active_pack,
)

__all__ = [
    "ActivePack",
    "available_packs",
    "get_active_pack",
    "load_pack",
    "pack_registry",
    "set_active_pack",
]
