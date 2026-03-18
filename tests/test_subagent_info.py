"""Tests for SubAgentInfo and sub-agent tracking on AgentState."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from clorch.state.models import SUBAGENT_RETENTION_SECONDS, AgentState, SubAgentInfo


class TestSubAgentInfoConstruction:
    def test_defaults(self):
        si = SubAgentInfo(agent_id="abc-123")
        assert si.agent_id == "abc-123"
        assert si.agent_type == ""
        assert si.status == "running"
        assert si.started_at == ""
        assert si.completed_at == ""
        assert si.last_message == ""
        assert si.transcript_path == ""

    def test_full_construction(self):
        si = SubAgentInfo(
            agent_id="abc",
            agent_type="Explore",
            status="completed",
            started_at="2026-03-16T10:00:00Z",
            completed_at="2026-03-16T10:00:30Z",
            last_message="Found 3 files",
            transcript_path="/tmp/transcript.jsonl",
        )
        assert si.agent_type == "Explore"
        assert si.status == "completed"
        assert si.last_message == "Found 3 files"


class TestSubAgentInfoDuration:
    def test_duration_no_started_at(self):
        si = SubAgentInfo(agent_id="x")
        assert si.duration == "0s"

    def test_duration_completed(self):
        si = SubAgentInfo(
            agent_id="x",
            started_at="2026-03-16T10:00:00Z",
            completed_at="2026-03-16T10:00:45Z",
            status="completed",
        )
        assert si.duration == "45s"

    def test_duration_over_minute(self):
        si = SubAgentInfo(
            agent_id="x",
            started_at="2026-03-16T10:00:00Z",
            completed_at="2026-03-16T10:02:15Z",
            status="completed",
        )
        assert si.duration == "2m 15s"

    def test_duration_running_uses_now(self):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        si = SubAgentInfo(agent_id="x", status="running", started_at=now)
        # Running sub-agent just started — duration should be 0s or 1s
        assert si.duration in ("0s", "1s")

    def test_duration_negative_clamped_to_zero(self):
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        si = SubAgentInfo(
            agent_id="x",
            status="running",
            started_at=future,
        )
        # started_at in the future → negative delta clamped to 0
        assert si.duration == "0s"

    def test_duration_invalid_timestamp(self):
        si = SubAgentInfo(agent_id="x", started_at="not-a-date")
        assert si.duration == "?"


class TestAgentStateSubagentsParsing:
    def test_from_json_with_subagents(self, make_agent_state):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        path = make_agent_state(
            session_id="s1",
            subagents={
                "agent-1": {
                    "agent_id": "agent-1",
                    "agent_type": "Explore",
                    "status": "running",
                    "started_at": now,
                },
                "agent-2": {
                    "agent_id": "agent-2",
                    "agent_type": "Plan",
                    "status": "completed",
                    "started_at": now,
                    "completed_at": now,
                    "last_message": "Done",
                },
            },
        )
        agent = AgentState.from_json_file(path)
        assert len(agent.subagents) == 2
        assert agent.subagent_count == 1  # only 1 running sub-agent

    def test_from_json_no_subagents_backward_compat(self, make_agent_state):
        path = make_agent_state(session_id="s2")
        agent = AgentState.from_json_file(path)
        assert agent.subagents == []
        assert agent.subagent_count == 0

    def test_pruning_old_completed(self, make_agent_state):
        now = datetime.now(timezone.utc)
        old_time = (now - timedelta(seconds=SUBAGENT_RETENTION_SECONDS + 60)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        recent_time = (now - timedelta(seconds=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
        current_time = now.strftime("%Y-%m-%dT%H:%M:%SZ")

        path = make_agent_state(
            session_id="s3",
            subagents={
                "old": {
                    "agent_id": "old",
                    "agent_type": "Explore",
                    "status": "completed",
                    "started_at": old_time,
                    "completed_at": old_time,
                },
                "recent": {
                    "agent_id": "recent",
                    "agent_type": "Plan",
                    "status": "completed",
                    "started_at": recent_time,
                    "completed_at": recent_time,
                },
                "running": {
                    "agent_id": "running",
                    "agent_type": "Explore",
                    "status": "running",
                    "started_at": current_time,
                },
            },
        )
        agent = AgentState.from_json_file(path)
        ids = {s.agent_id for s in agent.subagents}
        assert "old" not in ids
        assert "recent" in ids
        assert "running" in ids

    def test_empty_subagents_dict(self, make_agent_state):
        path = make_agent_state(session_id="s4", subagents={})
        agent = AgentState.from_json_file(path)
        assert agent.subagents == []

    def test_non_dict_subagent_value_skipped(self, make_agent_state):
        path = make_agent_state(
            session_id="s5",
            subagents={
                "bad": "not-a-dict",
                "good": {
                    "agent_id": "good",
                    "agent_type": "Explore",
                    "status": "running",
                    "started_at": "2026-03-16T10:00:00Z",
                },
            },
        )
        agent = AgentState.from_json_file(path)
        assert len(agent.subagents) == 1
        assert agent.subagents[0].agent_id == "good"

    def test_completed_with_invalid_timestamp_not_pruned(self, make_agent_state):
        path = make_agent_state(
            session_id="s6",
            subagents={
                "bad-ts": {
                    "agent_id": "bad-ts",
                    "agent_type": "Plan",
                    "status": "completed",
                    "started_at": "2026-03-16T10:00:00Z",
                    "completed_at": "not-a-date",
                },
            },
        )
        agent = AgentState.from_json_file(path)
        # Invalid completed_at → can't parse → not pruned, kept
        assert len(agent.subagents) == 1
        assert agent.subagents[0].agent_id == "bad-ts"


class TestAgentStateSubagentProperties:
    def test_running_subagents(self):
        agent = AgentState(
            session_id="x",
            subagents=[
                SubAgentInfo(agent_id="a", status="running"),
                SubAgentInfo(agent_id="b", status="completed"),
                SubAgentInfo(agent_id="c", status="running"),
            ],
        )
        running = agent.running_subagents
        assert len(running) == 2
        assert {s.agent_id for s in running} == {"a", "c"}

    def test_completed_subagents(self):
        agent = AgentState(
            session_id="x",
            subagents=[
                SubAgentInfo(agent_id="a", status="running"),
                SubAgentInfo(agent_id="b", status="completed"),
            ],
        )
        assert len(agent.completed_subagents) == 1
        assert agent.completed_subagents[0].agent_id == "b"

