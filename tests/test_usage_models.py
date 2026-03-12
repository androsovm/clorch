"""Tests for clorch.usage.models."""
from __future__ import annotations

from clorch.usage.models import SessionUsage, TokenUsage, UsageSummary


class TestTokenUsage:
    def test_defaults(self):
        t = TokenUsage()
        assert t.input_tokens == 0
        assert t.output_tokens == 0
        assert t.cache_creation_input_tokens == 0
        assert t.cache_read_input_tokens == 0

    def test_total_input(self):
        t = TokenUsage(input_tokens=100, cache_creation_input_tokens=50, cache_read_input_tokens=30)
        assert t.total_input == 180

    def test_iadd(self):
        a = TokenUsage(
            input_tokens=10, output_tokens=20,
            cache_creation_input_tokens=5, cache_read_input_tokens=3,
        )
        b = TokenUsage(
            input_tokens=7, output_tokens=8,
            cache_creation_input_tokens=2, cache_read_input_tokens=1,
        )
        a += b
        assert a.input_tokens == 17
        assert a.output_tokens == 28
        assert a.cache_creation_input_tokens == 7
        assert a.cache_read_input_tokens == 4

    def test_iadd_returns_self(self):
        a = TokenUsage(input_tokens=1)
        b = TokenUsage(input_tokens=2)
        result = a.__iadd__(b)
        assert result is a

    def test_last_input_default(self):
        t = TokenUsage()
        assert t.last_input == 0

    def test_iadd_last_input_overwrites(self):
        """last_input takes the latest non-zero value, not accumulated."""
        a = TokenUsage(last_input=50_000)
        b = TokenUsage(last_input=80_000)
        a += b
        assert a.last_input == 80_000

    def test_iadd_last_input_preserves_when_other_zero(self):
        a = TokenUsage(last_input=50_000)
        b = TokenUsage(last_input=0)
        a += b
        assert a.last_input == 50_000

    def test_context_window_pct_basic(self):
        t = TokenUsage(last_input=100_000)
        assert t.context_window_pct(200_000) == 50.0

    def test_context_window_pct_capped_at_100(self):
        t = TokenUsage(last_input=300_000)
        assert t.context_window_pct(200_000) == 100.0

    def test_context_window_pct_zero_last_input(self):
        t = TokenUsage(last_input=0)
        assert t.context_window_pct(200_000) == 0.0

    def test_context_window_pct_zero_capacity(self):
        t = TokenUsage(last_input=100_000)
        assert t.context_window_pct(0) == 0.0

    def test_context_window_pct_exact_capacity(self):
        t = TokenUsage(last_input=200_000)
        assert t.context_window_pct(200_000) == 100.0

    def test_context_window_pct_small_values(self):
        t = TokenUsage(last_input=1)
        pct = t.context_window_pct(200_000)
        assert 0.0 < pct < 1.0

    def test_context_window_pct_negative_capacity(self):
        t = TokenUsage(last_input=100_000)
        assert t.context_window_pct(-1) == 0.0


class TestSessionUsage:
    def test_defaults(self):
        su = SessionUsage()
        assert su.session_id == ""
        assert su.model == ""
        assert su.message_count == 0
        assert su.cost == 0.0
        assert su.tokens.input_tokens == 0


class TestUsageSummary:
    def test_defaults(self):
        s = UsageSummary()
        assert s.total_cost == 0.0
        assert s.total_tokens == 0
        assert s.message_count == 0
        assert s.session_count == 0
        assert s.sessions == {}

    def test_total_tokens(self):
        s = UsageSummary(total_input=1000, total_output=500)
        assert s.total_tokens == 1500

    def test_sessions_default_is_independent(self):
        s1 = UsageSummary()
        s2 = UsageSummary()
        s1.sessions["a"] = SessionUsage(session_id="a")
        assert "a" not in s2.sessions
