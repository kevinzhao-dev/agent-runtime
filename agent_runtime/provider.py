"""Model provider abstraction with streaming support.

MVP supports two adapter types:
  - Anthropic (native SDK)
  - OpenAI-compatible (covers OpenAI, Gemini, DeepSeek, Ollama, etc.)

Internal neutral message format is provider-agnostic.
Converters translate between neutral and API-specific formats.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Generator


# ── Provider Registry ─────────────────────────────────────────────────────

PROVIDERS: dict[str, dict[str, Any]] = {
    "anthropic": {
        "type": "anthropic",
        "api_key_env": "ANTHROPIC_API_KEY",
        "context_limit": 200_000,
        "models": [
            "claude-opus-4-6", "claude-sonnet-4-6",
            "claude-haiku-4-5-20251001",
        ],
    },
    "openai": {
        "type": "openai",
        "api_key_env": "OPENAI_API_KEY",
        "base_url": "https://api.openai.com/v1",
        "context_limit": 128_000,
        "models": ["gpt-5.4", "gpt-5.4-mini", "gpt-5.4-nano", "o3-mini"],
    },
    "gemini": {
        "type": "openai",
        "api_key_env": "GEMINI_API_KEY",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "context_limit": 1_000_000,
        "models": ["gemini-2.5-pro-preview-03-25", "gemini-2.0-flash"],
    },
    "deepseek": {
        "type": "openai",
        "api_key_env": "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com/v1",
        "context_limit": 64_000,
        "models": ["deepseek-chat", "deepseek-reasoner"],
    },
    "ollama": {
        "type": "openai",
        "api_key_env": None,
        "base_url": "http://localhost:11434/v1",
        "api_key": "ollama",
        "context_limit": 128_000,
        "models": ["llama3.3", "qwen2.5-coder", "gemma3"],
    },
}

# Auto-detection: prefix → provider name
_PREFIXES: list[tuple[str, str]] = [
    ("claude-", "anthropic"),
    ("gpt-", "openai"),
    ("o1", "openai"),
    ("o3", "openai"),
    ("gemini-", "gemini"),
    ("deepseek-", "deepseek"),
    ("llama", "ollama"),
    ("qwen", "ollama"),
    ("gemma", "ollama"),
]


def detect_provider(model: str) -> str:
    """Return provider name for a model string.

    Supports 'provider/model' explicit format, or auto-detect by prefix.
    """
    if "/" in model:
        return model.split("/", 1)[0]
    lower = model.lower()
    for prefix, name in _PREFIXES:
        if lower.startswith(prefix):
            return name
    return "openai"  # fallback


def bare_model(model: str) -> str:
    """Strip 'provider/' prefix if present."""
    return model.split("/", 1)[1] if "/" in model else model


def get_api_key(provider_name: str, config: dict[str, Any] | None = None) -> str:
    """Resolve API key from config dict or environment."""
    config = config or {}
    prov = PROVIDERS.get(provider_name, {})
    # 1. Config dict
    cfg_key = config.get(f"{provider_name}_api_key", "")
    if cfg_key:
        return cfg_key
    # 2. Environment variable
    env_var = prov.get("api_key_env")
    if env_var:
        return os.environ.get(env_var, "")
    # 3. Hardcoded (local providers)
    return prov.get("api_key", "")


def get_context_limit(model: str) -> int:
    """Return context window size for a model."""
    provider_name = detect_provider(model)
    prov = PROVIDERS.get(provider_name, {})
    return prov.get("context_limit", 128_000)


# ── Streaming Event Types ─────────────────────────────────────────────────

@dataclass(slots=True)
class TextChunk:
    """Streaming text delta from model."""
    text: str


@dataclass(slots=True)
class ThinkingChunk:
    """Streaming thinking/reasoning delta."""
    text: str


@dataclass(slots=True)
class AssistantTurn:
    """Completed assistant turn with text, tool calls, and token usage."""
    text: str
    tool_calls: list[dict[str, Any]]  # [{"id": ..., "name": ..., "input": {...}}]
    input_tokens: int
    output_tokens: int


# ── Message Format Converters ─────────────────────────────────────────────

def messages_to_anthropic(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert neutral messages → Anthropic API format."""
    result: list[dict[str, Any]] = []
    i = 0
    while i < len(messages):
        m = messages[i]
        role = m["role"]

        if role == "user":
            result.append({"role": "user", "content": m["content"]})
            i += 1

        elif role == "assistant":
            blocks: list[dict[str, Any]] = []
            text = m.get("content", "")
            if text:
                blocks.append({"type": "text", "text": text})
            for tc in m.get("tool_calls", []):
                blocks.append({
                    "type": "tool_use",
                    "id": tc["id"],
                    "name": tc["name"],
                    "input": tc["input"],
                })
            result.append({"role": "assistant", "content": blocks})
            i += 1

        elif role == "tool":
            # Collect consecutive tool results into one user message
            tool_blocks: list[dict[str, Any]] = []
            while i < len(messages) and messages[i]["role"] == "tool":
                t = messages[i]
                tool_blocks.append({
                    "type": "tool_result",
                    "tool_use_id": t["tool_call_id"],
                    "content": t["content"],
                })
                i += 1
            result.append({"role": "user", "content": tool_blocks})

        else:
            i += 1

    return result


