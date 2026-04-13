"""Slash-command dispatcher for the REPL.

Inputs starting with '/' route here. Each command is a small function
that prints to stdout. Commands share a ReplContext carrying the live
SessionState so they can inspect the current session without a session_id.

For commands that read from disk (sessions listed, transcript, etc.) we
delegate to the existing functions in `cli.dev` — keeping a single source
of truth for formatting.
"""
from __future__ import annotations

import difflib
import json
import subprocess
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable

from agent_runtime.cli import dev
from agent_runtime.cli.prompt_view import (
    build_current_prompt,
    estimate_tokens_str,
    layer_stats,
)
from agent_runtime.engine.loop import estimate_tokens
from agent_runtime.engine.models import SessionState, TurnConfig
from agent_runtime.storage import (
    copy_session_dir,
    delete_snapshots_after,
    init_meta,
    list_sessions,
    list_snapshots,
    load_meta,
    load_session,
    load_snapshot,
    save_meta,
    save_session,
    save_snapshot,
    truncate_transcript_after,
)

_SESSION_DIR = Path(".agent_sessions")


@dataclass
class ReplContext:
    state: SessionState
    config: TurnConfig
    user_turn: int = 0
    pending_inputs: list[str] = field(default_factory=list)
    step_mode: bool = False
    break_tools: set[str] = field(default_factory=set)
    break_turns: set[int] = field(default_factory=set)


Handler = Callable[[list[str], ReplContext], None]


@dataclass
class Command:
    name: str
    help: str
    handler: Handler


COMMANDS: dict[str, Command] = {}


def register(name: str, help: str) -> Callable[[Handler], Handler]:
    def _wrap(fn: Handler) -> Handler:
        COMMANDS[name] = Command(name=name, help=help, handler=fn)
        return fn
    return _wrap


def _resolve_sid(args: list[str], ctx: ReplContext) -> str | None:
    """Resolve a session id argument. '.' or no-arg means current session.

    Current session is flushed to disk first so the dev readers see fresh data.
    """
    if not args or args[0] == ".":
        save_session(ctx.state)
        return ctx.state.session_id
    return args[0]


# ── Commands ──────────────────────────────────────────────────────────────

@register("help", "List all slash commands")
def _help(args: list[str], ctx: ReplContext) -> None:
    print("\nSlash commands:")
    for name in sorted(COMMANDS):
        c = COMMANDS[name]
        print(f"  /{name:<12} {c.help}")
    print("\nOther:")
    print("  !<cmd>         Run a shell command")
    print("  quit / exit    Leave the REPL\n")


@register("sessions", "List saved sessions")
def _sessions(args: list[str], ctx: ReplContext) -> None:
    dev.cmd_sessions()


@register("show", "Show session overview [session_id|.]")
def _show(args: list[str], ctx: ReplContext) -> None:
    sid = _resolve_sid(args, ctx)
    if sid:
        dev.cmd_show(sid)


@register("messages", "Show session messages [session_id|.]")
def _messages(args: list[str], ctx: ReplContext) -> None:
    sid = _resolve_sid(args, ctx)
    if sid:
        dev.cmd_messages(sid)


@register("ledger", "Show tool execution ledger [session_id|.]")
def _ledger(args: list[str], ctx: ReplContext) -> None:
    sid = _resolve_sid(args, ctx)
    if sid:
        dev.cmd_ledger(sid)


@register("transcript", "Show raw transcript log [session_id|.]")
def _transcript(args: list[str], ctx: ReplContext) -> None:
    sid = _resolve_sid(args, ctx)
    if sid:
        dev.cmd_transcript(sid)


# ── Prompt inspectors ─────────────────────────────────────────────────────

