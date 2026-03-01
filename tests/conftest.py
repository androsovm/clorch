"""Shared fixtures for clorch tests."""
from __future__ import annotations

import json
import pytest
from pathlib import Path


@pytest.fixture
def tmp_state_dir(tmp_path):
    """Create a temporary state directory."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    return state_dir


@pytest.fixture
def make_agent_state(tmp_state_dir):
    """Factory fixture to create agent state JSON files."""
    def _make(
        session_id: str = "test-session",
        status: str = "WORKING",
        cwd: str = "/home/user/project",
        project_name: str = "test-project",
        model: str = "claude-opus-4-6",
        last_event: str = "PostToolUse",
        last_tool: str = "Edit",
        tool_count: int = 10,
        error_count: int = 0,
        subagent_count: int = 0,
        compact_count: int = 0,
        last_compact_time: str = "",
        task_completed_count: int = 0,
        started_at: str = "2026-02-22T10:00:00Z",
        last_event_time: str = "2026-02-22T10:30:00Z",
        notification_message: str | None = None,
        activity_history: list[int] | None = None,
        tool_request_summary: str | None = None,
        pid: int | None = None,
    ) -> Path:
        if activity_history is None:
            activity_history = [0, 1, 2, 3, 2, 1, 0, 3, 2, 1]
        state = {
            "session_id": session_id,
            "status": status,
            "cwd": cwd,
            "project_name": project_name,
            "model": model,
            "last_event": last_event,
            "last_event_time": last_event_time,
            "last_tool": last_tool,
            "tool_count": tool_count,
            "error_count": error_count,
            "subagent_count": subagent_count,
            "compact_count": compact_count,
            "last_compact_time": last_compact_time,
            "task_completed_count": task_completed_count,
            "started_at": started_at,
            "notification_message": notification_message,
            "activity_history": activity_history,
            "tool_request_summary": tool_request_summary,
            "pid": pid,
        }
        path = tmp_state_dir / f"{session_id}.json"
        path.write_text(json.dumps(state))
        return path
    return _make
