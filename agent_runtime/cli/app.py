"""CLI entrypoint — thin REPL that drives the query loop.

This is the entrypoint, not business logic. Keep it minimal.
"""
from __future__ import annotations

import asyncio
import sys

from agent_runtime.cli.bus import EventBus
from agent_runtime.cli.commands import ReplContext, dispatch, run_shell
from agent_runtime.cli.display import Spinner
from agent_runtime.cli.prompt_view import build_current_prompt, layer_stats
from agent_runtime.engine import SessionState, TurnConfig, compact, run_query_loop
from agent_runtime.packs import load_pack, pack_registry
from agent_runtime.storage import (
    append_transcript,
    init_meta,
    list_snapshots,
    save_session,
    save_snapshot,
)


def _make_permission_prompt(ctx: ReplContext):
    """Build a permission callback that reads step-mode / breakpoints from ctx."""
    def _cb(tool_name: str, tool_input: dict) -> bool:
        reg = pack_registry()
        high_risk = reg.is_high_risk(tool_name)
        tool_break = tool_name in ctx.break_tools
        if not (ctx.step_mode or high_risk or tool_break):
            return True
        reasons = []
        if ctx.step_mode:
            reasons.append("step")
        if high_risk:
            reasons.append("high-risk")
        if tool_break:
            reasons.append(f"break:{tool_name}")
        print(f"\n[Pause: {', '.join(reasons)}] Tool: {tool_name}")
        print(f"  Input: {tool_input}")
        answer = input("  Allow? (y/n): ").strip().lower()
        return answer in ("y", "yes")
    return _cb


def _pause_for_inspection(ctx: ReplContext, reason: str) -> str:
    """Mini-REPL that runs while a turn-breakpoint is paused.

    Accepts slash commands, shell escapes, plus `continue` / `abort`.
    Returns `"continue"` or `"abort"`.
    """
    print(f"\n[Break: {reason}]  slash commands available; 'continue' to resume, 'abort' to skip")
    while True:
        try:
            line = input("(paused)> ").strip()
        except (EOFError, KeyboardInterrupt):
            return "abort"
        if not line:
            continue
        if line in ("continue", "c"):
            return "continue"
        if line in ("abort", "a"):
            return "abort"
        if line.startswith("/"):
            dispatch(line[1:], ctx)
        elif line.startswith("!"):
            run_shell(line[1:])
        else:
            print("(while paused) use /<cmd>, 'continue', or 'abort'")


# ── Display subscriber ────────────────────────────────────────────────────

class DisplayRenderer:
    """Bus subscriber that prints events to the terminal with a spinner."""

    def __init__(self) -> None:
        self._spinner: Spinner | None = None
        self._first_chunk = True

    def start_turn(self, label: str = "Thinking") -> None:
        self._spinner = Spinner(label)
        self._spinner.start()
        self._first_chunk = True

    def end_turn(self) -> None:
        self._stop_spinner()

    def _stop_spinner(self) -> None:
        if self._spinner is not None:
            self._spinner.stop()
            self._spinner = None

    def on_event(self, event) -> None:
        etype = event.type
        if self._first_chunk and etype in ("text_delta", "tool_call", "final"):
            self._stop_spinner()
            self._first_chunk = False

        if etype == "text_delta":
            print(event.text, end="", flush=True)
        elif etype == "thinking":
            pass
        elif etype == "tool_call":
            print(f"\n[Tool: {event.tool_name}]")
        elif etype == "tool_result":
            status = "ok" if event.status == "ok" else f"ERROR: {event.status}"
            print(f"  → {status}")
            self._spinner = Spinner("Processing")
            self._spinner.start()
            self._first_chunk = False
        elif etype == "recovery":
            print(f"\n[Recovery: {event.reason}] {event.detail}")
        elif etype == "final":
            print()


def _event_to_record(event) -> dict | None:
    """Flatten an event into a JSON-friendly transcript record.

    Return None for events that aren't worth persisting (thinking, per-token
    text deltas — `final` already carries the full text).
    """
    etype = event.type
    if etype == "thinking" or etype == "text_delta":
        return None
    if etype == "tool_call":
        return {
            "type": "tool_call",
            "tool_call_id": event.tool_call_id,
            "tool_name": event.tool_name,
            "tool_input": event.tool_input,
        }
    if etype == "tool_result":
        return {
            "type": "tool_result",
            "tool_call_id": event.tool_call_id,
            "tool_name": event.tool_name,
            "status": event.status,
            "output": event.output,
        }
    if etype == "final":
        return {"type": "final", "text": event.text}
    if etype == "recovery":
        return {"type": "recovery", "reason": event.reason, "detail": event.detail}
    return {"type": etype}


