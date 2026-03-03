"""Data models for agent state."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from clorch.constants import AgentStatus, ATTENTION_STATUSES, ACTIVITY_HISTORY_LEN


@dataclass
class AgentState:
    """State of a single Claude Code agent/session."""

    session_id: str
    status: AgentStatus = AgentStatus.IDLE
    cwd: str = ""
    project_name: str = ""
    session_name: str = ""
    model: str = ""
    last_event: str = ""
    last_event_time: str = ""
    last_tool: str = ""
    notification_message: str | None = None
    started_at: str = ""
    tool_count: int = 0
    error_count: int = 0
    subagent_count: int = 0
    compact_count: int = 0
    last_compact_time: str = ""
    task_completed_count: int = 0
    activity_history: list[int] = field(default_factory=lambda: [0] * ACTIVITY_HISTORY_LEN)
    # Git context
    git_branch: str = ""
    git_dirty_count: int = 0
    # Process tracking — used to detect dead sessions
    pid: int | None = None
    # tmux mapping (filled by hook / navigator)
    tmux_window: str = ""
    tmux_pane: str = ""
    tmux_session: str = ""
    tmux_window_index: str = ""
    term_program: str = ""
    tool_request_summary: str | None = None

    @property
    def uptime(self) -> str:
        """Human-readable uptime string like '2h 15m'."""
        if not self.started_at:
            return "0m"
        try:
            started = datetime.fromisoformat(self.started_at.replace("Z", "+00:00"))
            delta = datetime.now(timezone.utc) - started
            hours, remainder = divmod(int(delta.total_seconds()), 3600)
            minutes = remainder // 60
            return f"{hours}h {minutes:02d}m"
        except (ValueError, TypeError):
            return "?"

    @property
    def needs_attention(self) -> bool:
        """True if agent is waiting for user input or has an error."""
        return self.status in ATTENTION_STATUSES

    @classmethod
    def from_json_file(cls, path: Path) -> AgentState:
        """Load state from a JSON file on disk."""
        data = json.loads(path.read_text())
        status_raw = data.get("status", "IDLE")
        try:
            status = AgentStatus(status_raw)
        except ValueError:
            status = AgentStatus.IDLE
        return cls(
            session_id=data.get("session_id", path.stem),
            status=status,
            cwd=data.get("cwd", ""),
            project_name=data.get("project_name", ""),
            session_name=data.get("session_name", ""),
            model=data.get("model", ""),
            last_event=data.get("last_event", ""),
            last_event_time=data.get("last_event_time", ""),
            last_tool=data.get("last_tool", ""),
            notification_message=data.get("notification_message"),
            started_at=data.get("started_at", ""),
            tool_count=data.get("tool_count", 0),
            error_count=data.get("error_count", 0),
            subagent_count=data.get("subagent_count", 0),
            compact_count=data.get("compact_count", 0),
            last_compact_time=data.get("last_compact_time", ""),
            task_completed_count=data.get("task_completed_count", 0),
            git_branch=data.get("git_branch", ""),
            git_dirty_count=data.get("git_dirty_count", 0),
            activity_history=data.get("activity_history", [0] * ACTIVITY_HISTORY_LEN),
            pid=data.get("pid"),
            tmux_window=data.get("tmux_window", ""),
            tmux_pane=data.get("tmux_pane", ""),
            tmux_session=data.get("tmux_session", ""),
            tmux_window_index=data.get("tmux_window_index", ""),
            term_program=data.get("term_program", ""),
            tool_request_summary=data.get("tool_request_summary"),
        )


@dataclass
class StatusSummary:
    """Aggregate counts across all agents."""

    working: int = 0
    idle: int = 0
    waiting_permission: int = 0
    waiting_answer: int = 0
    error: int = 0
    total_tools: int = 0

    @property
    def total(self) -> int:
        return self.working + self.idle + self.waiting_permission + self.waiting_answer + self.error

    @property
    def attention_count(self) -> int:
        return self.waiting_permission + self.waiting_answer + self.error

    def status_line(self) -> str:
        """Compact one-liner: W:3 [!]:2 I:1"""
        parts = []
        if self.working:
            parts.append(f"W:{self.working}")
        if self.waiting_permission:
            parts.append(f"[!]:{self.waiting_permission}")
        if self.waiting_answer:
            parts.append(f"[?]:{self.waiting_answer}")
        if self.error:
            parts.append(f"E:{self.error}")
        if self.idle:
            parts.append(f"I:{self.idle}")
        return "  ".join(parts) if parts else "no agents"

    @classmethod
    def from_agents(cls, agents: list[AgentState]) -> StatusSummary:
        s = cls()
        for a in agents:
            s.total_tools += a.tool_count
            match a.status:
                case AgentStatus.WORKING:
                    s.working += 1
                case AgentStatus.IDLE:
                    s.idle += 1
                case AgentStatus.WAITING_PERMISSION:
                    s.waiting_permission += 1
                case AgentStatus.WAITING_ANSWER:
                    s.waiting_answer += 1
                case AgentStatus.ERROR:
                    s.error += 1
        return s


@dataclass
class ActionItem:
    """A single item in the action queue."""

    letter: str
    agent: AgentState
    actionable: bool  # True for PERM (y/n), False for WAIT/ERR (jump only)
    summary: str


# Sort priority for attention agents: PERM first, then WAIT, then ERR.
_ACTION_PRIORITY: dict[AgentStatus, int] = {
    AgentStatus.WAITING_PERMISSION: 0,
    AgentStatus.WAITING_ANSWER: 1,
    AgentStatus.ERROR: 2,
}


def build_action_queue(agents: list[AgentState]) -> list[ActionItem]:
    """Build the action queue from agents needing attention.

    Filters to attention agents, sorts PERM > WAIT > ERR, assigns
    letters ``a``–``z`` (max 26 items).  Within the same status tier,
    tmux-reachable agents (``tmux_window`` set) are listed first so
    pressing ``y`` auto-focuses an agent that can be approved via
    send-keys.
    """
    attention = [a for a in agents if a.status in ATTENTION_STATUSES]
    attention.sort(key=lambda a: (
        _ACTION_PRIORITY.get(a.status, 99),
        0 if a.tmux_window else 1,
    ))

    items: list[ActionItem] = []
    for i, agent in enumerate(attention[:26]):
        letter = chr(ord("a") + i)
        actionable = agent.status == AgentStatus.WAITING_PERMISSION
        summary = agent.notification_message or agent.tool_request_summary or ""
        items.append(ActionItem(
            letter=letter,
            agent=agent,
            actionable=actionable,
            summary=summary,
        ))
    return items
