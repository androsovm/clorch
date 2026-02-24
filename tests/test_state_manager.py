"""Tests for StateManager."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest

from clorch.constants import AgentStatus
from clorch.state.manager import StateManager
from clorch.state.models import AgentState


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
