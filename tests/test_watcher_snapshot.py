"""Tests for StateWatcher._build_snapshot fingerprint change detection."""

from __future__ import annotations

from clorch.constants import AgentStatus
from clorch.state.models import AgentState, SubAgentInfo
from clorch.state.watcher import StateWatcher


def _make_agent(
    session_id: str = "sess-1",
    status: AgentStatus = AgentStatus.WORKING,
    subagents: list[SubAgentInfo] | None = None,
) -> AgentState:
    return AgentState(
        session_id=session_id,
        status=status,
        last_event_time="2026-03-17T10:00:00Z",
        tool_count=5,
        error_count=0,
        notification_message=None,
        compact_count=0,
        task_completed_count=0,
        subagents=subagents or [],
    )


class TestBuildSnapshot:
    """Verify _build_snapshot detects all meaningful state changes."""

    def test_snapshot_changes_when_subagent_completes(self):
        """Fingerprint must change when a subagent moves from running to completed."""
        sub = SubAgentInfo(agent_id="sub-1", status="running")
        agent_a = _make_agent(subagents=[sub, SubAgentInfo(agent_id="sub-2", status="running")])
        snap_a = StateWatcher._build_snapshot([agent_a])

        # Mark one subagent as completed — total count unchanged, running count changes
        agent_b = _make_agent(
            subagents=[
                SubAgentInfo(agent_id="sub-1", status="completed"),
                SubAgentInfo(agent_id="sub-2", status="running"),
            ]
        )
        snap_b = StateWatcher._build_snapshot([agent_b])

        assert snap_a != snap_b

    def test_snapshot_changes_when_subagent_added(self):
        """Fingerprint must change when a new subagent appears."""
        agent_a = _make_agent(subagents=[])
        snap_a = StateWatcher._build_snapshot([agent_a])

        agent_b = _make_agent(
            subagents=[SubAgentInfo(agent_id="sub-1", status="running")]
        )
        snap_b = StateWatcher._build_snapshot([agent_b])

        assert snap_a != snap_b

    def test_snapshot_unchanged_when_nothing_changes(self):
        """Identical agent state produces identical fingerprints."""
        agent1 = _make_agent(
            subagents=[SubAgentInfo(agent_id="sub-1", status="running")]
        )
        agent2 = _make_agent(
            subagents=[SubAgentInfo(agent_id="sub-1", status="running")]
        )
        snap1 = StateWatcher._build_snapshot([agent1])
        snap2 = StateWatcher._build_snapshot([agent2])

        assert snap1 == snap2
