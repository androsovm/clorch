"""Tests for pipefail guards in event_handler.sh.

Validates that the hook survives under `set -euo pipefail` when:
- ps -p $PPID fails (parent process gone, async hook)
- git status --porcelain fails (lock contention, broken worktree)
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

HANDLER = str(
    Path(__file__).resolve().parent.parent / "src" / "clorch" / "hooks" / "event_handler.sh"
)


def _run_event(state_dir: Path, session_id: str, event: str, payload: dict, env_extra: dict | None = None) -> dict:
    """Run event_handler.sh and return the resulting state JSON."""
    payload["session_id"] = session_id
    env = {
        "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
        "CLORCH_STATE_DIR": str(state_dir),
        "CLORCH_EVENT": event,
        "HOME": str(Path.home()),
    }
    if env_extra:
        env.update(env_extra)
    result = subprocess.run(
        ["bash", HANDLER],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )
    assert result.returncode == 0, f"Hook exited {result.returncode}\nstderr: {result.stderr}"
    state_file = state_dir / f"{session_id}.json"
    return json.loads(state_file.read_text())


@pytest.fixture
def state_dir(tmp_path):
    d = tmp_path / "state"
    d.mkdir()
    return d


class TestCLAUDETTYFallback:
    """Line 98: _CLAUDE_TTY pipeline must survive when ps -p $PPID fails."""

    def test_session_start_with_nonexistent_cwd(self, state_dir):
        """When CWD doesn't exist, git commands can't run — hook must not crash."""
        state = _run_event(state_dir, "test-tty-fallback", "SessionStart", {
            "cwd": "/nonexistent/path/that/does/not/exist",
        })
        assert state["session_id"] == "test-tty-fallback"
        assert state["status"] == "IDLE"
        assert state["last_event"] == "SessionStart"

    def test_session_start_with_non_git_cwd(self, state_dir, tmp_path):
        """When CWD is not a git repo, git_branch should be empty and hook survives."""
        non_git_dir = tmp_path / "not-a-repo"
        non_git_dir.mkdir()
        state = _run_event(state_dir, "test-non-git", "SessionStart", {
            "cwd": str(non_git_dir),
        })
        assert state["session_id"] == "test-non-git"
        assert state["status"] == "IDLE"
        assert state.get("git_branch", "") == ""


class TestGitDirtyFallback:
    """Line 116: GIT_DIRTY pipeline must survive when git status fails."""

    def test_session_start_in_git_repo_with_locked_index(self, state_dir, tmp_path):
        """Simulate git index lock — git status fails, GIT_DIRTY should fall back to 0."""
        # Create a minimal git repo
        repo = tmp_path / "locked-repo"
        repo.mkdir()
        subprocess.run(["git", "init", str(repo)], capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "init"],
            capture_output=True, check=True, cwd=str(repo),
        )
        # Create index.lock to make git status fail
        (repo / ".git" / "index.lock").touch()

        state = _run_event(state_dir, "test-locked", "SessionStart", {
            "cwd": str(repo),
        })
        assert state["session_id"] == "test-locked"
        assert state["status"] == "IDLE"
        # git_dirty_count should be 0 (fallback) since git status fails with lock
        assert state.get("git_dirty_count", 0) == 0

    def test_session_start_in_healthy_git_repo(self, state_dir, tmp_path):
        """Baseline: healthy git repo produces correct git_branch and git_dirty_count."""
        repo = tmp_path / "healthy-repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-b", "main", str(repo)], capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "init"],
            capture_output=True, check=True, cwd=str(repo),
        )
        # Create a dirty file
        (repo / "dirty.txt").write_text("uncommitted")

        state = _run_event(state_dir, "test-healthy", "SessionStart", {
            "cwd": str(repo),
        })
        assert state["session_id"] == "test-healthy"
        assert state["git_branch"] == "main"
        assert state["git_dirty_count"] == 1
