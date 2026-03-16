"""Tests for clorch.usage.parser."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from clorch.usage.parser import iter_today_jsonl_files, parse_session_usage


def _make_jsonl_entry(
    model: str = "claude-sonnet-4-6",
    input_tokens: int = 100,
    output_tokens: int = 50,
    cache_creation_input_tokens: int = 10,
    cache_read_input_tokens: int = 20,
    timestamp: str = "2026-03-02T12:00:00Z",
    role: str = "assistant",
) -> str:
    """Create a single JSONL line for an assistant message with usage."""
    entry = {
        "timestamp": timestamp,
        "message": {
            "role": role,
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
    """Create a temporary directory for JSONL files."""
    return tmp_path


class TestParseSessionUsage:
    def test_basic_parsing(self, tmp_jsonl_dir):
        path = tmp_jsonl_dir / "session-abc.jsonl"
        lines = [
            _make_jsonl_entry(input_tokens=100, output_tokens=50),
            _make_jsonl_entry(input_tokens=200, output_tokens=100),
        ]
        path.write_text("\n".join(lines) + "\n")

        usage, offset = parse_session_usage(path)
        assert usage is not None
        assert usage.session_id == "session-abc"
        assert usage.tokens.input_tokens == 300
        assert usage.tokens.output_tokens == 150
        assert usage.message_count == 2
        assert usage.model == "claude-sonnet-4-6"
        assert offset > 0

    def test_skips_non_assistant_messages(self, tmp_jsonl_dir):
        path = tmp_jsonl_dir / "session-xyz.jsonl"
        lines = [
            _make_jsonl_entry(role="user", input_tokens=999, output_tokens=999),
            _make_jsonl_entry(role="assistant", input_tokens=100, output_tokens=50),
        ]
        path.write_text("\n".join(lines) + "\n")

        usage, _ = parse_session_usage(path)
        assert usage is not None
        assert usage.tokens.input_tokens == 100
        assert usage.message_count == 1

    def test_timestamp_filtering(self, tmp_jsonl_dir):
        path = tmp_jsonl_dir / "session-ts.jsonl"
        since = datetime(2026, 3, 2, 12, 0, 0, tzinfo=timezone.utc)
        lines = [
            _make_jsonl_entry(timestamp="2026-03-02T11:00:00Z", input_tokens=100),  # before
            _make_jsonl_entry(timestamp="2026-03-02T13:00:00Z", input_tokens=200),  # after
        ]
        path.write_text("\n".join(lines) + "\n")

        usage, _ = parse_session_usage(path, since=since)
        assert usage is not None
        assert usage.tokens.input_tokens == 200
        assert usage.message_count == 1

    def test_byte_offset_incremental(self, tmp_jsonl_dir):
        path = tmp_jsonl_dir / "session-inc.jsonl"
        line1 = _make_jsonl_entry(input_tokens=100)
        path.write_text(line1 + "\n")

        # First parse: gets line 1
        usage1, offset1 = parse_session_usage(path)
        assert usage1 is not None
        assert usage1.tokens.input_tokens == 100

        # Append new data
        line2 = _make_jsonl_entry(input_tokens=200)
        with open(path, "a") as f:
            f.write(line2 + "\n")

        # Second parse from offset: only gets line 2
        usage2, offset2 = parse_session_usage(path, byte_offset=offset1)
        assert usage2 is not None
        assert usage2.tokens.input_tokens == 200
        assert offset2 > offset1

    def test_corrupted_lines_skipped(self, tmp_jsonl_dir):
        path = tmp_jsonl_dir / "session-bad.jsonl"
        lines = [
            "this is not json at all",
            '{"broken": json',
            _make_jsonl_entry(input_tokens=100),
        ]
        path.write_text("\n".join(lines) + "\n")

        usage, _ = parse_session_usage(path)
        assert usage is not None
        assert usage.tokens.input_tokens == 100
        assert usage.message_count == 1

    def test_missing_usage_field(self, tmp_jsonl_dir):
        path = tmp_jsonl_dir / "session-nousage.jsonl"
        entry = json.dumps({
            "timestamp": "2026-03-02T12:00:00Z",
            "message": {"role": "assistant", "model": "claude-sonnet-4-6"},
        })
        path.write_text(entry + "\n")

        usage, _ = parse_session_usage(path)
        assert usage is None

    def test_empty_file(self, tmp_jsonl_dir):
        path = tmp_jsonl_dir / "session-empty.jsonl"
        path.write_text("")

        usage, offset = parse_session_usage(path)
        assert usage is None

    def test_nonexistent_file(self, tmp_jsonl_dir):
        path = tmp_jsonl_dir / "nonexistent.jsonl"
        usage, offset = parse_session_usage(path)
        assert usage is None
        assert offset == 0

    def test_last_input_is_sum_of_last_message(self, tmp_jsonl_dir):
        """last_input = input + cache_creation + cache_read from last msg."""
        path = tmp_jsonl_dir / "session-lastinput.jsonl"
        lines = [
            _make_jsonl_entry(input_tokens=100, cache_creation_input_tokens=50,
                              cache_read_input_tokens=30),
            _make_jsonl_entry(input_tokens=200, cache_creation_input_tokens=80,
                              cache_read_input_tokens=60),
        ]
        path.write_text("\n".join(lines) + "\n")

        usage, _ = parse_session_usage(path)
        assert usage is not None
        # last_input should reflect only the last message: 200 + 80 + 60 = 340
        assert usage.tokens.last_input == 340

    def test_cache_tokens(self, tmp_jsonl_dir):
        path = tmp_jsonl_dir / "session-cache.jsonl"
        line = _make_jsonl_entry(
            cache_creation_input_tokens=500,
            cache_read_input_tokens=1000,
        )
        path.write_text(line + "\n")

        usage, _ = parse_session_usage(path)
        assert usage is not None
        assert usage.tokens.cache_creation_input_tokens == 500
        assert usage.tokens.cache_read_input_tokens == 1000


class TestIterTodayJsonlFiles:
    def test_with_mocked_dir(self, tmp_jsonl_dir, monkeypatch):
        """Test that iter_today_jsonl_files finds today-modified files."""
        import clorch.usage.parser as parser_mod

        # Create fake project structure
        project_dir = tmp_jsonl_dir / "projects" / "test-project"
        project_dir.mkdir(parents=True)
        jsonl_file = project_dir / "session.jsonl"
        jsonl_file.write_text("{}\n")

        monkeypatch.setattr(parser_mod, "CLAUDE_PROJECTS_DIR", tmp_jsonl_dir / "projects")

        files = iter_today_jsonl_files()
        assert len(files) == 1
        assert files[0] == jsonl_file