def _header(text: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {text}")
    print(f"{'─' * 60}")


@register("prompt", "Show system prompt | 'layers' | 'diff <a> <b>'")
def _prompt(args: list[str], ctx: ReplContext) -> None:
    if not args:
        pc = build_current_prompt(ctx.state, ctx.config)
        _header("Current system prompt")
        print(pc.system_prompt)
        return

    sub = args[0]
    if sub == "layers":
        _prompt_layers(ctx)
    elif sub == "diff" and len(args) >= 3:
        try:
            a, b = int(args[1]), int(args[2])
        except ValueError:
            print("Usage: /prompt diff <turn_a> <turn_b>")
            return
        _prompt_diff(ctx, a, b)
    else:
        print("Usage: /prompt | /prompt layers | /prompt diff <turn_a> <turn_b>")


def _prompt_layers(ctx: ReplContext) -> None:
    pc = build_current_prompt(ctx.state, ctx.config)
    stats = layer_stats(pc)

    _header("Prompt layers")
    print(f"  {'name':<16} {'source':<10} {'cache':<6} {'chars':>8} {'tokens':>8}")
    print(f"  {'-'*16} {'-'*10} {'-'*6} {'-'*8} {'-'*8}")
    total_chars = total_tokens = 0
    for s in stats:
        cache = "yes" if s["cacheable"] else "no"
        print(f"  {s['name']:<16} {s['source']:<10} {cache:<6} {s['chars']:>8} {s['tokens']:>8}")
        total_chars += s["chars"]
        total_tokens += s["tokens"]
    print(f"  {'-'*16} {'-'*10} {'-'*6} {'-'*8} {'-'*8}")
    print(f"  {'TOTAL':<16} {'':<10} {'':<6} {total_chars:>8} {total_tokens:>8}")


def _prompt_diff(ctx: ReplContext, turn_a: int, turn_b: int) -> None:
    path = _SESSION_DIR / ctx.state.session_id / "transcript.jsonl"
    if not path.is_file():
        print("No transcript for current session.")
        return

    prompts: dict[int, str] = {}
    for line in path.read_text().splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") == "system_prompt":
            prompts[entry.get("turn", -1)] = entry.get("prompt", "")

    missing = [t for t in (turn_a, turn_b) if t not in prompts]
    if missing:
        print(f"No system_prompt recorded for turn(s): {missing}")
        print(f"Available turns: {sorted(prompts)}")
        return

    a = prompts[turn_a].splitlines()
    b = prompts[turn_b].splitlines()
    _header(f"Prompt diff: turn {turn_a} → turn {turn_b}")
    any_line = False
    for line in difflib.unified_diff(
        a, b, lineterm="", fromfile=f"turn{turn_a}", tofile=f"turn{turn_b}"
    ):
        print(line)
        any_line = True
    if not any_line:
        print("  (identical)")


def _split_history(state: SessionState) -> tuple[list[dict], list[dict]]:
    """Split messages into (user+assistant history, tool-result messages)."""
    hist = [m for m in state.messages if m.get("role") in ("user", "assistant")]
    tools = [m for m in state.messages if m.get("role") == "tool"]
    return hist, tools


@register("tokens", "Context window token breakdown")
def _tokens(args: list[str], ctx: ReplContext) -> None:
    pc = build_current_prompt(ctx.state, ctx.config)
    stats = layer_stats(pc)
    hist, tools = _split_history(ctx.state)
    history_tokens = estimate_tokens(hist)
    tool_tokens = estimate_tokens(tools)
    system_total = sum(s["tokens"] for s in stats)
    total = system_total + history_tokens + tool_tokens
    threshold = ctx.config.compact_threshold_tokens

    _header("Context window tokens")
    for s in stats:
        label = f"{s['source']}/{s['name']}"
        print(f"  {label:<28} {s['tokens']:>8}")
    print(f"  {'history (user+assistant)':<28} {history_tokens:>8}")
    print(f"  {'tool results':<28} {tool_tokens:>8}")
    print(f"  {'-'*28} {'-'*8}")
    print(f"  {'TOTAL':<28} {total:>8}")
    pct = (total / threshold * 100) if threshold else 0
    print(f"  {'compact threshold':<28} {threshold:>8}  ({pct:.0f}% used)")


@register("context", "One-line context size summary")
def _context(args: list[str], ctx: ReplContext) -> None:
    pc = build_current_prompt(ctx.state, ctx.config)
    sys_tokens = sum(s["tokens"] for s in layer_stats(pc))
    hist, tools = _split_history(ctx.state)
    hist_tokens = estimate_tokens(hist)
    tool_tokens = estimate_tokens(tools)
    total = sys_tokens + hist_tokens + tool_tokens
    threshold = ctx.config.compact_threshold_tokens
    print(
        f"[ctx {total}/{threshold} · sys {sys_tokens} · hist {hist_tokens} · tools {tool_tokens}]"
    )


# ── Fork / rewind / replay ────────────────────────────────────────────────

def _new_session_id() -> str:
    return uuid.uuid4().hex[:12]


def _switch_ctx_to_session(
    ctx: ReplContext, new_state: SessionState, user_turn: int
) -> None:
    """In-place swap of the live session the REPL is working on."""
    ctx.state.replace_from(new_state)
    ctx.user_turn = user_turn


@register("fork", "Fork current session [@N  fork from user-turn N]")
def _fork(args: list[str], ctx: ReplContext) -> None:
    # Parse optional `@N` turn argument.
    fork_turn: int | None = None
    if args:
        tok = args[0]
        if tok.startswith("@"):
            try:
                fork_turn = int(tok[1:])
            except ValueError:
                print("Usage: /fork | /fork @<user_turn>")
                return
        else:
            print("Usage: /fork | /fork @<user_turn>")
            return

    # Flush current session so snapshots/transcript on disk are fresh.
    save_session(ctx.state)
    parent_sid = ctx.state.session_id

    # Determine source state to branch from.
    if fork_turn is None:
        if ctx.user_turn == 0:
            print("Nothing to fork — session has no completed turns yet.")
            return
        source_state = ctx.state
        source_turn = ctx.user_turn - 1
    else:
        loaded = load_snapshot(parent_sid, fork_turn)
        if loaded is None:
            available = list_snapshots(parent_sid)
            print(f"No snapshot at user_turn={fork_turn}. Available: {available}")
            return
        source_state = loaded
        source_turn = fork_turn

    # Create new session on disk.
    new_sid = _new_session_id()
    copy_session_dir(parent_sid, new_sid, max_user_turn=source_turn)

    # Fresh state for the new session (copied from source, new id).
    new_state = SessionState(session_id=new_sid)
    new_state.messages = list(source_state.messages)
    new_state.ledger = list(source_state.ledger)
    new_state.working_memory = source_state.working_memory
    new_state.compact_summary = source_state.compact_summary
    new_state.total_input_tokens = source_state.total_input_tokens
    new_state.total_output_tokens = source_state.total_output_tokens
    new_state.turn_count = source_state.turn_count

    save_session(new_state)
    # Re-snapshot the tip under the new session's id so replace_from is consistent.
    save_snapshot(new_state, source_turn)
    init_meta(
        new_sid,
        parent_session=parent_sid,
        parent_turn=source_turn,
    )

    _switch_ctx_to_session(ctx, new_state, user_turn=source_turn + 1)
    print(f"Forked: {parent_sid} @{source_turn} → {new_sid}")
    print(f"REPL now on session {new_sid} (user_turn {ctx.user_turn}).")


@register("rewind", "Drop last N user-turns in current session")
def _rewind(args: list[str], ctx: ReplContext) -> None:
    if not args:
        print("Usage: /rewind <N>")
        return
    try:
        n = int(args[0])
    except ValueError:
        print("Usage: /rewind <N>")
        return
    if n <= 0:
        print("N must be positive.")
        return

    target_turn = ctx.user_turn - n - 1  # user_turn points to next; snapshots are 0-indexed
    if target_turn < 0:
        print(f"Cannot rewind past start (current user_turn={ctx.user_turn}).")
        return

    sid = ctx.state.session_id
    snap = load_snapshot(sid, target_turn)
    if snap is None:
        print(f"No snapshot at user_turn={target_turn}. Available: {list_snapshots(sid)}")
        return

    confirm = input(f"Rewind to user_turn {target_turn} (drop {n} turn(s))? (y/n): ").strip().lower()
    if confirm not in ("y", "yes"):
        print("Aborted.")
        return

    delete_snapshots_after(sid, target_turn)
    truncate_transcript_after(sid, target_turn)
    _switch_ctx_to_session(ctx, snap, user_turn=target_turn + 1)
    save_session(ctx.state)
    print(f"Rewound to user_turn {target_turn}. Next turn will be {ctx.user_turn}.")


def _extract_user_inputs(session_id: str) -> list[str]:
    """Pull user inputs from a session's transcript (v2) or fall back to messages.

    Falls back to role=user messages in state.json for legacy v1 sessions.
    """
    path = _SESSION_DIR / session_id / "transcript.jsonl"
    inputs: list[str] = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("type") == "user_input":
                inputs.append(entry.get("text", ""))
    if inputs:
        return inputs

    # Fallback: v1 sessions — no user_input events; read state.
    state = load_session(session_id)
    if state is None:
        return []
    for m in state.messages:
        if m.get("role") == "user":
            content = m.get("content", "")
            if isinstance(content, str):
                inputs.append(content)
    return inputs


@register("replay", "Replay a session's user inputs: <sid> [--model X]")
def _replay(args: list[str], ctx: ReplContext) -> None:
    if not args:
        print("Usage: /replay <session_id> [--model NAME]")
        return
    sid = args[0]
    model_override: str | None = None
    i = 1
    while i < len(args):
        if args[i] == "--model" and i + 1 < len(args):
            model_override = args[i + 1]
            i += 2
        else:
            print(f"Unknown option: {args[i]}")
            return

    inputs = _extract_user_inputs(sid)
    if not inputs:
        print(f"No user inputs found in session {sid}.")
        return

    # Start a fresh session with lineage pointing at the source.
    new_sid = _new_session_id()
    new_state = SessionState(session_id=new_sid)
    save_session(new_state)
    init_meta(new_sid, replayed_from=sid)

    if model_override:
        ctx.config = replace(ctx.config, model_name=model_override)

    _switch_ctx_to_session(ctx, new_state, user_turn=0)
    ctx.pending_inputs.extend(inputs)
    print(
        f"Replaying {len(inputs)} input(s) from {sid} into new session {new_sid}"
        + (f" (model={model_override})" if model_override else "")
    )


@register("pack", "Show/list/switch active pack")
def _pack(args: list[str], ctx: ReplContext) -> None:
    from agent_runtime.packs import (
        available_packs,
        get_active_pack,
        load_pack,
    )

    if not args:
        active = get_active_pack()
        print()
        if active is None:
            print("  active pack: (none)")
        else:
            print(f"  active pack: {active.name}")
            print(f"  path:        {active.path}")
            print(f"  rules:       {[str(p.name) for p in active.rules_files]}")
            print(f"  tools:       {active.allowed_tools}")
        print(f"  available:   {available_packs()}")
        print("\n  Usage: /pack                    show current")
        print("         /pack switch <name>     swap to another pack\n")
        return

    sub = args[0]
    if sub == "switch" and len(args) >= 2:
        try:
            pack = load_pack(args[1])
        except (FileNotFoundError, ImportError) as e:
            print(f"[/pack] {e}")
            return
        print(f"Switched to pack: {pack.name}  (tools={pack.allowed_tools})")
    else:
        print("Usage: /pack | /pack switch <name>")


@register("tree", "Show session fork tree")
def _tree(args: list[str], ctx: ReplContext) -> None:
    sessions = list_sessions(_SESSION_DIR)
    if not sessions:
        print("No sessions found.")
        return

    # Build parent -> [child] adjacency from meta files.
    children: dict[str | None, list[str]] = {}
    parents: dict[str, tuple[str | None, int | None, str | None]] = {}
    for sid in sessions:
        meta = load_meta(sid)
        parent = meta.get("parent_session")
        parent_turn = meta.get("parent_turn")
        replayed = meta.get("replayed_from")
        parents[sid] = (parent, parent_turn, replayed)
        children.setdefault(parent, []).append(sid)

    def _render(sid: str, indent: str, is_last: bool) -> None:
        marker = "└─ " if is_last else "├─ "
        _, parent_turn, replayed = parents[sid]
        tag = ""
        if parent_turn is not None:
            tag = f"  (forked @{parent_turn})"
        elif replayed:
            tag = f"  (replayed from {replayed[:8]})"
        state = load_session(sid)
        meta_str = ""
        if state:
            meta_str = f"  turns={state.turn_count}"
        print(f"{indent}{marker}{sid}{tag}{meta_str}")
        kids = sorted(children.get(sid, []))
        next_indent = indent + ("   " if is_last else "│  ")
        for i, kid in enumerate(kids):
            _render(kid, next_indent, i == len(kids) - 1)

    _header("Session tree")
    roots = sorted(children.get(None, []))
    for i, root in enumerate(roots):
        _render(root, "", i == len(roots) - 1)


# ── Debug / hot-reload ────────────────────────────────────────────────────

@register("step", "Toggle step mode (pause on every tool call): on|off")
def _step(args: list[str], ctx: ReplContext) -> None:
    if not args:
        print(f"step mode: {'on' if ctx.step_mode else 'off'}")
        return
    if args[0] == "on":
        ctx.step_mode = True
        print("Step mode: on — pauses before every tool call.")
    elif args[0] == "off":
        ctx.step_mode = False
        print("Step mode: off.")
    else:
        print("Usage: /step [on|off]")


@register("break", "Set/list/clear breakpoints: tool:<name> | turn:<n> | list | clear")
def _break(args: list[str], ctx: ReplContext) -> None:
    if not args or args[0] == "list":
        print(f"  tool breakpoints: {sorted(ctx.break_tools) or '(none)'}")
        print(f"  turn breakpoints: {sorted(ctx.break_turns) or '(none)'}")
        return
    if args[0] == "clear":
        ctx.break_tools.clear()
        ctx.break_turns.clear()
        print("Breakpoints cleared.")
        return
    for arg in args:
        if arg.startswith("tool:"):
            name = arg[5:]
            if not name:
                print("Usage: /break tool:<name>")
                return
            ctx.break_tools.add(name)
        elif arg.startswith("turn:"):
            try:
                ctx.break_turns.add(int(arg[5:]))
            except ValueError:
                print(f"Invalid turn number: {arg}")
                return
        else:
            print("Usage: /break tool:<name> | turn:<n> | list | clear")
            return
    print(f"OK. tools={sorted(ctx.break_tools)} turns={sorted(ctx.break_turns)}")


@register("dry-run", "Print what would be sent to the model for a given input")
def _dry_run(args: list[str], ctx: ReplContext) -> None:
    from agent_runtime.packs import pack_registry as _pack_registry

    message = " ".join(args) if args else "(empty input)"
    pc = build_current_prompt(ctx.state, ctx.config)
    reg = _pack_registry()

    _header("Dry run — would send to model")
    print(f"  model:         {ctx.config.model_name}")
    print(f"  user_turn:     {ctx.user_turn}")
    print(f"  user input:    {message!r}")
    print(f"  tools visible: {sorted(reg.list_names()) or '(none)'}")
    print(f"  prompt chars:  {sum(len(l.content) for l in pc.layers)}")
    print()
    print("  system prompt:")
    for line in pc.system_prompt.splitlines():
        print(f"    {line}")


@register("edit", "Edit pack files in $EDITOR: /edit prompt")
def _edit(args: list[str], ctx: ReplContext) -> None:
    import os
    from agent_runtime.packs import get_active_pack

    if not args or args[0] != "prompt":
        print("Usage: /edit prompt")
        return
    pack = get_active_pack()
    if pack is None:
        print("No active pack.")
        return

    target = pack.path / "AGENT.md"
    editor = os.environ.get("EDITOR", "vi")
    try:
        subprocess.run([editor, str(target)])
    except FileNotFoundError:
        print(f"[edit] $EDITOR not found: {editor!r}")
        return
    print(f"Edited {target}. Next turn will re-read AGENT.md from disk.")


@register("reload", "Reload pack tools: /reload tools")
def _reload(args: list[str], ctx: ReplContext) -> None:
    import importlib
    import sys
    from agent_runtime.packs import get_active_pack, load_pack

    if not args or args[0] != "tools":
        print("Usage: /reload tools")
        return
    pack = get_active_pack()
    if pack is None:
        print("No active pack.")
        return

    # Reload any already-imported agent_runtime.tools.* modules so source edits
    # to tool implementations are picked up. Skip base (which owns the global
    # registry dict) to avoid wiping registrations mid-flight.
    reloaded: list[str] = []
    for mod_name in list(sys.modules):
        if mod_name.startswith("agent_runtime.tools.") and mod_name != "agent_runtime.tools.base":
            try:
                importlib.reload(sys.modules[mod_name])
                reloaded.append(mod_name.split(".")[-1])
            except Exception as e:
                print(f"  [reload] {mod_name} failed: {e}")

    # Re-run the pack's manifest so any pack-local tool imports re-execute
    # and ALLOWED_TOOLS is re-read.
    load_pack(pack.name)
    print(f"Reloaded {len(reloaded)} tool module(s): {reloaded}")
    print(f"Pack re-loaded: {pack.name}")


# ── Dispatcher ────────────────────────────────────────────────────────────

def dispatch(body: str, ctx: ReplContext) -> None:
    """Run a slash command. `body` is the line with the leading '/' removed."""
    parts = body.strip().split()
    if not parts:
        return
    name = parts[0]
    args = parts[1:]
    cmd = COMMANDS.get(name)
    if cmd is None:
        print(f"Unknown command: /{name}  (try /help)")
        return
    try:
        cmd.handler(args, ctx)
    except Exception as e:
        print(f"[/{name}] error: {e}")


def run_shell(body: str) -> None:
    """Shell escape: `!ls -la` etc. Blocks until the command exits."""
    cmd = body.strip()
    if not cmd:
        return
    try:
        subprocess.run(cmd, shell=True)
    except Exception as e:
        print(f"[shell] error: {e}")
