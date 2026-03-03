"""Tests for AgentState and StatusSummary models."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest

from clorch.constants import AgentStatus
from clorch.state.models import AgentState, StatusSummary, ActionItem, build_action_queue


# ------------------------------------------------------------------
# AgentState.from_json_file
# ------------------------------------------------------------------


class TestAgentStateFromJsonFile:
    """Tests for loading AgentState from JSON files."""

    def test_agent_state_from_json_file(self, make_agent_state):
        """Load a valid JSON file and verify all fields are populated."""
        path = make_agent_state(
            session_id="sess-1",
            status="WORKING",
            cwd="/home/user/project",
            project_name="my-project",
            model="claude-opus-4-6",
            last_event="PostToolUse",
            last_tool="Edit",
            tool_count=42,
            error_count=3,
            started_at="2026-02-22T10:00:00Z",
            last_event_time="2026-02-22T10:30:00Z",
            notification_message="Build passed",
            activity_history=[1, 2, 3, 4, 5, 6, 7, 8, 9, 0],
        )

        agent = AgentState.from_json_file(path)

        assert agent.session_id == "sess-1"
        assert agent.status == AgentStatus.WORKING
        assert agent.cwd == "/home/user/project"
        assert agent.project_name == "my-project"
        assert agent.model == "claude-opus-4-6"
        assert agent.last_event == "PostToolUse"
        assert agent.last_tool == "Edit"
        assert agent.tool_count == 42
        assert agent.error_count == 3
        assert agent.started_at == "2026-02-22T10:00:00Z"
        assert agent.last_event_time == "2026-02-22T10:30:00Z"
        assert agent.notification_message == "Build passed"
        assert agent.activity_history == [1, 2, 3, 4, 5, 6, 7, 8, 9, 0]

    def test_agent_state_from_json_file_new_fields(self, make_agent_state):
        """New counter fields load correctly from JSON."""
        path = make_agent_state(
            session_id="new-fields",
            subagent_count=3,
            compact_count=2,
            last_compact_time="2026-02-22T11:00:00Z",
            task_completed_count=5,
        )

        agent = AgentState.from_json_file(path)

        assert agent.subagent_count == 3
        assert agent.compact_count == 2
        assert agent.last_compact_time == "2026-02-22T11:00:00Z"
        assert agent.task_completed_count == 5

    def test_agent_state_term_program_from_json(self, make_agent_state):
        """term_program loads from JSON file."""
        import json
        from pathlib import Path

        # Write a state file with term_program
        path = make_agent_state(session_id="term-test")
        data = json.loads(path.read_text())
        data["term_program"] = "iTerm.app"
        path.write_text(json.dumps(data))

        agent = AgentState.from_json_file(path)
        assert agent.term_program == "iTerm.app"

    def test_agent_state_term_program_default_empty(self, make_agent_state):
        """term_program defaults to empty string when missing."""
        path = make_agent_state(session_id="no-term")
        agent = AgentState.from_json_file(path)
        assert agent.term_program == ""

    def test_agent_state_tmux_session_from_json(self, make_agent_state):
        """tmux_session loads from JSON file."""
        import json

        path = make_agent_state(session_id="tmux-sess-test")
        data = json.loads(path.read_text())
        data["tmux_session"] = "my-session"
        path.write_text(json.dumps(data))

        agent = AgentState.from_json_file(path)
        assert agent.tmux_session == "my-session"

    def test_agent_state_tmux_session_default_empty(self, make_agent_state):
        """tmux_session defaults to empty string when missing."""
        path = make_agent_state(session_id="no-tmux-sess")
        agent = AgentState.from_json_file(path)
        assert agent.tmux_session == ""

    def test_agent_state_from_json_file_missing_fields(self, tmp_state_dir):
        """Loading JSON with only session_id fills defaults for missing fields."""
        import json

        path = tmp_state_dir / "minimal.json"
        path.write_text(json.dumps({"session_id": "minimal-sess"}))

        agent = AgentState.from_json_file(path)

        assert agent.session_id == "minimal-sess"
        assert agent.status == AgentStatus.IDLE  # default
        assert agent.cwd == ""
        assert agent.project_name == ""
        assert agent.model == ""
        assert agent.last_event == ""
        assert agent.last_tool == ""
        assert agent.tool_count == 0
        assert agent.error_count == 0
        assert agent.subagent_count == 0
        assert agent.compact_count == 0
        assert agent.last_compact_time == ""
        assert agent.task_completed_count == 0
        assert agent.started_at == ""
        assert agent.notification_message is None
        assert agent.term_program == ""
        assert len(agent.activity_history) == 10
        assert all(v == 0 for v in agent.activity_history)

    def test_agent_state_from_json_file_invalid_status(self, tmp_state_dir):
        """An unrecognised status string falls back to IDLE."""
        import json

        path = tmp_state_dir / "bad-status.json"
        path.write_text(json.dumps({
            "session_id": "bad-status",
            "status": "TOTALLY_INVALID_STATUS",
        }))

        agent = AgentState.from_json_file(path)

        assert agent.status == AgentStatus.IDLE


# ------------------------------------------------------------------
# AgentState.uptime
# ------------------------------------------------------------------


class TestAgentStateUptime:
    """Tests for uptime property."""

    def test_agent_state_uptime(self, make_agent_state):
        """Uptime is calculated relative to datetime.now(UTC)."""
        # Agent started 2 hours and 15 minutes ago.
        started = datetime(2026, 2, 22, 8, 0, 0, tzinfo=timezone.utc)
        now = datetime(2026, 2, 22, 10, 15, 0, tzinfo=timezone.utc)

        path = make_agent_state(
            session_id="uptime-test",
            started_at=started.isoformat().replace("+00:00", "Z"),
        )
        agent = AgentState.from_json_file(path)

        with patch("clorch.state.models.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.fromisoformat = datetime.fromisoformat
            uptime = agent.uptime

        assert uptime == "2h 15m"

    def test_agent_state_uptime_no_started_at(self):
        """Empty started_at returns '0m'."""
        agent = AgentState(session_id="no-start", started_at="")
        assert agent.uptime == "0m"

    def test_agent_state_uptime_invalid_timestamp(self):
        """Garbage started_at returns '?'."""
        agent = AgentState(session_id="bad-ts", started_at="not-a-date")
        assert agent.uptime == "?"


# ------------------------------------------------------------------
# AgentState.needs_attention
# ------------------------------------------------------------------


class TestAgentStateNeedsAttention:
    """Tests for needs_attention property."""

    @pytest.mark.parametrize("status", [
        AgentStatus.WAITING_PERMISSION,
        AgentStatus.WAITING_ANSWER,
        AgentStatus.ERROR,
    ])
    def test_agent_state_needs_attention(self, status):
        """WAITING_PERMISSION, WAITING_ANSWER, and ERROR need attention."""
        agent = AgentState(session_id="attn", status=status)
        assert agent.needs_attention is True

    @pytest.mark.parametrize("status", [
        AgentStatus.WORKING,
        AgentStatus.IDLE,
    ])
    def test_agent_state_no_attention(self, status):
        """WORKING and IDLE do not need attention."""
        agent = AgentState(session_id="ok", status=status)
        assert agent.needs_attention is False


# ------------------------------------------------------------------
# StatusSummary
# ------------------------------------------------------------------


class TestStatusSummary:
    """Tests for the StatusSummary aggregate model."""

    def test_status_summary_from_agents(self):
        """Create multiple agents, check per-status counts."""
        agents = [
            AgentState(session_id="a1", status=AgentStatus.WORKING),
            AgentState(session_id="a2", status=AgentStatus.WORKING),
            AgentState(session_id="a3", status=AgentStatus.IDLE),
            AgentState(session_id="a4", status=AgentStatus.WAITING_PERMISSION),
            AgentState(session_id="a5", status=AgentStatus.ERROR),
        ]
        summary = StatusSummary.from_agents(agents)

        assert summary.working == 2
        assert summary.idle == 1
        assert summary.waiting_permission == 1
        assert summary.waiting_answer == 0
        assert summary.error == 1

    def test_status_summary_status_line(self):
        """status_line() produces compact W:N [!]:N format."""
        agents = [
            AgentState(session_id="a1", status=AgentStatus.WORKING),
            AgentState(session_id="a2", status=AgentStatus.WORKING),
            AgentState(session_id="a3", status=AgentStatus.WORKING),
            AgentState(session_id="a4", status=AgentStatus.WAITING_PERMISSION),
            AgentState(session_id="a5", status=AgentStatus.WAITING_PERMISSION),
            AgentState(session_id="a6", status=AgentStatus.WAITING_ANSWER),
            AgentState(session_id="a7", status=AgentStatus.ERROR),
            AgentState(session_id="a8", status=AgentStatus.IDLE),
        ]
        summary = StatusSummary.from_agents(agents)
        line = summary.status_line()

        assert "W:3" in line
        assert "[!]:2" in line
        assert "[?]:1" in line
        assert "E:1" in line
        assert "I:1" in line

    def test_status_summary_empty(self):
        """No agents produces 'no agents'."""
        summary = StatusSummary.from_agents([])
        assert summary.status_line() == "no agents"

    def test_status_summary_total(self):
        """total property is the sum of all status counts."""
        agents = [
            AgentState(session_id="a1", status=AgentStatus.WORKING),
            AgentState(session_id="a2", status=AgentStatus.IDLE),
            AgentState(session_id="a3", status=AgentStatus.ERROR),
        ]
        summary = StatusSummary.from_agents(agents)
        assert summary.total == 3

    def test_status_summary_attention_count(self):
        """attention_count counts only WAITING_PERMISSION + WAITING_ANSWER + ERROR."""
        agents = [
            AgentState(session_id="a1", status=AgentStatus.WORKING),
            AgentState(session_id="a2", status=AgentStatus.IDLE),
            AgentState(session_id="a3", status=AgentStatus.WAITING_PERMISSION),
            AgentState(session_id="a4", status=AgentStatus.WAITING_ANSWER),
            AgentState(session_id="a5", status=AgentStatus.ERROR),
        ]
        summary = StatusSummary.from_agents(agents)
        assert summary.attention_count == 3


# ------------------------------------------------------------------
# ActionItem & build_action_queue
# ------------------------------------------------------------------


class TestActionItem:
    """Tests for ActionItem dataclass."""

    def test_action_item_fields(self):
        agent = AgentState(session_id="s1", status=AgentStatus.WAITING_PERMISSION)
        item = ActionItem(letter="a", agent=agent, actionable=True, summary="Allow Bash")
        assert item.letter == "a"
        assert item.agent is agent
        assert item.actionable is True
        assert item.summary == "Allow Bash"


class TestBuildActionQueue:
    """Tests for build_action_queue()."""

    def test_empty_agents(self):
        """No agents produces empty queue."""
        assert build_action_queue([]) == []

    def test_no_attention_agents(self):
        """Only WORKING/IDLE agents produces empty queue."""
        agents = [
            AgentState(session_id="w", status=AgentStatus.WORKING),
            AgentState(session_id="i", status=AgentStatus.IDLE),
        ]
        assert build_action_queue(agents) == []

    def test_ordering_perm_first(self):
        """PERM items come before WAIT, which come before ERR."""
        agents = [
            AgentState(session_id="err", status=AgentStatus.ERROR),
            AgentState(session_id="ask", status=AgentStatus.WAITING_ANSWER),
            AgentState(session_id="perm", status=AgentStatus.WAITING_PERMISSION),
            AgentState(session_id="work", status=AgentStatus.WORKING),
        ]
        items = build_action_queue(agents)
        assert len(items) == 3
        assert items[0].agent.session_id == "perm"
        assert items[1].agent.session_id == "ask"
        assert items[2].agent.session_id == "err"

    def test_letter_assignment(self):
        """Letters are assigned sequentially starting from 'a'."""
        agents = [
            AgentState(session_id="p1", status=AgentStatus.WAITING_PERMISSION),
            AgentState(session_id="p2", status=AgentStatus.WAITING_PERMISSION),
            AgentState(session_id="a1", status=AgentStatus.WAITING_ANSWER),
        ]
        items = build_action_queue(agents)
        assert [i.letter for i in items] == ["a", "b", "c"]

    def test_actionable_flag(self):
        """Only WAITING_PERMISSION items are actionable."""
        agents = [
            AgentState(session_id="perm", status=AgentStatus.WAITING_PERMISSION),
            AgentState(session_id="ask", status=AgentStatus.WAITING_ANSWER),
            AgentState(session_id="err", status=AgentStatus.ERROR),
        ]
        items = build_action_queue(agents)
        assert items[0].actionable is True   # PERM
        assert items[1].actionable is False  # WAIT
        assert items[2].actionable is False  # ERR

    def test_max_26_items(self):
        """Queue is capped at 26 items (a-z)."""
        agents = [
            AgentState(session_id=f"p{i}", status=AgentStatus.WAITING_PERMISSION)
            for i in range(30)
        ]
        items = build_action_queue(agents)
        assert len(items) == 26
        assert items[-1].letter == "z"

    def test_tmux_reachable_agents_sorted_first_within_perm(self):
        """PERM agents with tmux_window come before those without."""
        agents = [
            AgentState(
                session_id="no-tmux",
                status=AgentStatus.WAITING_PERMISSION,
            ),
            AgentState(
                session_id="in-tmux",
                status=AgentStatus.WAITING_PERMISSION,
                tmux_window="my-win",
                tmux_session="sess",
            ),
        ]
        items = build_action_queue(agents)
        assert items[0].agent.session_id == "in-tmux"
        assert items[1].agent.session_id == "no-tmux"

    def test_tmux_sorting_does_not_change_cross_tier_order(self):
        """tmux sorting only applies within the same status tier."""
        agents = [
            AgentState(
                session_id="ask-tmux",
                status=AgentStatus.WAITING_ANSWER,
                tmux_window="win",
            ),
            AgentState(
                session_id="perm-no-tmux",
                status=AgentStatus.WAITING_PERMISSION,
            ),
        ]
        items = build_action_queue(agents)
        # PERM always before WAIT regardless of tmux
        assert items[0].agent.session_id == "perm-no-tmux"
        assert items[1].agent.session_id == "ask-tmux"

    def test_summary_from_notification_message(self):
        """Summary is taken from notification_message."""
        agents = [
            AgentState(
                session_id="s1",
                status=AgentStatus.WAITING_PERMISSION,
                notification_message="Allow Write: src/api.py",
            ),
        ]
        items = build_action_queue(agents)
        assert items[0].summary == "Allow Write: src/api.py"

    def test_summary_empty_when_no_message(self):
        """Summary is empty string when notification_message is None."""
        agents = [
            AgentState(session_id="s1", status=AgentStatus.WAITING_PERMISSION),
        ]
        items = build_action_queue(agents)
        assert items[0].summary == ""

    def test_summary_fallback_to_tool_request_summary(self):
        """Summary falls back to tool_request_summary when notification_message is None."""
        agents = [
            AgentState(
                session_id="s1",
                status=AgentStatus.WAITING_PERMISSION,
                tool_request_summary="$ rm -rf /tmp/test",
            ),
        ]
        items = build_action_queue(agents)
        assert items[0].summary == "$ rm -rf /tmp/test"

    def test_summary_notification_takes_priority(self):
        """notification_message takes priority over tool_request_summary."""
        agents = [
            AgentState(
                session_id="s1",
                status=AgentStatus.WAITING_PERMISSION,
                notification_message="Allow Bash",
                tool_request_summary="$ rm -rf /tmp/test",
            ),
        ]
        items = build_action_queue(agents)
        assert items[0].summary == "Allow Bash"


# ------------------------------------------------------------------
# AgentState.tool_request_summary
# ------------------------------------------------------------------


class TestToolRequestSummary:
    """Tests for tool_request_summary field."""

    def test_tool_request_summary_from_json(self, make_agent_state):
        """tool_request_summary loads from JSON file."""
        path = make_agent_state(
            session_id="perm-test",
            status="WAITING_PERMISSION",
            tool_request_summary="$ ls -la /tmp",
        )
        agent = AgentState.from_json_file(path)
        assert agent.tool_request_summary == "$ ls -la /tmp"

    def test_tool_request_summary_default_none(self, make_agent_state):
        """tool_request_summary defaults to None when not in JSON."""
        path = make_agent_state(session_id="no-summary")
        agent = AgentState.from_json_file(path)
        assert agent.tool_request_summary is None

    def test_tool_request_summary_none_in_json(self, tmp_state_dir):
        """tool_request_summary is None when explicitly null in JSON."""
        import json
        path = tmp_state_dir / "null-summary.json"
        path.write_text(json.dumps({
            "session_id": "null-summary",
            "tool_request_summary": None,
        }))
        agent = AgentState.from_json_file(path)
        assert agent.tool_request_summary is None
