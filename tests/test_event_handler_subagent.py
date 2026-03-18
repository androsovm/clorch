"""Tests for SubagentStart/SubagentStop handling in event_handler.sh.

Validates that subagent_count and subagents dict stay consistent,
especially when agent_id is empty.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

HANDLER = str(
    Path(__file__).resolve().parent.parent / "src" / "clorch" / "hooks" / "event_handler.sh"
)


def _run_event(state_dir: Path, session_id: str, event: str, payload: dict) -> dict:
    """Run event_handler.sh with given event and return the resulting state JSON."""
    payload["session_id"] = session_id
    result = subprocess.run(
        ["bash", HANDLER],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
            "CLORCH_STATE_DIR": str(state_dir),
            "CLORCH_EVENT": event,
            "HOME": str(Path.home()),
        },
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    state_file = state_dir / f"{session_id}.json"
    return json.loads(state_file.read_text())


@pytest.fixture
def state_dir(tmp_path):
    d = tmp_path / "state"
    d.mkdir()
    return d


def _seed_state(state_dir: Path, session_id: str, extra: dict | None = None) -> None:
    """Write an initial state file so the handler has something to update."""
    state = {
        "session_id": session_id,
        "status": "WORKING",
        "cwd": "/tmp/test",
        "project_name": "test",
        "last_event": "SessionStart",
        "last_event_time": "2026-03-17T10:00:00Z",
        "subagents": {},
    }
    if extra:
        state.update(extra)
    (state_dir / f"{session_id}.json").write_text(json.dumps(state))


class TestSubagentStart:
    def test_valid_agent_id_adds_to_dict(self, state_dir):
        _seed_state(state_dir, "s1")
        state = _run_event(state_dir, "s1", "SubagentStart", {
            "agent_id": "sub-abc",
            "agent_type": "Explore",
        })
        assert "sub-abc" in state["subagents"]
        assert state["subagents"]["sub-abc"]["status"] == "running"
        assert state["subagents"]["sub-abc"]["agent_type"] == "Explore"

    def test_empty_agent_id_leaves_dict_empty(self, state_dir):
        _seed_state(state_dir, "s1")
        state = _run_event(state_dir, "s1", "SubagentStart", {
            "agent_id": "",
            "agent_type": "unknown",
        })
        assert state["subagents"] == {}

    def test_invalid_agent_id_treated_as_empty(self, state_dir):
        _seed_state(state_dir, "s1")
        state = _run_event(state_dir, "s1", "SubagentStart", {
            "agent_id": "../../bad",
            "agent_type": "Explore",
        })
        assert state["subagents"] == {}

    def test_agent_id_with_spaces_treated_as_empty(self, state_dir):
        _seed_state(state_dir, "s1")
        state = _run_event(state_dir, "s1", "SubagentStart", {
            "agent_id": "has spaces",
            "agent_type": "Explore",
        })
        assert state["subagents"] == {}


class TestSubagentStop:
    def test_valid_agent_id_marks_completed(self, state_dir):
        _seed_state(state_dir, "s1", extra={
            "subagents": {
                "sub-abc": {
                    "agent_id": "sub-abc",
                    "agent_type": "Explore",
                    "status": "running",
                    "started_at": "2026-03-17T10:00:00Z",
                },
            },
        })
        state = _run_event(state_dir, "s1", "SubagentStop", {
            "agent_id": "sub-abc",
        })
        assert state["subagents"]["sub-abc"]["status"] == "completed"

    def test_empty_agent_id_leaves_dict_unchanged(self, state_dir):
        _seed_state(state_dir, "s1", extra={
            "subagents": {
                "sub-abc": {
                    "agent_id": "sub-abc",
                    "status": "running",
                },
            },
        })
        state = _run_event(state_dir, "s1", "SubagentStop", {
            "agent_id": "",
        })
        assert state["subagents"]["sub-abc"]["status"] == "running"

    def test_invalid_agent_id_treated_as_empty(self, state_dir):
        _seed_state(state_dir, "s1", extra={
            "subagents": {
                "sub-abc": {
                    "agent_id": "sub-abc",
                    "status": "running",
                },
            },
        })
        state = _run_event(state_dir, "s1", "SubagentStop", {
            "agent_id": "has spaces",
        })
        assert state["subagents"]["sub-abc"]["status"] == "running"
