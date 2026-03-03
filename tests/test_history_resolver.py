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


@pytest.fixture
def projects_dir(tmp_path):
    """Create a temporary projects directory."""
    d = tmp_path / "projects"
    d.mkdir()
    return d


def _write_entries(path, entries):
    """Write JSONL entries to a file."""
    with path.open("w") as fh:
        for entry in entries:
            fh.write(json.dumps(entry) + "\n")


def test_resolve_returns_first_display(history_file, projects_dir):
    """First display per session wins."""
    _write_entries(history_file, [
        {"sessionId": "aaa", "display": "first prompt"},
        {"sessionId": "aaa", "display": "second prompt"},
    ])
    resolver = HistoryResolver(history_file, projects_dir)
    assert resolver.resolve("aaa") == "first prompt"


def test_unknown_session_returns_empty(history_file, projects_dir):
    """Unknown session IDs return empty string."""
    _write_entries(history_file, [
        {"sessionId": "aaa", "display": "hello"},
    ])
    resolver = HistoryResolver(history_file, projects_dir)
    assert resolver.resolve("unknown-id") == ""


def test_cache_refreshes_on_mtime_change(history_file, projects_dir):
    """Cache refreshes when file mtime changes."""
    _write_entries(history_file, [
        {"sessionId": "aaa", "display": "original"},
    ])
    resolver = HistoryResolver(history_file, projects_dir)
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
    resolver = HistoryResolver(
        tmp_path / "nonexistent.jsonl",
        tmp_path / "no-projects",
    )
    assert resolver.resolve("any-id") == ""


def test_malformed_lines_skipped(history_file, projects_dir):
    """Malformed JSON lines are skipped without breaking valid ones."""
    with history_file.open("w") as fh:
        fh.write('{"sessionId": "aaa", "display": "valid"}\n')
        fh.write("not json at all\n")
        fh.write('{"broken json\n')
        fh.write('{"sessionId": "bbb", "display": "also valid"}\n')
    resolver = HistoryResolver(history_file, projects_dir)
    assert resolver.resolve("aaa") == "valid"
    assert resolver.resolve("bbb") == "also valid"


def test_resolve_many(history_file, projects_dir):
    """resolve_many returns dict of known sessions."""
    _write_entries(history_file, [
        {"sessionId": "aaa", "display": "alpha"},
        {"sessionId": "bbb", "display": "beta"},
        {"sessionId": "ccc", "display": "gamma"},
    ])
    resolver = HistoryResolver(history_file, projects_dir)
    result = resolver.resolve_many({"aaa", "ccc", "unknown"})
    assert result == {"aaa": "alpha", "ccc": "gamma"}


def test_long_display_truncated(history_file, projects_dir):
    """Display values longer than 80 chars are truncated."""
    long_name = "x" * 120
    _write_entries(history_file, [
        {"sessionId": "aaa", "display": long_name},
    ])
    resolver = HistoryResolver(history_file, projects_dir)
    assert len(resolver.resolve("aaa")) == 80


# -- Custom title tests (/rename) --


def test_custom_title_overrides_display(history_file, projects_dir):
    """/rename custom title takes priority over history display."""
    _write_entries(history_file, [
        {"sessionId": "aaa", "display": "initial prompt"},
    ])
    # Create a transcript with a custom-title entry
    proj = projects_dir / "my-project"
    proj.mkdir()
    _write_entries(proj / "aaa.jsonl", [
        {"type": "user", "sessionId": "aaa", "message": "hello"},
        {"type": "custom-title", "customTitle": "my renamed session", "sessionId": "aaa"},
    ])
    resolver = HistoryResolver(history_file, projects_dir)
    assert resolver.resolve("aaa") == "my renamed session"


def test_custom_title_in_resolve_many(history_file, projects_dir):
    """resolve_many prefers custom titles."""
    _write_entries(history_file, [
        {"sessionId": "aaa", "display": "prompt a"},
        {"sessionId": "bbb", "display": "prompt b"},
    ])
    proj = projects_dir / "proj"
    proj.mkdir()
    _write_entries(proj / "aaa.jsonl", [
        {"type": "custom-title", "customTitle": "renamed a", "sessionId": "aaa"},
    ])
    resolver = HistoryResolver(history_file, projects_dir)
    result = resolver.resolve_many({"aaa", "bbb"})
    assert result == {"aaa": "renamed a", "bbb": "prompt b"}


def test_custom_title_missing_projects_dir(history_file, tmp_path):
    """Missing projects dir falls back to history display."""
    _write_entries(history_file, [
        {"sessionId": "aaa", "display": "fallback"},
    ])
    resolver = HistoryResolver(history_file, tmp_path / "no-such-dir")
    assert resolver.resolve("aaa") == "fallback"


def test_custom_title_cache_refreshes(history_file, projects_dir):
    """Custom title cache updates when transcript file changes."""
    _write_entries(history_file, [
        {"sessionId": "aaa", "display": "original prompt"},
    ])
    proj = projects_dir / "proj"
    proj.mkdir()
    transcript = proj / "aaa.jsonl"

    # No custom title yet
    _write_entries(transcript, [
        {"type": "user", "sessionId": "aaa", "message": "hello"},
    ])
    resolver = HistoryResolver(history_file, projects_dir)
    assert resolver.resolve("aaa") == "original prompt"

    # Now add a custom title
    _write_entries(transcript, [
        {"type": "user", "sessionId": "aaa", "message": "hello"},
        {"type": "custom-title", "customTitle": "new name", "sessionId": "aaa"},
    ])
    assert resolver.resolve("aaa") == "new name"
