"""Agent table widget showing all Claude Code sessions."""
from __future__ import annotations

from textual.widgets import DataTable
from textual.message import Message
from rich.text import Text

from clorch.state.models import AgentState
from clorch.constants import AgentStatus, STATUS_DISPLAY, SPARKLINE_CHARS, CYAN, PINK


# Sort priority: attention statuses first, then working, then idle.
_TABLE_SORT_PRIORITY: dict[AgentStatus, int] = {
    AgentStatus.WAITING_PERMISSION: 0,
    AgentStatus.WAITING_ANSWER: 1,
    AgentStatus.ERROR: 2,
    AgentStatus.WORKING: 3,
    AgentStatus.IDLE: 4,
}


class AgentSelected(Message):
    """Posted when user selects an agent."""

    def __init__(self, agent: AgentState) -> None:
        self.agent = agent
        super().__init__()


class AgentTable(DataTable):
    """DataTable displaying agent status list."""

    DEFAULT_CSS = """
    AgentTable {
        height: 1fr;
        min-height: 8;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._agents: list[AgentState] = []

    def on_mount(self) -> None:
        self.add_columns(
            "#", "PROJECT", "SESSION", "STATUS", "TOOL",
            "T", "E", "UP", "ACTIVITY", "MSG",
        )
        self.cursor_type = "row"
        self.zebra_stripes = True

    def update_agents(self, agents: list[AgentState]) -> None:
        """Refresh table data with attention-first sorting."""
        # Sort: PERM > WAIT > ERR > WORK > IDLE, then by project name
        agents = sorted(
            agents,
            key=lambda a: (
                _TABLE_SORT_PRIORITY.get(a.status, 99),
                a.project_name.lower(),
            ),
        )

        # Preserve cursor position across rebuilds
        prev_row = self.cursor_row
        # Track by session_id so cursor follows the agent if sort order changes
        prev_id = (
            self._agents[prev_row].session_id
            if prev_row is not None and 0 <= prev_row < len(self._agents)
            else None
        )

        self._agents = agents
        self.clear()
        for i, agent in enumerate(agents, 1):
            symbol, label, color = STATUS_DISPLAY[agent.status]
            status_text = Text(f"{symbol}{label}", style=f"bold {color}")
            tool_text = Text(agent.last_tool or "", style="dim")
            sparkline = self._render_sparkline(agent.activity_history)
            project_label = agent.project_name or agent.session_id[:12]
            if agent.subagent_count > 0:
                project_label = f"{project_label} [{agent.subagent_count}s]"

            # Truncated notification message
            msg = agent.notification_message or ""
            if len(msg) > 40:
                msg = msg[:38] + ".."

            # Error count — highlight if non-zero
            err_text = Text(str(agent.error_count), style=f"bold {PINK}" if agent.error_count else "dim")

            session_name = (agent.session_name or "")[:40]

            self.add_row(
                str(i),
                project_label,
                Text(session_name, style="dim italic"),
                status_text,
                tool_text,
                str(agent.tool_count),
                err_text,
                agent.uptime,
                sparkline,
                Text(msg, style="dim italic"),
                key=agent.session_id,
            )

        # Restore cursor position
        if agents and prev_id is not None:
            # Try to follow the same agent
            for idx, agent in enumerate(agents):
                if agent.session_id == prev_id:
                    self.move_cursor(row=idx)
                    return
            # Agent gone — clamp to previous row
            self.move_cursor(row=min(prev_row, len(agents) - 1))
        elif agents and prev_row is not None:
            self.move_cursor(row=min(prev_row, len(agents) - 1))

    def _render_sparkline(self, history: list[int]) -> Text:
        """Render activity history as sparkline."""
        if not history or max(history) == 0:
            return Text("\u2581" * 10, style="dim #555555")
        max_val = max(history)
        chars = []
        for v in history:
            idx = min(int(v / max(max_val, 1) * 7), 7)
            chars.append(SPARKLINE_CHARS[idx])
        return Text("".join(chars), style=CYAN)

    def get_selected_agent(self) -> AgentState | None:
        """Get the currently highlighted agent."""
        if self.cursor_row is not None and 0 <= self.cursor_row < len(self._agents):
            return self._agents[self.cursor_row]
        return None

    def get_agent_by_number(self, num: int) -> AgentState | None:
        """Get an agent by its 1-based display number.

        Number keys: ``1``–``9`` map to rows 1–9, ``0`` maps to row 10.
        Returns ``None`` if the number is out of range.
        """
        if num == 0:
            num = 10
        idx = num - 1
        if 0 <= idx < len(self._agents):
            return self._agents[idx]
        return None
