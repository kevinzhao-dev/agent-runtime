"""Tests for verify/verifier.py — strategies and parsing."""

import pytest

from verify.verifier import (
    LLMReviewStrategy,
    PytestStrategy,
    Verdict,
    VerifyContext,
    VerifyResult,
)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

def test_verdict_values():
    assert Verdict.PASS == "pass"
    assert Verdict.FAIL == "fail"
    assert Verdict.PARTIAL == "partial"


def test_verify_result():
    r = VerifyResult(verdict=Verdict.PASS, reason="all good")
    assert r.verdict == Verdict.PASS
    assert r.details is None


def test_verify_context():
    ctx = VerifyContext(
        task_description="build X",
        working_dir="/tmp",
        files_changed=["a.py"],
    )
    assert ctx.task_description == "build X"


# ---------------------------------------------------------------------------
# PytestStrategy
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pytest_strategy_pass(tmp_path):
    (tmp_path / "test_ok.py").write_text("def test_pass():\n    assert True\n")
    strategy = PytestStrategy(test_command="python -m pytest -v")
    ctx = VerifyContext(task_description="test", working_dir=str(tmp_path))
    result = await strategy.verify(ctx)
    assert result.verdict == Verdict.PASS
    assert "passed" in result.reason.lower()


@pytest.mark.asyncio
async def test_pytest_strategy_fail(tmp_path):
    (tmp_path / "test_fail.py").write_text("def test_fail():\n    assert False\n")
    strategy = PytestStrategy(test_command="python -m pytest -v")
    ctx = VerifyContext(task_description="test", working_dir=str(tmp_path))
    result = await strategy.verify(ctx)
    assert result.verdict == Verdict.FAIL


@pytest.mark.asyncio
async def test_pytest_strategy_no_tests(tmp_path):
    strategy = PytestStrategy(test_command="python -m pytest -v")
    ctx = VerifyContext(task_description="test", working_dir=str(tmp_path))
    result = await strategy.verify(ctx)
    # pytest exits with code 5 when no tests found
    assert result.verdict == Verdict.FAIL


# ---------------------------------------------------------------------------
# LLMReviewStrategy — parse_review logic
# ---------------------------------------------------------------------------

def test_parse_review_pass():
    strategy = LLMReviewStrategy()
    result = strategy._parse_review("After review, VERDICT: PASS. Everything looks correct.")
    assert result.verdict == Verdict.PASS


def test_parse_review_fail():
    strategy = LLMReviewStrategy()
    result = strategy._parse_review("VERDICT: FAIL. Found a bug in line 42.")
    assert result.verdict == Verdict.FAIL


def test_parse_review_partial():
    strategy = LLMReviewStrategy()
    result = strategy._parse_review("VERDICT: PARTIAL. Some tests pass but edge cases missing.")
    assert result.verdict == Verdict.PARTIAL


def test_parse_review_heuristic_bug():
    strategy = LLMReviewStrategy()
    result = strategy._parse_review("I found a bug in the auth handler.")
    assert result.verdict == Verdict.FAIL


def test_parse_review_heuristic_looks_good():
    strategy = LLMReviewStrategy()
    result = strategy._parse_review("The code all correct and well structured.")
    assert result.verdict == Verdict.PASS


def test_parse_review_fallback_partial():
    strategy = LLMReviewStrategy()
    result = strategy._parse_review("The implementation is interesting.")
    assert result.verdict == Verdict.PARTIAL
