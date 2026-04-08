"""Developer tools for session analysis and prompt iteration.

Usage:
  python -m agent_runtime.dev sessions                  List all sessions
  python -m agent_runtime.dev show <session_id>         Show session details
  python -m agent_runtime.dev messages <session_id>     Show conversation messages
  python -m agent_runtime.dev ledger <session_id>       Show tool ledger
  python -m agent_runtime.dev prompt [session_id]       Show system prompt (current or from session)
  python -m agent_runtime.dev transcript <session_id>   Show raw transcript log
  python -m agent_runtime.dev compare <id1> <id2>       Compare two sessions side by side
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from agent_runtime.context import build_task_context
from agent_runtime.memory import load_memory_index, load_rules
from agent_runtime.models import SessionState, TurnConfig
from agent_runtime.prompt import build_prompt
from agent_runtime.storage import list_sessions, load_session
from agent_runtime.tools import registry

_SESSION_DIR = Path(".agent_sessions")


def _header(text: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {text}")
    print(f"{'─' * 60}")


def cmd_sessions() -> None:
    """List all saved sessions."""
    sessions = list_sessions(_SESSION_DIR)
    if not sessions:
        print("No sessions found.")
        return
    _header("Sessions")
    for sid in sessions:
        state = load_session(sid, _SESSION_DIR)
        if state:
            n_msgs = len(state.messages)
            tokens = state.total_input_tokens + state.total_output_tokens
            print(f"  {sid}  |  {state.turn_count} turns  |  {n_msgs} msgs  |  {tokens} tokens")
        else:
            print(f"  {sid}  |  (corrupted)")


def cmd_show(session_id: str) -> None:
    """Show session overview."""
    state = load_session(session_id, _SESSION_DIR)
    if not state:
        print(f"Session not found: {session_id}")
        return

    _header(f"Session: {session_id}")
    print(f"  Turns:          {state.turn_count}")
    print(f"  Messages:       {len(state.messages)}")
    print(f"  Ledger entries: {len(state.ledger)}")
    print(f"  Input tokens:   {state.total_input_tokens}")
    print(f"  Output tokens:  {state.total_output_tokens}")
    print(f"  Topics loaded:  {state.loaded_topics or '(none)'}")

    if state.working_memory.task_state:
        print(f"\n  Working Memory:")
        print(f"    Task: {state.working_memory.task_state}")
        if state.working_memory.files_touched:
            print(f"    Files: {', '.join(state.working_memory.files_touched)}")
        if state.working_memory.worklog:
            print(f"    Worklog:")
            for entry in state.working_memory.worklog[-5:]:
                print(f"      - {entry}")

    if state.compact_summary:
        print(f"\n  Compact Summary:")
        print(f"    {state.compact_summary[:200]}...")


def cmd_messages(session_id: str) -> None:
    """Show conversation messages."""
    state = load_session(session_id, _SESSION_DIR)
    if not state:
        print(f"Session not found: {session_id}")
        return

    _header(f"Messages: {session_id}")
    for i, msg in enumerate(state.messages):
        role = msg.get("role", "?")
        content = msg.get("content", "")

        if role == "user":
            print(f"\n  [{i}] USER:")
            if isinstance(content, str):
                _print_truncated(content, indent=4)
            else:
                print(f"    (structured content, {len(content)} blocks)")

        elif role == "assistant":
            print(f"\n  [{i}] ASSISTANT:")
            _print_truncated(content if isinstance(content, str) else str(content), indent=4)
            tool_calls = msg.get("tool_calls", [])
            if tool_calls:
                for tc in tool_calls:
                    print(f"    → tool_call: {tc['name']}({_short_dict(tc['input'])})")

        elif role == "tool":
            name = msg.get("name", "?")
            print(f"\n  [{i}] TOOL ({name}):")
            _print_truncated(content if isinstance(content, str) else str(content), indent=4)


def cmd_ledger(session_id: str) -> None:
    """Show tool execution ledger."""
    state = load_session(session_id, _SESSION_DIR)
    if not state:
        print(f"Session not found: {session_id}")
        return

    _header(f"Tool Ledger: {session_id}")
    if not state.ledger:
        print("  (empty)")
        return

    for i, entry in enumerate(state.ledger):
        if isinstance(entry, dict):
            name = entry.get("tool_name", "?")
            status = entry.get("status", "?")
            duration = ""
            started = entry.get("started_at", 0)
            ended = entry.get("ended_at")
            if started and ended:
                duration = f"  ({ended - started:.2f}s)"
            error = entry.get("error", "")
            summary = entry.get("summary", "")[:80]

            print(f"  [{i}] {name}: {status}{duration}")
            if summary:
                print(f"       {summary}")
            if error:
                print(f"       ERROR: {error}")


def cmd_prompt(session_id: str | None = None) -> None:
    """Show system prompt — current or extracted from a session's transcript."""
    if session_id:
        # Try to find system_prompt from transcript
        transcript_path = _SESSION_DIR / session_id / "transcript.jsonl"
        if transcript_path.is_file():
            prompts = []
            for line in transcript_path.read_text().splitlines():
                try:
                    entry = json.loads(line)
                    if entry.get("type") == "system_prompt":
                        prompts.append(entry)
                except json.JSONDecodeError:
                    continue

            if prompts:
                _header(f"System Prompt (session {session_id}, turn {prompts[-1].get('turn', '?')})")
                print(prompts[-1]["prompt"])
                if len(prompts) > 1:
                    print(f"\n  ({len(prompts)} prompt snapshots in transcript)")
                return

        print(f"No system prompt found in session {session_id} transcript.")
        print("(Prompt recording was added after this session was created.)")
        return

    # Show current prompt
    state = SessionState()
    config = TurnConfig()
    rules = load_rules("AGENT.md", "PROJECT.md")
    memory_index = load_memory_index("MEMORY.md")
    task_context = build_task_context(state, rules_content=rules, memory_index=memory_index)

    tool_descs = "\n".join(
        f"- **{s['name']}**: {s['description']}"
        for s in registry.get_schemas()
    )

    prompt_config = build_prompt(
        project_rules=rules,
        runtime_mode="",
        task_context=task_context,
        tool_descriptions=tool_descs,
    )

    _header("Current System Prompt")
    print(prompt_config.system_prompt)

    print(f"\n{'─' * 60}")
    print(f"  Layers: {len(prompt_config.layers)}")
    for layer in prompt_config.layers:
        cache = "cacheable" if layer.cacheable else "dynamic"
        print(f"    [{layer.source}] {layer.name} ({cache}, {len(layer.content)} chars)")
    print(f"  Cacheable prefix: {len(prompt_config.cacheable_prefix)} chars")


