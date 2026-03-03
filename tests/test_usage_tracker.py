"""Tests for clorch.usage.tracker."""
from __future__ import annotations

import json
import time
from unittest.mock import patch

import pytest

from clorch.usage.tracker import UsageTracker


def _make_jsonl_entry(
    model: str = "claude-sonnet-4-6",
    input_tokens: int = 100,
    output_tokens: int = 50,
    cache_creation_input_tokens: int = 10,
    cache_read_input_tokens: int = 20,
    timestamp: str | None = None,
) -> str:
    if timestamp is None:
        from datetime import datetime, timezone
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = {
        "timestamp": timestamp,
        "message": {
            "role": "assistant",
            "model": model,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_creation_input_tokens": cache_creation_input_tokens,
                "cache_read_input_tokens": cache_read_input_tokens,
            },
        },
    }
    return json.dumps(entry)


@pytest.fixture
def tmp_jsonl_dir(tmp_path):
    return tmp_path


@pytest.fixture(autouse=True)
def _no_real_jsonl(monkeypatch):
    """Prevent tracker from scanning real ~/.claude/projects/ in tests."""
    monkeypatch.setattr(
        "clorch.usage.tracker.iter_today_jsonl_files", lambda: [],
    )


class TestUsageTracker:
    def test_poll_with_active_sessions(self, tmp_jsonl_dir):
        path = tmp_jsonl_dir / "session-a.jsonl"
        path.write_text(_make_jsonl_entry(input_tokens=100, output_tokens=50) + "\n")

        tracker = UsageTracker()
        summary = tracker.poll(active_session_paths=[str(path)])

        assert summary.message_count == 1
        assert summary.total_output == 50
        assert summary.session_count == 1
        assert summary.total_cost > 0

    def test_incremental_polling(self, tmp_jsonl_dir):
        path = tmp_jsonl_dir / "session-b.jsonl"
        path.write_text(_make_jsonl_entry(input_tokens=100) + "\n")

        tracker = UsageTracker()
        s1 = tracker.poll(active_session_paths=[str(path)])
        assert s1.message_count == 1

        # Append more data
        with open(path, "a") as f:
            f.write(_make_jsonl_entry(input_tokens=200) + "\n")

        s2 = tracker.poll(active_session_paths=[str(path)])
        assert s2.message_count == 2
        # Total input should include both
        assert "session-b" in s2.sessions
        sess = s2.sessions["session-b"]
        assert sess.tokens.input_tokens == 300

    def test_cache_hit_rate(self, tmp_jsonl_dir):
        path = tmp_jsonl_dir / "session-c.jsonl"
        # 0 regular input, 0 cache write, 1000 cache read => 100% hit rate
        path.write_text(
            _make_jsonl_entry(
                input_tokens=0,
                cache_creation_input_tokens=0,
                cache_read_input_tokens=1000,
            )
            + "\n"
        )

        tracker = UsageTracker()
        summary = tracker.poll(active_session_paths=[str(path)])
        assert summary.cache_hit_rate == 100.0

    def test_cache_hit_rate_mixed(self, tmp_jsonl_dir):
        path = tmp_jsonl_dir / "session-d.jsonl"
        # 100 input + 100 cache write + 800 cache read = 1000 total, 80% cache
        path.write_text(
            _make_jsonl_entry(
                input_tokens=100,
                cache_creation_input_tokens=100,
                cache_read_input_tokens=800,
            )
            + "\n"
        )

        tracker = UsageTracker()
        summary = tracker.poll(active_session_paths=[str(path)])
        assert abs(summary.cache_hit_rate - 80.0) < 0.1

    def test_burn_rate_needs_time(self, tmp_jsonl_dir):
        path = tmp_jsonl_dir / "session-e.jsonl"
        path.write_text(_make_jsonl_entry() + "\n")

        tracker = UsageTracker()
        summary = tracker.poll(active_session_paths=[str(path)])
        # First poll — not enough data for burn rate
        assert summary.burn_rate == 0.0

    def test_burn_rate_with_elapsed_time(self, tmp_jsonl_dir):
        path = tmp_jsonl_dir / "session-f.jsonl"
        path.write_text(_make_jsonl_entry(input_tokens=100, output_tokens=50) + "\n")

        tracker = UsageTracker()

        # First poll at t=0
        with patch.object(time, "monotonic", return_value=1000.0):
            tracker.poll(active_session_paths=[str(path)])

        # Append more data and poll at t=60
        with open(path, "a") as f:
            f.write(_make_jsonl_entry(input_tokens=1000, output_tokens=500) + "\n")

        with patch.object(time, "monotonic", return_value=1060.0):
            s2 = tracker.poll(active_session_paths=[str(path)])

        # Burn rate should be positive now (60s elapsed, cost increased)
        assert s2.burn_rate > 0

    def test_poll_no_paths(self):
        tracker = UsageTracker()
        summary = tracker.poll()
        assert summary.total_cost == 0.0
        assert summary.session_count == 0

    def test_midnight_rollover(self, tmp_jsonl_dir):
        from datetime import date

        path = tmp_jsonl_dir / "session-g.jsonl"
        path.write_text(_make_jsonl_entry(input_tokens=100) + "\n")

        tracker = UsageTracker()
        tracker._current_date = date(2026, 3, 1)  # yesterday

        summary = tracker.poll(active_session_paths=[str(path)])

        # After midnight rollover, offsets are reset so full file is re-parsed
        assert summary.message_count == 1
