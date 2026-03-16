"""Tests for clorch.constants."""
from __future__ import annotations

from clorch.constants import (
    CONTEXT_WINDOW_CAPACITY,
    GREEN,
    RED,
    YELLOW,
    context_pct_color,
    model_context_capacity,
)


class TestContextPctColor:
    def test_low_usage_green(self):
        assert context_pct_color(0.0) == GREEN
        assert context_pct_color(59.9) == GREEN

    def test_medium_usage_yellow(self):
        assert context_pct_color(60.0) == YELLOW
        assert context_pct_color(79.9) == YELLOW

    def test_high_usage_red(self):
        assert context_pct_color(80.0) == RED
        assert context_pct_color(100.0) == RED

    def test_boundary_60(self):
        """Exactly 60% should be yellow, not green."""
        assert context_pct_color(60.0) == YELLOW
        assert context_pct_color(59.99) == GREEN

    def test_boundary_80(self):
        """Exactly 80% should be red, not yellow."""
        assert context_pct_color(80.0) == RED
        assert context_pct_color(79.99) == YELLOW


class TestModelContextCapacity:
    def test_opus_1m(self):
        assert model_context_capacity("claude-opus-4-6") == 1_000_000
        assert model_context_capacity("claude-opus-4-20250115") == 1_000_000

    def test_sonnet_200k(self):
        assert model_context_capacity("claude-sonnet-4-6") == 200_000

    def test_haiku_200k(self):
        assert model_context_capacity("claude-haiku-4-5") == 200_000

    def test_unknown_model_fallback(self):
        assert model_context_capacity("gpt-4o") == CONTEXT_WINDOW_CAPACITY

    def test_empty_string_fallback(self):
        assert model_context_capacity("") == CONTEXT_WINDOW_CAPACITY
