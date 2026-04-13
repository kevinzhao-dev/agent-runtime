"""Flat file persistence for sessions, transcripts, and working memory.

Storage layout:
  .agent_sessions/
    {session_id}/
      state.json           — latest SessionState
      transcript.jsonl     — Append-only event log (full payloads since v2)
      meta.json            — {schema_version, created_at, parent_session, parent_turn}
      snapshots/
        turn_0000.json     — SessionState after user-turn 0 completed
        turn_0001.json
        ...
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from agent_runtime.engine.models import SessionState, WorkingMemory

_DEFAULT_DIR = Path(".agent_sessions")

SCHEMA_VERSION = 2


def _session_dir(session_id: str, base: Path = _DEFAULT_DIR) -> Path:
    return base / session_id


def session_dir(session_id: str, base: Path = _DEFAULT_DIR) -> Path:
    """Public accessor for the session directory — used by dev commands."""
    return _session_dir(session_id, base)


def save_session(state: SessionState, base: Path = _DEFAULT_DIR) -> Path:
    """Save session state to disk as JSON."""
    d = _session_dir(state.session_id, base)
    d.mkdir(parents=True, exist_ok=True)

    data = {
        "session_id": state.session_id,
        "messages": state.messages,
        "ledger": [asdict(e) for e in state.ledger],
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


# ── Session metadata (schema v2+) ─────────────────────────────────────────

def save_meta(
    session_id: str,
    meta: dict[str, Any],
    base: Path = _DEFAULT_DIR,
) -> Path:
    d = _session_dir(session_id, base)
    d.mkdir(parents=True, exist_ok=True)
    path = d / "meta.json"
    path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_meta(session_id: str, base: Path = _DEFAULT_DIR) -> dict[str, Any]:
    path = _session_dir(session_id, base) / "meta.json"
    if not path.is_file():
        return {"schema_version": 1}  # legacy sessions default to v1
    return json.loads(path.read_text(encoding="utf-8"))


def init_meta(
    session_id: str,
    *,
    parent_session: str | None = None,
    parent_turn: int | None = None,
    replayed_from: str | None = None,
    base: Path = _DEFAULT_DIR,
) -> dict[str, Any]:
    meta = {
        "schema_version": SCHEMA_VERSION,
        "created_at": time.time(),
        "parent_session": parent_session,
        "parent_turn": parent_turn,
        "replayed_from": replayed_from,
    }
    save_meta(session_id, meta, base)
    return meta


# ── Snapshots (per user-turn) ─────────────────────────────────────────────

def _snapshot_path(session_id: str, user_turn: int, base: Path = _DEFAULT_DIR) -> Path:
    return _session_dir(session_id, base) / "snapshots" / f"turn_{user_turn:04d}.json"


def save_snapshot(
    state: SessionState,
    user_turn: int,
    base: Path = _DEFAULT_DIR,
) -> Path:
    """Snapshot a full SessionState after user-turn N completed."""
    path = _snapshot_path(state.session_id, user_turn, base)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "user_turn": user_turn,
        "session_id": state.session_id,
        "messages": state.messages,
        "ledger": [asdict(e) if hasattr(e, "__dataclass_fields__") else e for e in state.ledger],
        "working_memory": asdict(state.working_memory),
        "compact_summary": state.compact_summary,
        "total_input_tokens": state.total_input_tokens,
        "total_output_tokens": state.total_output_tokens,
        "turn_count": state.turn_count,
    }
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_snapshot(
    session_id: str,
    user_turn: int,
    base: Path = _DEFAULT_DIR,
) -> SessionState | None:
    """Load a snapshot into a fresh SessionState. Session id is preserved."""
    path = _snapshot_path(session_id, user_turn, base)
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    state = SessionState(session_id=data["session_id"])
    state.messages = data.get("messages", [])
    state.ledger = data.get("ledger", [])
    state.compact_summary = data.get("compact_summary", "")
    state.total_input_tokens = data.get("total_input_tokens", 0)
    state.total_output_tokens = data.get("total_output_tokens", 0)
    state.turn_count = data.get("turn_count", 0)
    wm = data.get("working_memory", {})
    state.working_memory = WorkingMemory(
        task_state=wm.get("task_state", ""),
        files_touched=wm.get("files_touched", []),
        errors_and_corrections=wm.get("errors_and_corrections", []),
        key_results=wm.get("key_results", []),
        worklog=wm.get("worklog", []),
    )
    return state


def list_snapshots(session_id: str, base: Path = _DEFAULT_DIR) -> list[int]:
    """Return sorted user-turn numbers that have snapshots."""
    snap_dir = _session_dir(session_id, base) / "snapshots"
    if not snap_dir.is_dir():
        return []
    turns: list[int] = []
    for f in snap_dir.iterdir():
        if f.suffix != ".json" or not f.stem.startswith("turn_"):
            continue
        try:
            turns.append(int(f.stem.split("_", 1)[1]))
        except (ValueError, IndexError):
            continue
    return sorted(turns)


def delete_snapshots_after(
    session_id: str,
    max_user_turn: int,
    base: Path = _DEFAULT_DIR,
) -> int:
    """Delete snapshots for user_turn > max_user_turn. Returns count removed."""
    snap_dir = _session_dir(session_id, base) / "snapshots"
    if not snap_dir.is_dir():
        return 0
    removed = 0
    for turn in list_snapshots(session_id, base):
        if turn > max_user_turn:
            _snapshot_path(session_id, turn, base).unlink(missing_ok=True)
            removed += 1
    return removed


def truncate_transcript_after(
    session_id: str,
    max_user_turn: int,
    base: Path = _DEFAULT_DIR,
) -> int:
    """Drop transcript lines whose user_turn > max_user_turn. Returns lines removed.

    Lines without a `user_turn` field (e.g. legacy v1 entries) are kept untouched.
    """
    path = _session_dir(session_id, base) / "transcript.jsonl"
    if not path.is_file():
        return 0
    kept: list[str] = []
    removed = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            kept.append(line)
            continue
        ut = entry.get("user_turn")
        if isinstance(ut, int) and ut > max_user_turn:
            removed += 1
            continue
        kept.append(line)
    if kept:
        path.write_text("\n".join(kept) + "\n", encoding="utf-8")
    else:
        path.write_text("", encoding="utf-8")
    return removed


def copy_session_dir(
    src_session: str,
    dst_session: str,
    *,
    max_user_turn: int | None = None,
    base: Path = _DEFAULT_DIR,
) -> None:
    """Copy a session's files to a new session id, optionally truncated.

    Copies state.json (overwritten below by caller), transcript.jsonl, and
    snapshots. If `max_user_turn` is set, transcript lines with higher
    user_turn are dropped and only snapshots <= max_user_turn are copied.
    """
    src = _session_dir(src_session, base)
    dst = _session_dir(dst_session, base)
    dst.mkdir(parents=True, exist_ok=True)

    # transcript
    src_tx = src / "transcript.jsonl"
    if src_tx.is_file():
        if max_user_turn is None:
            (dst / "transcript.jsonl").write_text(
                src_tx.read_text(encoding="utf-8"), encoding="utf-8"
            )
        else:
            kept: list[str] = []
            for line in src_tx.read_text(encoding="utf-8").splitlines():
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    kept.append(line)
                    continue
                ut = entry.get("user_turn")
                if isinstance(ut, int) and ut > max_user_turn:
                    continue
                kept.append(line)
            (dst / "transcript.jsonl").write_text(
                ("\n".join(kept) + "\n") if kept else "", encoding="utf-8"
            )

    # snapshots
    src_snaps = src / "snapshots"
    if src_snaps.is_dir():
        (dst / "snapshots").mkdir(parents=True, exist_ok=True)
        for turn in list_snapshots(src_session, base):
            if max_user_turn is not None and turn > max_user_turn:
                continue
            src_path = _snapshot_path(src_session, turn, base)
            dst_path = _snapshot_path(dst_session, turn, base)
            dst_path.write_text(src_path.read_text(encoding="utf-8"), encoding="utf-8")
