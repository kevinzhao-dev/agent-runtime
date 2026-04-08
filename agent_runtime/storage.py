"""Flat file persistence for sessions, transcripts, and working memory.

Storage layout:
  .agent_sessions/
    {session_id}/
      state.json        — SessionState (messages, ledger, working memory)
      transcript.jsonl   — Append-only event log
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from agent_runtime.engine.models import SessionState, WorkingMemory

_DEFAULT_DIR = Path(".agent_sessions")


def _session_dir(session_id: str, base: Path = _DEFAULT_DIR) -> Path:
    return base / session_id


def save_session(state: SessionState, base: Path = _DEFAULT_DIR) -> Path:
    """Save session state to disk as JSON."""
    d = _session_dir(state.session_id, base)
    d.mkdir(parents=True, exist_ok=True)

    data = {
        "session_id": state.session_id,
        "messages": state.messages,
        "ledger": [asdict(e) for e in state.ledger],
        "loaded_topics": state.loaded_topics,
        "working_memory": asdict(state.working_memory),
        "compact_summary": state.compact_summary,
        "total_input_tokens": state.total_input_tokens,
        "total_output_tokens": state.total_output_tokens,
        "turn_count": state.turn_count,
    }

    path = d / "state.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_session(session_id: str, base: Path = _DEFAULT_DIR) -> SessionState | None:
    """Load session state from disk. Returns None if not found."""
    path = _session_dir(session_id, base) / "state.json"
    if not path.is_file():
        return None

    data = json.loads(path.read_text(encoding="utf-8"))

    state = SessionState(session_id=data["session_id"])
    state.messages = data.get("messages", [])
    state.loaded_topics = data.get("loaded_topics", [])
    state.compact_summary = data.get("compact_summary", "")
    state.total_input_tokens = data.get("total_input_tokens", 0)
    state.total_output_tokens = data.get("total_output_tokens", 0)
    state.turn_count = data.get("turn_count", 0)

    wm_data = data.get("working_memory", {})
    state.working_memory = WorkingMemory(
        task_state=wm_data.get("task_state", ""),
        files_touched=wm_data.get("files_touched", []),
        errors_and_corrections=wm_data.get("errors_and_corrections", []),
        key_results=wm_data.get("key_results", []),
        worklog=wm_data.get("worklog", []),
    )

    # Ledger entries stored as dicts — keep as dicts for simplicity
    state.ledger = data.get("ledger", [])

    return state


def append_transcript(
    session_id: str,
    event: dict[str, Any],
    base: Path = _DEFAULT_DIR,
) -> None:
    """Append an event to the transcript log (JSONL)."""
    d = _session_dir(session_id, base)
    d.mkdir(parents=True, exist_ok=True)
    path = d / "transcript.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def list_sessions(base: Path = _DEFAULT_DIR) -> list[str]:
    """List all session IDs."""
    if not base.is_dir():
        return []
    return sorted(
        d.name for d in base.iterdir()
        if d.is_dir() and (d / "state.json").is_file()
    )
