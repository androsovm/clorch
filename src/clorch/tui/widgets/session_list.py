"""Session list widget — ListView replacement for AgentTable (DataTable)."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import ListView, ListItem, Static
from textual.message import Message
from rich.text import Text

from clorch.state.models import AgentState, ActionItem
from clorch.constants import (
    AgentStatus, STATUS_DISPLAY, SPARKLINE_CHARS, BRAILLE_SPINNER,
    CYAN, GREEN, GREY, PINK, RED, YELLOW,
)


class SessionRow(ListItem):
    """A single agent row in the session list.

    Renders: row number, project name, status badge, mini sparkline.
    Attention rows get a colored left accent and inline action hints.
    """

    DEFAULT_CSS = """
    SessionRow {
        height: auto;
        padding: 0 1;
    }
    """

    def __init__(self, agent: AgentState, row_num: int, **kwargs) -> None:
        super().__init__(**kwargs)
        self.agent = agent
        self._row_num = row_num
        self._action: ActionItem | None = None
        self._action_focused: bool = False
        self._anim_frame: int = 0

    def compose(self) -> ComposeResult:
        yield Static(self._render_row(), markup=False)

    def set_action(self, action: ActionItem | None) -> None:
        """Associate an action item with this row."""
        self._action = action
        self._action_focused = False
        self._refresh_display()

    def set_action_focused(self, focused: bool) -> None:
        """Set whether this row's action is currently focused for approval."""
        if self._action_focused != focused:
            self._action_focused = focused
            self._refresh_display()

    def set_anim_frame(self, frame: int) -> None:
        """Set the global animation frame and re-render if animated."""
        if self._anim_frame != frame:
            self._anim_frame = frame
            # Only re-render if this row has animation (WORKING or PERM)
            if self.agent.status in (AgentStatus.WORKING, AgentStatus.WAITING_PERMISSION):
                self._refresh_display()

    def update_row(self, agent: AgentState, row_num: int) -> None:
        """Update the row with new agent data."""
        self.agent = agent
        self._row_num = row_num
        self._refresh_display()

    def _refresh_display(self) -> None:
        """Re-render the row content."""
        try:
            static = self.query_one(Static)
            static.update(self._render_row())
        except Exception:
            pass

    # Fixed column widths for vertical alignment across all rows.
    _COL_ACCENT = 2     # "┃ " or "  "
    _COL_NUM = 3        # "[a]" or " 1 "
    _COL_PROJECT = 22   # project name padded
    _COL_STATUS = 8     # ">>> WORK" / "[!] PERM" — symbol(3) + space + label(4)
    _COL_TOOL = 12      # last tool name padded
    _COL_TCNT = 4       # tool count right-aligned
    _COL_ECNT = 3       # error count right-aligned
    _COL_UPTIME = 8     # "1h 23m" right-aligned
    _COL_SPARK = 10     # sparkline chars

    def _render_row(self) -> Text:
        """Render the row as Rich Text with fixed-width columns."""
        text = Text()
        agent = self.agent

        symbol, label, color = STATUS_DISPLAY[agent.status]

        # Animated symbol for WORKING: braille spinner (same width as ">>>")
        if agent.status == AgentStatus.WORKING:
            spinner_char = BRAILLE_SPINNER[self._anim_frame % len(BRAILLE_SPINNER)]
            symbol = f" {spinner_char} "

        # Col 1: Left accent (2 chars)
        if agent.status == AgentStatus.WAITING_PERMISSION:
            perm_style = f"bold {RED}" if (self._anim_frame // 2) % 2 == 0 else f"dim {RED}"
            text.append("\u2503 ", style=perm_style)
        elif agent.status == AgentStatus.WAITING_ANSWER:
            text.append("\u2503 ", style=f"bold {YELLOW}")
        elif agent.status == AgentStatus.ERROR:
            text.append("\u2503 ", style=f"bold {PINK}")
        else:
            text.append("  ", style="dim")

        # Col 2: Row number or action letter (3 chars)
        if self._action:
            letter_style = f"bold {GREEN}" if self._action_focused else f"bold {CYAN}"
            text.append(f"[{self._action.letter}]", style=letter_style)
        else:
            display_num = self._row_num if self._row_num <= 9 else 0
            text.append(f" {display_num} ", style="dim")

        text.append(" ", style="dim")

        # Col 3: Project name (fixed 18 chars)
        project = agent.project_name or agent.session_id[:12]
        if agent.subagent_count > 0:
            project = f"{project} [{agent.subagent_count}s]"
        text.append(f"{project:<{self._COL_PROJECT}s}"[:self._COL_PROJECT], style="bold white")

        # Col 4: Status badge (fixed 8 chars: ">>> WORK", "[!] PERM")
        status_str = f"{symbol} {label:<4s}"
        text.append(f" {status_str:<{self._COL_STATUS}s}", style=f"bold {color}")

        # Col 5: Last tool (fixed 12 chars)
        tool = (agent.last_tool or "-")[:self._COL_TOOL]
        text.append(f" {tool:<{self._COL_TOOL}s}", style="white")

        # Col 6: Tool count (right-aligned 4 chars)
        text.append(f"{agent.tool_count:>{self._COL_TCNT}d}", style="dim")

        # Col 7: Error count (right-aligned 3 chars)
        ecnt = f"{agent.error_count:>{self._COL_ECNT}d}"
        if agent.error_count > 0:
            text.append(ecnt, style=f"bold {PINK}")
        else:
            text.append(ecnt, style="dim")

        # Col 8: Uptime (right-aligned 8 chars)
        text.append(f"{agent.uptime:>{self._COL_UPTIME}s}", style="dim")

        # Col 9: Sparkline (10 chars)
        text.append("  ", style="dim")
        sparkline = self._render_sparkline(agent.activity_history)
        text.append_text(sparkline)

        # Col 10: Notification message (remaining space)
        msg = agent.notification_message or ""
        if msg:
            trunc = msg[:60] if len(msg) > 60 else msg
            text.append(f"  {trunc}", style="dim italic")

        # Inline action hints
        if self._action:
            text.append("  ", style="dim")
            if self._action.actionable:
                text.append("[y]", style=f"bold {GREEN}")
                text.append("[n]", style=f"bold {RED}")
            else:
                text.append("[->]", style=f"bold {CYAN}")

        # Focused action expansion
        if self._action_focused and self._action and self._action.actionable:
            summary = self._action.summary or ""
            text.append(f'\n  "{summary}"', style="italic")
            text.append("\n  >>> ", style=f"bold {GREEN}")
            text.append("[y]", style=f"bold reverse {GREEN}")
            text.append(" APPROVE  ", style="dim")
            text.append("[n]", style=f"bold reverse {RED}")
            text.append(" DENY  ", style="dim")
            text.append("[Esc]", style=f"bold {CYAN}")
            text.append(" cancel", style="dim")

        return text

    @staticmethod
    def _render_sparkline(history: list[int]) -> Text:
        """Render activity history as a 10-char sparkline."""
        recent = history[-10:] if len(history) >= 10 else history
        if not recent or max(recent) == 0:
            return Text("\u2581" * 10, style=f"dim {GREY}")
        max_val = max(recent)
        chars = []
        for v in recent:
            idx = min(int(v / max(max_val, 1) * 7), 7)
            chars.append(SPARKLINE_CHARS[idx])
        # Pad to 10 chars
        while len(chars) < 10:
            chars.insert(0, SPARKLINE_CHARS[0])
        return Text("".join(chars), style=CYAN)


class SessionList(ListView):
    """ListView-based session list replacing AgentTable.

    Provides the same public API as AgentTable so the app can use it
    as a drop-in replacement.  Also supports inline action display.
    """

    DEFAULT_CSS = """
    SessionList {
        height: 1fr;
        min-height: 8;
        scrollbar-size: 1 1;
    }
    SessionList > ListItem.--highlight {
        background: #3A4A60;
    }
    """

    class AgentHighlighted(Message):
        """Posted when the cursor moves to a new agent."""

        def __init__(self, agent: AgentState) -> None:
            self.agent = agent
            super().__init__()

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._agents: list[AgentState] = []
        self._action_map: dict[str, ActionItem] = {}  # session_id -> ActionItem
        self._focused_letter: str | None = None

    def update_agents(self, agents: list[AgentState]) -> None:
        """Refresh the list with stable alphabetical sorting.

        Rows are sorted by project name only — status changes never
        cause rows to jump.  Updates existing rows in-place to avoid
        flicker; only rebuilds from scratch when the agent *set* changes
        (new agent appeared or old one disappeared).
        """
        # Stable sort: alphabetical by project name only.
        agents = sorted(agents, key=lambda a: a.project_name.lower())

        new_ids = [a.session_id for a in agents]
        old_ids = [a.session_id for a in self._agents]

        if new_ids == old_ids:
            # Same agents in same order — update in-place (no flicker)
            self._agents = agents
            rows = [c for c in self.children if isinstance(c, SessionRow)]
            for i, (agent, row) in enumerate(zip(agents, rows), 1):
                row.update_row(agent, i)
                action = self._action_map.get(agent.session_id)
                row.set_action(action)
                if action and self._focused_letter and action.letter == self._focused_letter:
                    row.set_action_focused(True)
                else:
                    row.set_action_focused(False)
            return

        # Agent set changed — full rebuild
        prev_id: str | None = None
        if self._agents and self.index is not None and 0 <= self.index < len(self._agents):
            prev_id = self._agents[self.index].session_id

        self._agents = agents

        self.clear()
        for i, agent in enumerate(agents, 1):
            row = SessionRow(agent, i)
            action = self._action_map.get(agent.session_id)
            if action:
                row.set_action(action)
                if self._focused_letter and action.letter == self._focused_letter:
                    row.set_action_focused(True)
            self.append(row)

        # Restore cursor position by session_id.
        # Defer via call_after_refresh so the appended items are mounted
        # before ListView applies the --highlight class.
        new_index = 0
        if prev_id is not None:
            for idx, agent in enumerate(agents):
                if agent.session_id == prev_id:
                    new_index = idx
                    break
            else:
                # Previous agent gone — clamp to valid range
                old_idx = self.index if self.index is not None else 0
                new_index = min(old_idx, max(len(agents) - 1, 0))
        if agents:
            self.call_after_refresh(setattr, self, "index", new_index)

    def update_actions(self, items: list[ActionItem]) -> None:
        """Update the action map and refresh inline action display."""
        self._action_map = {item.agent.session_id: item for item in items}
        # Update existing rows with action info
        for child in self.children:
            if isinstance(child, SessionRow):
                action = self._action_map.get(child.agent.session_id)
                child.set_action(action)
                if action and self._focused_letter and action.letter == self._focused_letter:
                    child.set_action_focused(True)
                else:
                    child.set_action_focused(False)

    def set_action_focus(self, letter: str) -> None:
        """Focus an action by its letter — expands the matching row."""
        self._focused_letter = letter
        for child in self.children:
            if isinstance(child, SessionRow) and child._action:
                child.set_action_focused(child._action.letter == letter)

    def clear_action_focus(self) -> None:
        """Clear the focused action on all rows."""
        self._focused_letter = None
        for child in self.children:
            if isinstance(child, SessionRow):
                child.set_action_focused(False)

    def get_selected_agent(self) -> AgentState | None:
        """Get the currently highlighted agent."""
        if self.index is not None and 0 <= self.index < len(self._agents):
            return self._agents[self.index]
        return None

    def get_agent_by_number(self, num: int) -> AgentState | None:
        """Get an agent by its 1-based display number.

        Number keys: 1-9 map to rows 1-9, 0 maps to row 10.
        Returns None if the number is out of range.
        """
        if num == 0:
            num = 10
        idx = num - 1
        if 0 <= idx < len(self._agents):
            return self._agents[idx]
        return None

    def move_cursor(self, row: int) -> None:
        """Move the cursor to a specific row index."""
        if 0 <= row < len(self._agents):
            self.index = row

    def tick_animation(self, frame: int) -> None:
        """Advance the animation frame on all rows."""
        for child in self.children:
            if isinstance(child, SessionRow):
                child.set_anim_frame(frame)

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        """Post an AgentHighlighted message when the cursor moves."""
        agent = self.get_selected_agent()
        if agent:
            self.post_message(self.AgentHighlighted(agent))
