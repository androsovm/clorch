"""Tests for HistoryResolver."""

from __future__ import annotations

import json

import pytest

from clorch.state.history import HistoryResolver


@pytest.fixture
def history_file(tmp_path):
    """Create a temporary history.jsonl file."""
    path = tmp_path / "history.jsonl"
    return path


def _write_entries(path, entries):
    """Write JSONL entries to a file."""
    with path.open("w") as fh:
        for entry in entries:
            fh.write(json.dumps(entry) + "\n")


def test_resolve_returns_first_display(history_file):
    """First display per session wins."""
    _write_entries(history_file, [
        {"sessionId": "aaa", "display": "first prompt"},
        {"sessionId": "aaa", "display": "second prompt"},
    ])
    resolver = HistoryResolver(history_file)
    assert resolver.resolve("aaa") == "first prompt"


def test_unknown_session_returns_empty(history_file):
    """Unknown session IDs return empty string."""
    _write_entries(history_file, [
        {"sessionId": "aaa", "display": "hello"},
    ])
    resolver = HistoryResolver(history_file)
    assert resolver.resolve("unknown-id") == ""


def test_cache_refreshes_on_mtime_change(history_file):
    """Cache refreshes when file mtime changes."""
    _write_entries(history_file, [
        {"sessionId": "aaa", "display": "original"},
    ])
    resolver = HistoryResolver(history_file)
    assert resolver.resolve("aaa") == "original"
    assert resolver.resolve("bbb") == ""

    # Overwrite with new content
    _write_entries(history_file, [
        {"sessionId": "aaa", "display": "original"},
        {"sessionId": "bbb", "display": "new session"},
    ])
    assert resolver.resolve("bbb") == "new session"


def test_missing_file_handled_gracefully(tmp_path):
    """Missing history file returns empty without errors."""
    resolver = HistoryResolver(tmp_path / "nonexistent.jsonl")
    assert resolver.resolve("any-id") == ""


def test_malformed_lines_skipped(history_file):
    """Malformed JSON lines are skipped without breaking valid ones."""
    with history_file.open("w") as fh:
        fh.write('{"sessionId": "aaa", "display": "valid"}\n')
        fh.write("not json at all\n")
        fh.write('{"broken json\n')
        fh.write('{"sessionId": "bbb", "display": "also valid"}\n')
    resolver = HistoryResolver(history_file)
    assert resolver.resolve("aaa") == "valid"
    assert resolver.resolve("bbb") == "also valid"


def test_resolve_many(history_file):
    """resolve_many returns dict of known sessions."""
    _write_entries(history_file, [
        {"sessionId": "aaa", "display": "alpha"},
        {"sessionId": "bbb", "display": "beta"},
        {"sessionId": "ccc", "display": "gamma"},
    ])
    resolver = HistoryResolver(history_file)
    result = resolver.resolve_many({"aaa", "ccc", "unknown"})
    assert result == {"aaa": "alpha", "ccc": "gamma"}


def test_long_display_truncated(history_file):
    """Display values longer than 80 chars are truncated."""
    long_name = "x" * 120
    _write_entries(history_file, [
        {"sessionId": "aaa", "display": long_name},
    ])
    resolver = HistoryResolver(history_file)
    assert len(resolver.resolve("aaa")) == 80
