"""Tests for clorch.constants."""
from __future__ import annotations

from clorch.constants import GREEN, RED, YELLOW, context_pct_color


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
