"""Tests for context/budget.py — TokenBudget calculations."""

from context.budget import TokenBudget


def test_defaults():
    b = TokenBudget()
    assert b.context_window == 200_000
    assert b.compact_reserve == 40_000
    assert b.autocompact_buffer == 13_000


def test_effective_window():
    b = TokenBudget(context_window=200_000, compact_reserve=40_000)
    assert b.effective_window() == 160_000


def test_autocompact_threshold():
    b = TokenBudget()
    assert b.autocompact_threshold() == 200_000 - 40_000 - 13_000  # 147_000


def test_should_compact_below_threshold():
    b = TokenBudget(current_input_tokens=100_000)
    assert b.should_compact() is False


def test_should_compact_at_threshold():
    b = TokenBudget(current_input_tokens=147_000)
    assert b.should_compact() is True


def test_should_compact_above_threshold():
    b = TokenBudget(current_input_tokens=150_000)
    assert b.should_compact() is True


def test_is_critical():
    b = TokenBudget(current_input_tokens=160_000)
    assert b.is_critical() is True


def test_is_not_critical():
    b = TokenBudget(current_input_tokens=100_000)
    assert b.is_critical() is False


def test_update_from_usage():
    b = TokenBudget()
    new = b.update_from_usage({"input_tokens": 5000, "output_tokens": 1000})
    assert new.current_input_tokens == 5000
    assert new.current_output_tokens == 1000
    assert b.current_input_tokens == 0  # original unchanged


def test_update_from_usage_preserves_config():
    b = TokenBudget(context_window=100_000, compact_reserve=20_000)
    new = b.update_from_usage({"input_tokens": 500})
    assert new.context_window == 100_000
    assert new.compact_reserve == 20_000
