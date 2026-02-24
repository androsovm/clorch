"""Agent detail panel."""
from __future__ import annotations

from textual.widgets import Static
from rich.text import Text

from clorch.state.models import AgentState
from clorch.constants import STATUS_DISPLAY
from clorch.constants import CYAN, GREEN, PINK


class AgentDetail(Static):
    """Shows detailed information about the selected agent."""

    DEFAULT_CSS = """
    AgentDetail {
        height: auto;
        max-height: 12;
        border: solid;
        padding: 0 1;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__("", **kwargs)
        self._agent: AgentState | None = None

    def show_agent(self, agent: AgentState | None) -> None:
        self._agent = agent
        if agent is None:
            self.display = False
            return
        self.display = True

        symbol, label, color = STATUS_DISPLAY[agent.status]

        text = Text()
        text.append(f" DETAIL: ", style=f"bold {CYAN}")
        text.append(f"{agent.project_name}\n", style="bold white")
        text.append(f" Path: ", style="dim")
        text.append(f"{agent.cwd}", style=GREEN)
        text.append(f"  Model: ", style="dim")
        text.append(f"{agent.model}", style=CYAN)
        text.append(f"  Tools: ", style="dim")
        text.append(f"{agent.tool_count}", style="white")
        text.append(f"  Errors: ", style="dim")
        text.append(f"{agent.error_count}", style=PINK if agent.error_count else "dim")
        if agent.subagent_count or agent.compact_count or agent.task_completed_count:
            if agent.subagent_count:
                text.append(f"  Subagents: ", style="dim")
                text.append(f"{agent.subagent_count}", style=CYAN)
            if agent.compact_count:
                text.append(f"  Compacts: ", style="dim")
                text.append(f"{agent.compact_count}", style=PINK)
            if agent.task_completed_count:
                text.append(f"  Tasks done: ", style="dim")
                text.append(f"{agent.task_completed_count}", style=GREEN)
        text.append("\n")
        text.append(f" Status: ", style="dim")
        text.append(f"{symbol} {label}", style=f"bold {color}")
        text.append(f"  Uptime: ", style="dim")
        text.append(f"{agent.uptime}", style="white")
        if agent.notification_message:
            text.append(f"\n Msg: ", style="dim")
            msg = agent.notification_message[:120]
            text.append(f'"{msg}"', style="italic #FFB800")

        self.update(text)
