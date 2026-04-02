"""Token budget tracking.

Implements a budget system for context window management:
  Effective Window = Context Window - Compact Reserve
  Autocompact Threshold = Effective Window - Buffer
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TokenBudget:
    context_window: int = 200_000
    compact_reserve: int = 40_000
    autocompact_buffer: int = 13_000
    current_input_tokens: int = 0
    current_output_tokens: int = 0

    def effective_window(self) -> int:
        """Context Window - Compact Reserve."""
        return self.context_window - self.compact_reserve

    def autocompact_threshold(self) -> int:
        """Effective Window - Buffer."""
        return self.effective_window() - self.autocompact_buffer

    def should_compact(self) -> bool:
        """True when input tokens exceed the autocompact threshold."""
        return self.current_input_tokens >= self.autocompact_threshold()

    def is_critical(self) -> bool:
        """True when dangerously close to hard context limit."""
        return self.current_input_tokens >= self.effective_window()

    def update_from_usage(self, usage: dict) -> TokenBudget:
        """Create new budget with updated token counts from API response."""
        return TokenBudget(
            context_window=self.context_window,
            compact_reserve=self.compact_reserve,
            autocompact_buffer=self.autocompact_buffer,
            current_input_tokens=usage.get("input_tokens", self.current_input_tokens),
            current_output_tokens=usage.get("output_tokens", self.current_output_tokens),
        )
