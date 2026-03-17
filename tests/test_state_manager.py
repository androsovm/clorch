"""Tests for StateManager."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from clorch.constants import AgentStatus
from clorch.state.manager import StateManager

# ------------------------------------------------------------------
# scan()
# ------------------------------------------------------------------


class TestStateManagerScan:
    """Tests for StateManager.scan()."""

    def test_scan_empty_dir(self, tmp_state_dir):
        """Empty directory returns an empty list."""
        mgr = StateManager(state_dir=tmp_state_dir)
        assert mgr.scan() == []

    def test_scan_single_agent(self, tmp_state_dir, make_agent_state):
        """A single JSON file is scanned into one AgentState."""
        make_agent_state(session_id="agent-1", project_name="alpha")

        mgr = StateManager(state_dir=tmp_state_dir)
        agents = mgr.scan()

        assert len(agents) == 1
        assert agents[0].session_id == "agent-1"
        assert agents[0].project_name == "alpha"

    def test_scan_multiple_agents(self, tmp_state_dir, make_agent_state):
        """Multiple files are returned sorted by project name (case-insensitive)."""
        make_agent_state(session_id="s1", project_name="Zeta")
        make_agent_state(session_id="s2", project_name="alpha")
        make_agent_state(session_id="s3", project_name="Beta")

        mgr = StateManager(state_dir=tmp_state_dir)
        agents = mgr.scan()

        assert len(agents) == 3
        names = [a.project_name for a in agents]
        assert names == ["alpha", "Beta", "Zeta"]

    def test_scan_corrupt_file(self, tmp_state_dir, make_agent_state, caplog):
        """A corrupt JSON file is skipped with a warning, valid files still returned."""
        make_agent_state(session_id="good", project_name="ok-project")
        corrupt = tmp_state_dir / "bad.json"
        corrupt.write_text("{this is not valid json!!!")

        mgr = StateManager(state_dir=tmp_state_dir)
        with caplog.at_level(logging.WARNING):
            agents = mgr.scan()

        assert len(agents) == 1
        assert agents[0].session_id == "good"
        assert any("Skipping corrupt state file" in r.message for r in caplog.records)


# ------------------------------------------------------------------
# get_agent()
# ------------------------------------------------------------------


class TestStateManagerGetAgent:
    """Tests for StateManager.get_agent()."""

    def test_get_agent_found(self, tmp_state_dir, make_agent_state):
        """Existing session_id returns the matching AgentState."""
        make_agent_state(session_id="found-me", project_name="proj-x")

        mgr = StateManager(state_dir=tmp_state_dir)
        agent = mgr.get_agent("found-me")

        assert agent is not None
        assert agent.session_id == "found-me"
        assert agent.project_name == "proj-x"

    def test_get_agent_not_found(self, tmp_state_dir):
        """Missing session_id returns None."""
        mgr = StateManager(state_dir=tmp_state_dir)
        assert mgr.get_agent("does-not-exist") is None


# ------------------------------------------------------------------
# remove_session()
# ------------------------------------------------------------------


class TestStateManagerRemoveSession:
    """Tests for StateManager.remove_session()."""

    def test_removes_existing_file(self, tmp_state_dir, make_agent_state):
        """Returns True and deletes the file when it exists."""
        make_agent_state(session_id="to-remove")
        mgr = StateManager(state_dir=tmp_state_dir)

        result = mgr.remove_session("to-remove")

        assert result is True
        assert not (tmp_state_dir / "to-remove.json").exists()

    def test_returns_false_when_missing(self, tmp_state_dir):
        """Returns False (no error) when the file does not exist."""
        mgr = StateManager(state_dir=tmp_state_dir)
        assert mgr.remove_session("nonexistent") is False

    def test_rejects_invalid_session_id(self, tmp_state_dir, make_agent_state):
        """Rejects session IDs that fail the regex — prevents path traversal."""
        make_agent_state(session_id="victim")
        mgr = StateManager(state_dir=tmp_state_dir)

        result = mgr.remove_session("../victim")

        assert result is False
        assert (tmp_state_dir / "victim.json").exists()

    def test_does_not_affect_other_sessions(self, tmp_state_dir, make_agent_state):
        """Removing one session leaves others intact."""
        make_agent_state(session_id="keep-me")
        make_agent_state(session_id="delete-me")
        mgr = StateManager(state_dir=tmp_state_dir)

        mgr.remove_session("delete-me")

        assert (tmp_state_dir / "keep-me.json").exists()


# ------------------------------------------------------------------
# get_summary()
# ------------------------------------------------------------------


class TestStateManagerGetSummary:
    """Tests for StateManager.get_summary()."""

    def test_get_summary(self, tmp_state_dir, make_agent_state):
        """Aggregate counts are computed correctly from scanned agents."""
        make_agent_state(session_id="w1", status="WORKING")
        make_agent_state(session_id="w2", status="WORKING")
        make_agent_state(session_id="i1", status="IDLE")
        make_agent_state(session_id="e1", status="ERROR")

        mgr = StateManager(state_dir=tmp_state_dir)
        summary = mgr.get_summary()

        assert summary.working == 2
        assert summary.idle == 1
        assert summary.error == 1
        assert summary.total == 4


# ------------------------------------------------------------------
# get_attention_agents()
# ------------------------------------------------------------------


class TestStateManagerAttention:
    """Tests for StateManager.get_attention_agents()."""

    def test_get_attention_agents(self, tmp_state_dir, make_agent_state):
        """Only WAITING_PERMISSION, WAITING_ANSWER, and ERROR agents are returned."""
        make_agent_state(session_id="work", status="WORKING", project_name="a")
        make_agent_state(session_id="idle", status="IDLE", project_name="b")
        make_agent_state(session_id="perm", status="WAITING_PERMISSION", project_name="c")
        make_agent_state(session_id="ask", status="WAITING_ANSWER", project_name="d")
        make_agent_state(session_id="err", status="ERROR", project_name="e")

        mgr = StateManager(state_dir=tmp_state_dir)
        attention = mgr.get_attention_agents()

        ids = {a.session_id for a in attention}
        assert ids == {"perm", "ask", "err"}
        # WORKING and IDLE should NOT appear.
        assert "work" not in ids
        assert "idle" not in ids


# ------------------------------------------------------------------
# cleanup_stale()
# ------------------------------------------------------------------


class TestStateManagerVerifyStatus:
    """Tests for StateManager.verify_status()."""

    def test_verify_status_match(self, tmp_state_dir, make_agent_state):
        """Returns True when agent status matches expected."""
        make_agent_state(session_id="s1", status="WAITING_PERMISSION")
        mgr = StateManager(state_dir=tmp_state_dir)
        assert mgr.verify_status("s1", AgentStatus.WAITING_PERMISSION) is True

    def test_verify_status_changed(self, tmp_state_dir, make_agent_state):
        """Returns False when agent status has changed."""
        make_agent_state(session_id="s1", status="WORKING")
        mgr = StateManager(state_dir=tmp_state_dir)
        assert mgr.verify_status("s1", AgentStatus.WAITING_PERMISSION) is False

    def test_verify_status_missing(self, tmp_state_dir):
        """Returns False when agent does not exist."""
        mgr = StateManager(state_dir=tmp_state_dir)
        assert mgr.verify_status("nonexistent", AgentStatus.WORKING) is False


class TestStateManagerCleanup:
    """Tests for StateManager.cleanup_stale()."""

    def test_cleanup_stale(self, tmp_state_dir, make_agent_state):
        """Stale files are removed, fresh ones are kept."""
        # "fresh" agent: last_event_time is right now.
        now = datetime.now(timezone.utc)
        fresh_time = now.isoformat().replace("+00:00", "Z")
        make_agent_state(
            session_id="fresh",
            last_event_time=fresh_time,
            project_name="a",
        )

        # "stale" agent: last_event_time is 2 hours ago.
        stale_time = (now - timedelta(hours=2)).isoformat().replace("+00:00", "Z")
        make_agent_state(
            session_id="stale",
            last_event_time=stale_time,
            project_name="b",
        )

        mgr = StateManager(state_dir=tmp_state_dir)
        removed = mgr.cleanup_stale(max_age_seconds=3600)

        assert removed == 1
        # The fresh file should still exist.
        assert (tmp_state_dir / "fresh.json").exists()
        # The stale file should be gone.
        assert not (tmp_state_dir / "stale.json").exists()


# ------------------------------------------------------------------
# reset_stale_permissions()
# ------------------------------------------------------------------


class TestResetStalePermissions:
    """Tests for StateManager.reset_stale_permissions()."""

    def test_no_reset_when_process_alive(self, tmp_state_dir, make_agent_state):
        """WAITING_PERMISSION is NOT reset when PID is alive — permission is legitimately pending."""
        import os

        path = make_agent_state(
            session_id="alive-perm",
            status="WAITING_PERMISSION",
            pid=os.getpid(),  # current process — guaranteed alive
        )
        # Backdate mtime so file_age > ttl
        old_mtime = path.stat().st_mtime - 120
        os.utime(path, (old_mtime, old_mtime))

        mgr = StateManager(state_dir=tmp_state_dir)
        mgr.reset_stale_permissions(ttl_seconds=30)

        agent = mgr.get_agent("alive-perm")
        assert agent is not None
        assert agent.status == AgentStatus.WAITING_PERMISSION

    def test_reset_when_process_dead(self, tmp_state_dir, make_agent_state):
        """WAITING_PERMISSION is reset to IDLE when PID is dead."""
        import os

        path = make_agent_state(
            session_id="dead-perm",
            status="WAITING_PERMISSION",
            pid=99999999,  # almost certainly not a real PID
        )
        old_mtime = path.stat().st_mtime - 120
        os.utime(path, (old_mtime, old_mtime))

        mgr = StateManager(state_dir=tmp_state_dir)
        # Mock kill to raise ProcessLookupError (dead process)
        with patch("os.kill", side_effect=ProcessLookupError):
            mgr.reset_stale_permissions(ttl_seconds=30)

        agent = mgr.get_agent("dead-perm")
        assert agent is not None
        assert agent.status == AgentStatus.IDLE

    def test_no_reset_when_file_is_fresh(self, tmp_state_dir, make_agent_state):
        """WAITING_PERMISSION is NOT reset when file age < ttl, even without PID."""
        make_agent_state(
            session_id="fresh-perm",
            status="WAITING_PERMISSION",
        )
        # File was just created — mtime is fresh

        mgr = StateManager(state_dir=tmp_state_dir)
        mgr.reset_stale_permissions(ttl_seconds=30)

        agent = mgr.get_agent("fresh-perm")
        assert agent is not None
        assert agent.status == AgentStatus.WAITING_PERMISSION

    def test_reset_when_no_pid_and_stale(self, tmp_state_dir, make_agent_state):
        """WAITING_PERMISSION without PID is reset after ttl (fallback behavior)."""
        import os

        path = make_agent_state(
            session_id="no-pid-perm",
            status="WAITING_PERMISSION",
            pid=None,
        )
        old_mtime = path.stat().st_mtime - 120
        os.utime(path, (old_mtime, old_mtime))

        mgr = StateManager(state_dir=tmp_state_dir)
        mgr.reset_stale_permissions(ttl_seconds=30)

        agent = mgr.get_agent("no-pid-perm")
        assert agent is not None
        assert agent.status == AgentStatus.IDLE

    def test_working_status_not_affected(self, tmp_state_dir, make_agent_state):
        """Only WAITING_PERMISSION is reset, other statuses are untouched."""
        import os

        path = make_agent_state(
            session_id="working-agent",
            status="WORKING",
            pid=None,
        )
        old_mtime = path.stat().st_mtime - 120
        os.utime(path, (old_mtime, old_mtime))

        mgr = StateManager(state_dir=tmp_state_dir)
        mgr.reset_stale_permissions(ttl_seconds=30)

        agent = mgr.get_agent("working-agent")
        assert agent is not None
        assert agent.status == AgentStatus.WORKING
