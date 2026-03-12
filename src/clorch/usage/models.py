"""Data models for Claude Code usage tracking."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TokenUsage:
    """Token counts for a session or aggregate."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    # Overwritten (not accumulated) per message — represents current context window size
    last_input: int = 0

    @property
    def total_input(self) -> int:
        """Total input tokens including cache write and read."""
        return self.input_tokens + self.cache_creation_input_tokens + self.cache_read_input_tokens

    def context_window_pct(self, capacity: int) -> float:
        """Context window utilization from last message (0.0-100.0).

        Uses last_input (most recent API call's total input tokens)
        as a proxy for current context window fill.
        """
        if not self.last_input or capacity <= 0:
            return 0.0
        return min(self.last_input / capacity * 100, 100.0)

    def __iadd__(self, other: TokenUsage) -> TokenUsage:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_creation_input_tokens += other.cache_creation_input_tokens
        self.cache_read_input_tokens += other.cache_read_input_tokens
        if other.last_input:
            self.last_input = other.last_input
        return self


@dataclass
class SessionUsage:
    """Usage data for a single Claude Code session."""

    session_id: str = ""
    model: str = ""
    tokens: TokenUsage = field(default_factory=TokenUsage)
    message_count: int = 0
    cost: float = 0.0


@dataclass
class UsageSummary:
    """Aggregated usage across all sessions."""

    total_cost: float = 0.0
    total_input: int = 0
    total_output: int = 0
    cache_read: int = 0
    cache_write: int = 0
    cache_hit_rate: float = 0.0
    burn_rate: float = 0.0
    message_count: int = 0
    session_count: int = 0
    sessions: dict[str, SessionUsage] = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        """Input (excl. cache read) + output."""
        return self.total_input + self.total_output