def messages_to_openai(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert neutral messages → OpenAI API format."""
    result: list[dict[str, Any]] = []
    for m in messages:
        role = m["role"]

        if role == "user":
            result.append({"role": "user", "content": m["content"]})

        elif role == "assistant":
            msg: dict[str, Any] = {"role": "assistant", "content": m.get("content") or None}
            tcs = m.get("tool_calls", [])
            if tcs:
                msg["tool_calls"] = [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc["input"], ensure_ascii=False),
                        },
                    }
                    for tc in tcs
                ]
            result.append(msg)

        elif role == "tool":
            result.append({
                "role": "tool",
                "tool_call_id": m["tool_call_id"],
                "content": m["content"],
            })

    return result


def tools_to_openai(tool_schemas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert Anthropic-style tool schemas to OpenAI function-calling format."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in tool_schemas
    ]


# ── Streaming Adapters ────────────────────────────────────────────────────

def stream_anthropic(
    api_key: str,
    model: str,
    system: str,
    messages: list[dict[str, Any]],
    tool_schemas: list[dict[str, Any]],
    max_tokens: int = 8192,
) -> Generator[TextChunk | ThinkingChunk | AssistantTurn, None, None]:
    """Stream from Anthropic API."""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages_to_anthropic(messages),
    }
    if tool_schemas:
        kwargs["tools"] = tool_schemas

    text = ""
    tool_calls: list[dict[str, Any]] = []

    with client.messages.stream(**kwargs) as s:
        for event in s:
            etype = getattr(event, "type", None)
            if etype == "content_block_delta":
                delta = event.delta
                dtype = getattr(delta, "type", None)
                if dtype == "text_delta":
                    text += delta.text
                    yield TextChunk(delta.text)
                elif dtype == "thinking_delta":
                    yield ThinkingChunk(delta.thinking)

        final = s.get_final_message()
        for block in final.content:
            if block.type == "tool_use":
                tool_calls.append({
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })

        yield AssistantTurn(
            text, tool_calls,
            final.usage.input_tokens,
            final.usage.output_tokens,
        )


def stream_openai_compat(
    api_key: str,
    base_url: str,
    model: str,
    system: str,
    messages: list[dict[str, Any]],
    tool_schemas: list[dict[str, Any]],
    max_tokens: int = 8192,
) -> Generator[TextChunk | ThinkingChunk | AssistantTurn, None, None]:
    """Stream from any OpenAI-compatible API."""
    from openai import OpenAI

    client = OpenAI(api_key=api_key or "dummy", base_url=base_url)
    oai_messages = [{"role": "system", "content": system}] + messages_to_openai(messages)

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": oai_messages,
        "stream": True,
        "max_completion_tokens": max_tokens,
    }
    if tool_schemas:
        kwargs["tools"] = tools_to_openai(tool_schemas)
        kwargs["tool_choice"] = "auto"

    text = ""
    tool_buf: dict[int, dict[str, Any]] = {}
    in_tok = out_tok = 0

    response = client.chat.completions.create(**kwargs)
    for chunk in response:
        if not chunk.choices:
            if hasattr(chunk, "usage") and chunk.usage:
                in_tok = chunk.usage.prompt_tokens or 0
                out_tok = chunk.usage.completion_tokens or 0
            continue

        delta = chunk.choices[0].delta

        if delta.content:
            text += delta.content
            yield TextChunk(delta.content)

        if delta.tool_calls:
            for tc in delta.tool_calls:
                idx = tc.index
                if idx not in tool_buf:
                    tool_buf[idx] = {"id": "", "name": "", "args": ""}
                if tc.id:
                    tool_buf[idx]["id"] = tc.id
                if tc.function:
                    if tc.function.name:
                        tool_buf[idx]["name"] += tc.function.name
                    if tc.function.arguments:
                        tool_buf[idx]["args"] += tc.function.arguments

        if hasattr(chunk, "usage") and chunk.usage:
            in_tok = chunk.usage.prompt_tokens or in_tok
            out_tok = chunk.usage.completion_tokens or out_tok

    tool_calls: list[dict[str, Any]] = []
    for idx in sorted(tool_buf):
        v = tool_buf[idx]
        try:
            inp = json.loads(v["args"]) if v["args"] else {}
        except json.JSONDecodeError:
            inp = {"_raw": v["args"]}
        tool_calls.append({
            "id": v["id"] or f"call_{idx}",
            "name": v["name"],
            "input": inp,
        })

    yield AssistantTurn(text, tool_calls, in_tok, out_tok)


# ── Unified Entry Point ───────────────────────────────────────────────────

def stream(
    model: str,
    system: str,
    messages: list[dict[str, Any]],
    tool_schemas: list[dict[str, Any]] | None = None,
    max_tokens: int = 8192,
    config: dict[str, Any] | None = None,
) -> Generator[TextChunk | ThinkingChunk | AssistantTurn, None, None]:
    """Unified streaming entry point. Auto-detects provider from model string."""
    config = config or {}
    tool_schemas = tool_schemas or []
    provider_name = detect_provider(model)
    model_name = bare_model(model)
    prov = PROVIDERS.get(provider_name, PROVIDERS["openai"])
    api_key = get_api_key(provider_name, config)

    if prov["type"] == "anthropic":
        yield from stream_anthropic(
            api_key, model_name, system, messages, tool_schemas, max_tokens,
        )
    else:
        base_url = prov.get("base_url", "https://api.openai.com/v1")
        yield from stream_openai_compat(
            api_key, base_url, model_name, system, messages,
            tool_schemas, max_tokens,
        )
