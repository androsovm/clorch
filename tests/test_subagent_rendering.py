"""Tests for sub-agent rendering in TUI widgets.

Tests the sub-agent display logic via AgentState.visible_subagents()
(domain method) and the simplified session list suffix format.
"""

from __future__ import annotations

from clorch.state.models import AgentState, SubAgentInfo


class TestSessionListSubagentSuffix:
    """Test the sub-agent suffix in SessionRow project column."""

    def test_simple_count_suffix(self):
        agent = AgentState(
            session_id="x",
            project_name="myproj",
            subagents=[
                SubAgentInfo(agent_id="a", status="running"),
                SubAgentInfo(agent_id="b", status="running"),
                SubAgentInfo(agent_id="c", status="running"),
            ],
        )
        # Session list now uses simple [Ns] format
        project = agent.project_name
        if agent.subagent_count > 0:
            project = f"{project} [{agent.subagent_count}s]"
        assert project == "myproj [3s]"

    def test_zero_subagents_no_suffix(self):
        agent = AgentState(
            session_id="x",
            project_name="myproj",
        )
        project = agent.project_name
        if agent.subagent_count > 0:
            project = f"{project} [{agent.subagent_count}s]"
        assert project == "myproj"


class TestVisibleSubagents:
    """Test AgentState.visible_subagents() — the domain method used by telemetry panel."""

    def test_running_subagents_first(self):
        agent = AgentState(
            session_id="x",
            subagents=[
                SubAgentInfo(agent_id="c", agent_type="Plan", status="completed",
                             started_at="2026-03-16T10:00:00Z",
                             completed_at="2026-03-16T10:00:30Z"),
                SubAgentInfo(agent_id="r", agent_type="Explore", status="running",
                             started_at="2026-03-16T10:00:00Z"),
            ],
        )
        visible = agent.visible_subagents()
        assert visible[0].status == "running"
        assert visible[1].status == "completed"

    def test_cap_at_limit(self):
        subs = [
            SubAgentInfo(agent_id=f"r{i}", agent_type="Explore", status="running",
                         started_at="2026-03-16T10:00:00Z")
            for i in range(7)
        ]
        subs.append(
            SubAgentInfo(agent_id="c1", agent_type="Plan", status="completed",
                         started_at="2026-03-16T10:00:00Z",
                         completed_at="2026-03-16T10:00:30Z"),
        )
        agent = AgentState(session_id="x", subagents=subs)
        visible = agent.visible_subagents(limit=6)
        assert len(visible) == 6
        assert all(s.status == "running" for s in visible)

    def test_completed_fill_remaining_slots(self):
        agent = AgentState(
            session_id="x",
            subagents=[
                SubAgentInfo(agent_id="r1", agent_type="Explore", status="running",
                             started_at="2026-03-16T10:00:00Z"),
                SubAgentInfo(agent_id="c1", agent_type="Plan", status="completed",
                             started_at="2026-03-16T10:00:00Z",
                             completed_at="2026-03-16T10:00:30Z"),
                SubAgentInfo(agent_id="c2", agent_type="Review", status="completed",
                             started_at="2026-03-16T10:00:00Z",
                             completed_at="2026-03-16T10:01:00Z"),
            ],
        )
        visible = agent.visible_subagents(limit=3)
        assert len(visible) == 3
        assert visible[0].agent_id == "r1"
        assert visible[1].agent_id == "c1"
        assert visible[2].agent_id == "c2"

    def test_empty_subagents(self):
        agent = AgentState(session_id="x")
        assert agent.visible_subagents() == []

    def test_custom_limit(self):
        subs = [
            SubAgentInfo(agent_id=f"r{i}", agent_type="Explore", status="running",
                         started_at="2026-03-16T10:00:00Z")
            for i in range(5)
        ]
        agent = AgentState(session_id="x", subagents=subs)
        assert len(agent.visible_subagents(limit=2)) == 2
        assert len(agent.visible_subagents(limit=10)) == 5

    def test_only_completed(self):
        agent = AgentState(
            session_id="x",
            subagents=[
                SubAgentInfo(agent_id="c1", agent_type="Plan", status="completed",
                             started_at="2026-03-16T10:00:00Z",
                             completed_at="2026-03-16T10:00:30Z"),
                SubAgentInfo(agent_id="c2", agent_type="Review", status="completed",
                             started_at="2026-03-16T10:00:00Z",
                             completed_at="2026-03-16T10:01:00Z"),
            ],
        )
        visible = agent.visible_subagents(limit=6)
        assert len(visible) == 2
        assert all(s.status == "completed" for s in visible)

    def test_unknown_type_preserved(self):
        agent = AgentState(
            session_id="x",
            subagents=[
                SubAgentInfo(agent_id="a", agent_type="", status="running",
                             started_at="2026-03-16T10:00:00Z"),
            ],
        )
        visible = agent.visible_subagents()
        assert len(visible) == 1
        assert visible[0].agent_type == ""