def cmd_transcript(session_id: str) -> None:
    """Show raw transcript log."""
    path = _SESSION_DIR / session_id / "transcript.jsonl"
    if not path.is_file():
        print(f"No transcript found for session: {session_id}")
        return

    _header(f"Transcript: {session_id}")
    for line in path.read_text().splitlines():
        try:
            entry = json.loads(line)
            etype = entry.get("type", "?")
            turn = entry.get("turn", "?")
            if etype == "system_prompt":
                print(f"  [turn {turn}] system_prompt ({len(entry.get('prompt', ''))} chars)")
            else:
                print(f"  [turn {turn}] {etype}")
        except json.JSONDecodeError:
            print(f"  (invalid JSON: {line[:60]}...)")


def cmd_compare(id1: str, id2: str) -> None:
    """Compare two sessions side by side."""
    s1 = load_session(id1, _SESSION_DIR)
    s2 = load_session(id2, _SESSION_DIR)

    if not s1 or not s2:
        if not s1:
            print(f"Session not found: {id1}")
        if not s2:
            print(f"Session not found: {id2}")
        return

    _header(f"Compare: {id1} vs {id2}")
    rows = [
        ("Turns", str(s1.turn_count), str(s2.turn_count)),
        ("Messages", str(len(s1.messages)), str(len(s2.messages))),
        ("Ledger entries", str(len(s1.ledger)), str(len(s2.ledger))),
        ("Input tokens", str(s1.total_input_tokens), str(s2.total_input_tokens)),
        ("Output tokens", str(s1.total_output_tokens), str(s2.total_output_tokens)),
        ("Compacted", "yes" if s1.compact_summary else "no", "yes" if s2.compact_summary else "no"),
    ]

    print(f"  {'Metric':<20} {'Session 1':>12} {'Session 2':>12}")
    print(f"  {'─' * 20} {'─' * 12} {'─' * 12}")
    for label, v1, v2 in rows:
        marker = " *" if v1 != v2 else ""
        print(f"  {label:<20} {v1:>12} {v2:>12}{marker}")


# ── Helpers ───────────────────────────────────────────────────────────────

def _print_truncated(text: str, indent: int = 0, max_lines: int = 10) -> None:
    prefix = " " * indent
    lines = text.splitlines()
    for line in lines[:max_lines]:
        print(f"{prefix}{line}")
    if len(lines) > max_lines:
        print(f"{prefix}... ({len(lines) - max_lines} more lines)")


def _short_dict(d: dict, max_len: int = 60) -> str:
    s = json.dumps(d, ensure_ascii=False)
    return s if len(s) <= max_len else s[:max_len] + "..."


# ── CLI Entry ─────────────────────────────────────────────────────────────

USAGE = """
Usage: python -m agent_runtime.dev <command> [args]

Commands:
  sessions                  List all saved sessions
  show <session_id>         Show session overview
  messages <session_id>     Show conversation messages
  ledger <session_id>       Show tool execution ledger
  prompt [session_id]       Show system prompt (current or from session)
  transcript <session_id>   Show event transcript
  compare <id1> <id2>       Compare two sessions
""".strip()


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(USAGE)
        return

    cmd = args[0]

    if cmd == "sessions":
        cmd_sessions()
    elif cmd == "show" and len(args) >= 2:
        cmd_show(args[1])
    elif cmd == "messages" and len(args) >= 2:
        cmd_messages(args[1])
    elif cmd == "ledger" and len(args) >= 2:
        cmd_ledger(args[1])
    elif cmd == "prompt":
        cmd_prompt(args[1] if len(args) >= 2 else None)
    elif cmd == "transcript" and len(args) >= 2:
        cmd_transcript(args[1])
    elif cmd == "compare" and len(args) >= 3:
        cmd_compare(args[1], args[2])
    else:
        print(USAGE)


if __name__ == "__main__":
    main()
