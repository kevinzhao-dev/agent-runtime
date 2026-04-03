"""Tests for engine/recovery.py — error recovery handlers."""

import pytest

from engine.recovery import (
    API_RETRY_MAX,
    MAX_OUTPUT_RECOVERY_LIMIT,
    RetryDecision,
    handle_api_error,
    handle_max_output_tokens,
    handle_prompt_too_long,
)
from engine.state import CompactTracking, LoopState


def test_handle_max_output_tokens_injects_continuation():
    state = LoopState(messages=({"role": "user", "content": "hi"},))
    result = handle_max_output_tokens(state, "partial text")
    assert result is not None
    assert len(result.messages) == 3  # original + assistant + continuation
    assert result.messages[1]["role"] == "assistant"
    assert result.messages[2]["role"] == "user"
    assert "truncated" in result.messages[2]["content"].lower()
    assert result.max_output_recoveries == 1


def test_handle_max_output_tokens_circuit_breaker():
    state = LoopState(
        messages=(),
        max_output_recoveries=MAX_OUTPUT_RECOVERY_LIMIT,
    )
    result = handle_max_output_tokens(state, "text")
    assert result is None


def test_handle_api_error_retryable():
    error = type("FakeError", (), {"status_code": 429})()
    decision = handle_api_error(error, attempt=0)
    assert decision.should_retry is True
    assert decision.delay_seconds > 0


def test_handle_api_error_not_retryable():
    error = type("FakeError", (), {"status_code": 400})()
    decision = handle_api_error(error, attempt=0)
    assert decision.should_retry is False


def test_handle_api_error_max_retries():
    error = type("FakeError", (), {"status_code": 500})()
    decision = handle_api_error(error, attempt=API_RETRY_MAX)
    assert decision.should_retry is False


def test_handle_api_error_exponential_backoff():
    error = type("FakeError", (), {"status_code": 503})()
    d0 = handle_api_error(error, attempt=0)
    d1 = handle_api_error(error, attempt=1)
    d2 = handle_api_error(error, attempt=2)
    # Each delay should be roughly doubling (with jitter)
    assert d1.delay_seconds > d0.delay_seconds * 0.5
    assert d2.delay_seconds > d1.delay_seconds * 0.5


def test_handle_api_error_server_errors_retryable():
    for code in [429, 500, 502, 503, 529]:
        error = type("FakeError", (), {"status_code": code})()
        decision = handle_api_error(error, attempt=0)
        assert decision.should_retry is True, f"Status {code} should be retryable"


def test_handle_api_error_client_errors_not_retryable():
    for code in [400, 401, 403, 404]:
        error = type("FakeError", (), {"status_code": code})()
        decision = handle_api_error(error, attempt=0)
        assert decision.should_retry is False, f"Status {code} should not be retryable"


@pytest.mark.asyncio
async def test_handle_prompt_too_long_circuit_breaker():
    state = LoopState(
        messages=({"role": "user", "content": "hi"},),
        compact_tracking=CompactTracking(consecutive_failures=3),
    )
    result = await handle_prompt_too_long(state, "claude-sonnet-4-6")
    assert result is None