def _make_transcript_subscriber(ctx: ReplContext):
    """Full-payload transcript subscriber (schema v2)."""
    def _sub(event) -> None:
        record = _event_to_record(event)
        if record is None:
            return
        record["user_turn"] = ctx.user_turn
        append_transcript(ctx.state.session_id, record)
    return _sub


# ── REPL ──────────────────────────────────────────────────────────────────

_BANNER = """\
Agent Runtime v0.1.0 | Session: {sid}
Pack: {pack} | Model: {model} | Max turns: {turns}
Type a message to talk to the agent.
  /help          list dev commands
  !<cmd>         shell escape
  quit / exit    leave
"""


async def _run_session(config: TurnConfig, pack_name: str = "coding") -> None:
    """Run an interactive REPL session."""
    from agent_runtime.packs import get_active_pack
    try:
        load_pack(pack_name)
    except FileNotFoundError as e:
        print(f"[pack] {e}")
        return

    state = SessionState()
    ctx = ReplContext(state=state, config=config)

    # Initialize meta.json for the fresh session (schema v2).
    init_meta(state.session_id)

    bus = EventBus()
    renderer = DisplayRenderer()
    bus.subscribe(renderer.on_event)
    bus.subscribe(_make_transcript_subscriber(ctx))
    permission_cb = _make_permission_prompt(ctx)

    active = get_active_pack()
    pack_label = active.name if active else "(none)"
    print(_BANNER.format(sid=state.session_id, pack=pack_label, model=config.model_name, turns=config.max_turns))

    while True:
        # Read input — either a queued replay line or real stdin.
        if ctx.pending_inputs:
            line = ctx.pending_inputs.pop(0).strip()
            print(f"You (replay): {line}")
        else:
            try:
                line = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nGoodbye.")
                break

        if not line:
            continue
        if line.lower() in ("quit", "exit"):
            break
        if line.startswith("/"):
            dispatch(line[1:], ctx)
            continue
        if line.startswith("!"):
            run_shell(line[1:])
            continue

        # Turn-level breakpoint: pause before sending to the model.
        if ctx.user_turn in ctx.break_turns:
            decision = _pause_for_inspection(ctx, f"turn:{ctx.user_turn}")
            if decision == "abort":
                print("(turn aborted)")
                continue

        # Agent turn. Read live state/config from ctx so commands that swap
        # session (fork / replay) or override config take effect immediately.
        active_state = ctx.state
        active_config = ctx.config

        pc = build_current_prompt(active_state, active_config)
        system_prompt = pc.system_prompt

        append_transcript(active_state.session_id, {
            "type": "user_input",
            "user_turn": ctx.user_turn,
            "text": line,
        })
        append_transcript(active_state.session_id, {
            "type": "system_prompt",
            "user_turn": ctx.user_turn,
            "prompt": system_prompt,
            "layers": layer_stats(pc),
        })

        renderer.start_turn()
        async for event in run_query_loop(
            line, active_state, active_config,
            system_prompt=system_prompt,
            permission_callback=permission_cb,
            compact_handler=compact,
            tool_registry=pack_registry(),
        ):
            bus.publish(event)
        renderer.end_turn()

        save_session(active_state)
        save_snapshot(active_state, ctx.user_turn)
        ctx.user_turn += 1

    # Final save
    save_session(ctx.state)
    print(f"\nSession saved: {ctx.state.session_id}")
    print(f"Tokens: {ctx.state.total_input_tokens} in / {ctx.state.total_output_tokens} out")


def main() -> None:
    """Entry point.

    Usage: python -m agent_runtime [MODEL] [--pack NAME]
    """
    args = list(sys.argv[1:])
    pack_name = "coding"
    if "--pack" in args:
        i = args.index("--pack")
        if i + 1 < len(args):
            pack_name = args[i + 1]
            del args[i : i + 2]
        else:
            print("--pack requires an argument")
            return
    model = args[0] if args else "gpt-5.4-mini"

    config = TurnConfig(model_name=model)

    try:
        asyncio.run(_run_session(config, pack_name=pack_name))
    except KeyboardInterrupt:
        print("\nAborted.")


if __name__ == "__main__":
    main()
