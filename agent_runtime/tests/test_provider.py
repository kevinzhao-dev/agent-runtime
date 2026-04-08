"""Tests for provider abstraction (no real API calls)."""
import json

from agent_runtime.provider import (
    bare_model,
    detect_provider,
    get_context_limit,
    messages_to_anthropic,
    messages_to_openai,
    tools_to_openai,
)


class TestDetectProvider:
    def test_anthropic(self):
        assert detect_provider("claude-sonnet-4-6") == "anthropic"
        assert detect_provider("claude-opus-4-6") == "anthropic"

    def test_openai(self):
        assert detect_provider("gpt-4o") == "openai"
        assert detect_provider("gpt-4o-mini") == "openai"
        assert detect_provider("o3-mini") == "openai"

    def test_gemini(self):
        assert detect_provider("gemini-2.0-flash") == "gemini"

    def test_deepseek(self):
        assert detect_provider("deepseek-chat") == "deepseek"

    def test_ollama(self):
        assert detect_provider("llama3.3") == "ollama"
        assert detect_provider("qwen2.5-coder") == "ollama"

    def test_explicit_prefix(self):
        assert detect_provider("ollama/mistral") == "ollama"
        assert detect_provider("custom/my-model") == "custom"

    def test_fallback(self):
        assert detect_provider("unknown-model") == "openai"


class TestBareModel:
    def test_no_prefix(self):
        assert bare_model("gpt-4o") == "gpt-4o"

    def test_with_prefix(self):
        assert bare_model("ollama/llama3.3") == "llama3.3"


class TestContextLimit:
    def test_anthropic(self):
        assert get_context_limit("claude-sonnet-4-6") == 200_000

    def test_openai(self):
        assert get_context_limit("gpt-4o") == 128_000

    def test_gemini(self):
        assert get_context_limit("gemini-2.0-flash") == 1_000_000


class TestMessagesToAnthropic:
    def test_user_message(self):
        msgs = [{"role": "user", "content": "hi"}]
        result = messages_to_anthropic(msgs)
        assert result == [{"role": "user", "content": "hi"}]

    def test_assistant_with_text(self):
        msgs = [{"role": "assistant", "content": "hello"}]
        result = messages_to_anthropic(msgs)
        assert result[0]["role"] == "assistant"
        assert result[0]["content"] == [{"type": "text", "text": "hello"}]

    def test_assistant_with_tool_calls(self):
        msgs = [{
            "role": "assistant",
            "content": "let me read",
            "tool_calls": [{"id": "t1", "name": "read_file", "input": {"path": "a.py"}}],
        }]
        result = messages_to_anthropic(msgs)
        blocks = result[0]["content"]
        assert len(blocks) == 2
        assert blocks[0]["type"] == "text"
        assert blocks[1]["type"] == "tool_use"
        assert blocks[1]["name"] == "read_file"

    def test_tool_results_grouped(self):
        msgs = [
            {"role": "tool", "tool_call_id": "t1", "name": "read_file", "content": "data1"},
            {"role": "tool", "tool_call_id": "t2", "name": "bash", "content": "data2"},
        ]
        result = messages_to_anthropic(msgs)
        assert len(result) == 1  # grouped into one user message
        assert result[0]["role"] == "user"
        assert len(result[0]["content"]) == 2
        assert result[0]["content"][0]["type"] == "tool_result"


class TestMessagesToOpenAI:
    def test_user_message(self):
        msgs = [{"role": "user", "content": "hi"}]
        result = messages_to_openai(msgs)
        assert result == [{"role": "user", "content": "hi"}]

    def test_assistant_with_tool_calls(self):
        msgs = [{
            "role": "assistant",
            "content": "doing",
            "tool_calls": [{"id": "t1", "name": "bash", "input": {"cmd": "ls"}}],
        }]
        result = messages_to_openai(msgs)
        tc = result[0]["tool_calls"][0]
        assert tc["type"] == "function"
        assert tc["function"]["name"] == "bash"
        args = json.loads(tc["function"]["arguments"])
        assert args == {"cmd": "ls"}

    def test_tool_result(self):
        msgs = [{"role": "tool", "tool_call_id": "t1", "name": "bash", "content": "output"}]
        result = messages_to_openai(msgs)
        assert result[0]["role"] == "tool"
        assert result[0]["tool_call_id"] == "t1"


class TestToolsToOpenAI:
    def test_conversion(self):
        schemas = [{
            "name": "read_file",
            "description": "Read a file",
            "input_schema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        }]
        result = tools_to_openai(schemas)
        assert len(result) == 1
        assert result[0]["type"] == "function"
        assert result[0]["function"]["name"] == "read_file"
        assert result[0]["function"]["parameters"]["type"] == "object"
