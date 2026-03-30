"""Session list widget — ListView replacement for AgentTable (DataTable)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from rich.text import Text
from textual.app import ComposeResult
from textual.message import Message
from textual.widgets import ListItem, ListView, Static

from clorch.constants import (
    BRAILLE_SPINNER,
    CYAN,
    GREEN,
    GREY,
    PINK,
    RED,
    SPARKLINE_CHARS,
    STATUS_DISPLAY,
    YELLOW,
    AgentStatus,
    context_pct_color,
    model_context_capacity,
)
from clorch.state.models import ActionItem, AgentState
from clorch.terminal.detect import get_terminal_label, normalize_term_program
from clorch.usage.models import SessionUsage

_SELECTED_ROW_BG = "#434C5E"
_SELECTED_PRIMARY = "#ECEFF4"
_SELECTED_SECONDARY = "#D8DEE9"
_SELECTED_MUTED = "#B8C0CF"
_SELECTED_DANGER = "#E7A1A8"
_SELECTED_ERROR = "#E5C6DD"


@dataclass(frozen=True)
class _RowPalette:
    """Text styles for a list row.

    Selected rows need a separate palette because Rich span colors are not
    automatically adapted when the parent ListItem background changes.
    """

    primary: str
    primary_bold: str
    secondary_italic: str
    muted: str
    idle: str
    danger: str
    error: str


def _row_palette(selected: bool) -> _RowPalette:
    """Return the effective palette for a row."""
    if selected:
        return _RowPalette(
            primary=_SELECTED_PRIMARY,
            primary_bold=f"bold {_SELECTED_PRIMARY}",
            secondary_italic=f"italic {_SELECTED_SECONDARY}",
            muted=_SELECTED_MUTED,
            idle=_SELECTED_MUTED,
            danger=_SELECTED_DANGER,
            error=_SELECTED_ERROR,
        )
    return _RowPalette(
        primary="white",
        primary_bold="bold white",
        secondary_italic="dim italic",
        muted="dim",
        idle=GREY,
        danger=RED,
        error=PINK,
    )


def _row_status_color(status: AgentStatus, selected: bool) -> str:
    """Return a status color adapted for the current row state."""
    if not selected:
        return STATUS_DISPLAY[status][2]

    palette = _row_palette(True)
    if status == AgentStatus.IDLE:
        return palette.idle
    if status == AgentStatus.WAITING_PERMISSION:
        return palette.danger
    if status == AgentStatus.ERROR:
        return palette.error
    return STATUS_DISPLAY[status][2]


def _row_context_color(pct: float, selected: bool) -> str:
    """Return context percentage color adapted for selection."""
    if selected and pct >= 80:
        return _row_palette(True).danger
    return context_pct_color(pct)


def _visible_columns(width: int) -> set[str]:
    """Determine which optional columns fit in the given width.

    Core columns (accent, num, project, status, stale, tool) always shown (~50 chars).
    Optional columns are added from most to least important as width allows.
    """
    # Core: accent(2) + num(3) + sep(1) + project(16) + sep(1) + status(1+8) + stale(5)
    #       + tool(1+12) = 50
    core = 50
    cols: set[str] = set()
    budget = width - core

    # Add columns in priority order (most important first)
    col_costs = [
        ("session", 31),    # session name (30 + 1 sep)
        ("tcnt", 4),        # tool count
        ("ecnt", 3),        # error count
        ("uptime", 8),      # uptime
        ("ctx", 6),         # context %
        ("branch", 11),     # git branch (10 + 1 sep)
        ("sparkline", 12),  # sparkline (10 + 2 sep)
    ]
    for name, cost in col_costs:
        if budget >= cost:
            cols.add(name)
            budget -= cost
    return cols


class ListHeader(Static):
    """Column header row matching SessionRow column widths."""

    def on_mount(self) -> None:
        self._render_header()

    def on_resize(self) -> None:
        self._render_header()

    def _render_header(self) -> None:
        width = (getattr(self.size, "width", 120) or 120)
        cols = _visible_columns(width)
        text = Text()
        # Col 1: accent (2) + Col 2: num (3) + separator (1) = 6 chars
        text.append("      ", style="dim")
        # Col 3: project name (16) + separator (1)
        text.append(f"{'PROJECT':<16s} ", style=f"dim {GREY}")
        # Col 3a: session name (30) + separator (1)
        if "session" in cols:
            text.append(f"{'SESSION':<30s} ", style=f"dim {GREY}")
        # Col 4: status (1 space + 8)
        text.append(f" {'STATUS':<8s}", style=f"dim {GREY}")
        # Col 4b: stale (5)
        text.append(f"{'':5s}", style="dim")
        # Col 5: tool (1 space + 12)
        text.append(f" {'TOOL':<12s}", style=f"dim {GREY}")
        # Col 6: tool count (4)
        if "tcnt" in cols:
            text.append(f"{'#T':>4s}", style=f"dim {GREY}")
        # Col 7: error count (3)
        if "ecnt" in cols:
            text.append(f"{'#E':>3s}", style=f"dim {GREY}")
        # Col 8: uptime (8)
        if "uptime" in cols:
            text.append(f"{'UPTIME':>8s}", style=f"dim {GREY}")
        # Col 8b: context window % (6 chars: 1 space + 4 + 1)
        if "ctx" in cols:
            text.append(f" {'CTX':>4s} ", style=f"dim {GREY}")
        # Col 9: git branch (1 space + 10)
        if "branch" in cols:
            text.append(f" {'BRANCH':<10s}", style=f"dim {GREY}")
        # Col 10: sparkline (2 space + 10)
        if "sparkline" in cols:
            text.append(f"  {'ACTIVITY':<10s}", style=f"dim {GREY}")
        self.update(text)


class GroupSeparator(ListItem):
    """Non-selectable separator row showing a terminal group name."""

    DEFAULT_CSS = """
    GroupSeparator {
        height: auto;
        padding: 0 1;
    }
    """

    def __init__(self, label: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._label = label
        self.disabled = True

    def compose(self) -> ComposeResult:
        text = Text()
        text.append(f"── {self._label} ", style=f"dim {GREY}")
        text.append("─" * 40, style=f"dim {GREY}")
        yield Static(text, markup=False)


def _agent_terminal_group(agent: AgentState) -> str:
    """Compute the terminal group key for an agent.

    - If the agent has a ``tmux_window`` → group is ``"tmux"``.
    - Otherwise → normalized ``term_program`` label.
    """
    if agent.tmux_window:
        return "tmux"
    return normalize_term_program(agent.term_program)


def _group_sort_key(group: str, local_terminal: str) -> tuple[int, str]:
    """Sort key so local terminal comes first, tmux second, then alphabetical."""
    if group == local_terminal:
        return (0, group)
    if group == "tmux":
        return (1, group)
    return (2, group)


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

    def __init__(self, agent: AgentState, row_num: int, dim: bool = False,
                 ctx_pct: int = -1, **kwargs) -> None:
        super().__init__(**kwargs)
        self.agent = agent
        self._row_num = row_num
        self._dim = dim
        self._ctx_pct = ctx_pct  # -1 = no data
        self._action: ActionItem | None = None
        self._action_focused: bool = False
        self._anim_frame: int = 0

    def compose(self) -> ComposeResult:
        yield Static(self._render_row(), markup=False)

    def watch_highlighted(self, value: bool) -> None:
        """Refresh the row when ListView moves the highlight."""
        super().watch_highlighted(value)
        self._refresh_display()

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

    def update_row(self, agent: AgentState, row_num: int, dim: bool | None = None,
                   ctx_pct: int | None = None) -> None:
        """Update the row with new agent data."""
        self.agent = agent
        self._row_num = row_num
        if dim is not None:
            self._dim = dim
        if ctx_pct is not None:
            self._ctx_pct = ctx_pct
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
    _COL_PROJECT = 16   # project name padded
    _COL_SESSION = 30   # session name padded
    _COL_BRANCH = 10    # git branch padded
    _COL_STATUS = 8     # ">>> WORK" / "[!] PERM" — symbol(3) + space + label(4)
    _COL_STALE = 5      # stale age indicator
    _COL_TOOL = 12      # last tool name padded
    _COL_TCNT = 4       # tool count right-aligned
    _COL_ECNT = 3       # error count right-aligned
    _COL_UPTIME = 8     # "1h 23m" right-aligned
    _COL_CTX = 6         # context % " 52% " or "  -  "
    _COL_SPARK = 10     # sparkline chars

    @staticmethod
    def _compute_used_width(cols: set[str]) -> int:
        """Compute the total character width used by visible columns."""
        # Core: accent(2) + num(3) + sep(1) + project(16) + sep(1)
        #       + status(1+8) + stale(5) + tool(1+12) = 50
        w = 50
        if "session" in cols:
            w += 31  # 30 + 1 sep
        if "tcnt" in cols:
            w += 4
        if "ecnt" in cols:
            w += 3
        if "uptime" in cols:
            w += 8
        if "ctx" in cols:
            w += 6
        if "branch" in cols:
            w += 11  # 10 + 1 sep
        if "sparkline" in cols:
            w += 12  # 10 + 2 sep
        return w

    def _render_row(self) -> Text:
        """Render the row as Rich Text with responsive columns."""
        text = Text()
        agent = self.agent
        selected = self.highlighted
        palette = _row_palette(selected)

        content_width = (getattr(self.size, "width", 120) or 120) - 2  # padding: 0 1
        cols = _visible_columns(content_width)

        symbol, label, _ = STATUS_DISPLAY[agent.status]
        status_color = _row_status_color(agent.status, selected)

        # Animated symbol for WORKING: braille spinner (same width as ">>>")
        if agent.status == AgentStatus.WORKING:
            spinner_char = BRAILLE_SPINNER[self._anim_frame % len(BRAILLE_SPINNER)]
            symbol = f" {spinner_char} "

        # Col 1: Left accent (2 chars)
        if agent.status == AgentStatus.WAITING_PERMISSION:
            perm_color = palette.danger
            perm_style = (
                f"bold {perm_color}"
                if (self._anim_frame // 2) % 2 == 0
                else perm_color
            )
            text.append("\u2503 ", style=perm_style)
        elif agent.status == AgentStatus.WAITING_ANSWER:
            text.append("\u2503 ", style=f"bold {YELLOW}")
        elif agent.status == AgentStatus.ERROR:
            text.append("\u2503 ", style=f"bold {palette.error}")
        else:
            text.append("  ", style=palette.muted)

        # Col 2: Row number or action letter (3 chars)
        if self._action:
            letter_style = f"bold {GREEN}" if self._action_focused else f"bold {CYAN}"
            text.append(f"[{self._action.letter}]", style=letter_style)
        else:
            display_num = self._row_num if self._row_num <= 9 else 0
            text.append(f" {display_num} ", style=palette.muted)

        text.append(" ", style=palette.muted)

        # Col 3: Project name (fixed 16 chars) + separator (1)
        project = agent.project_name or agent.session_id[:12]
        if agent.subagent_count > 0:
            project = f"{project} [{agent.subagent_count}s]"
        text.append(
            f"{project:<{self._COL_PROJECT}s}"[:self._COL_PROJECT],
            style=palette.primary_bold,
        )
        text.append(" ", style=palette.muted)

        # Col 3a: Session name (fixed 30 chars) + separator (1)
        if "session" in cols:
            sess = (agent.session_name or "")[:self._COL_SESSION]
            text.append(
                f"{sess:<{self._COL_SESSION}s}"[:self._COL_SESSION],
                style=palette.secondary_italic,
            )
            text.append(" ", style=palette.muted)

        # Col 4: Status badge (fixed 8 chars: ">>> WORK", "[!] PERM")
        status_str = f"{symbol} {label:<4s}"
        text.append(f" {status_str:<{self._COL_STATUS}s}", style=f"bold {status_color}")

        # Col 4b: Stale indicator (fixed 5 chars) — only for WORKING status
        stale_str = ""
        if agent.status == AgentStatus.WORKING and agent.last_event_time:
            try:
                last_t = datetime.fromisoformat(agent.last_event_time.replace("Z", "+00:00"))
                age_s = (datetime.now(timezone.utc) - last_t).total_seconds()
                if age_s > 120:
                    mins = int(age_s) // 60
                    secs = int(age_s) % 60
                    stale_str = f"{mins}m{secs:02d}"[:5]
                    text.append(f"{stale_str:<5s}", style=f"bold {palette.danger}")
                elif age_s > 30:
                    stale_str = f"{int(age_s)}s"
                    text.append(f"{stale_str:<5s}", style=f"bold {YELLOW}")
                else:
                    text.append(" " * self._COL_STALE, style=palette.muted)
            except (ValueError, TypeError):
                text.append(" " * self._COL_STALE, style=palette.muted)
        else:
            text.append(" " * self._COL_STALE, style=palette.muted)

        # Col 5: Last tool (fixed 12 chars)
        tool = (agent.last_tool or "-")[:self._COL_TOOL]
        text.append(f" {tool:<{self._COL_TOOL}s}", style=palette.primary)

        # Col 6: Tool count (right-aligned 4 chars)
        if "tcnt" in cols:
            text.append(f"{agent.tool_count:>{self._COL_TCNT}d}", style=palette.muted)

        # Col 7: Error count (right-aligned 3 chars)
        if "ecnt" in cols:
            ecnt = f"{agent.error_count:>{self._COL_ECNT}d}"
            if agent.error_count > 0:
                text.append(ecnt, style=f"bold {palette.error}")
            else:
                text.append(ecnt, style=palette.muted)

        # Col 8: Uptime (right-aligned 8 chars)
        if "uptime" in cols:
            text.append(f"{agent.uptime:>{self._COL_UPTIME}s}", style=palette.muted)

        # Col 8b: Context window % (6 chars)
        if "ctx" in cols:
            if self._ctx_pct < 0:
                text.append(f"{'–':>5s} ", style=palette.muted)
            else:
                pct = min(self._ctx_pct, 100)
                text.append(f"{pct:>4d}%", style=f"bold {_row_context_color(float(pct), selected)}")
                text.append(" ", style=palette.muted)

        # Col 9: Git branch (1 space + fixed 10 chars)
        if "branch" in cols:
            branch = agent.git_branch or ""
            if branch:
                branch_display = branch[:self._COL_BRANCH - 1]
                if agent.git_dirty_count > 0:
                    branch_display = branch[:self._COL_BRANCH - 2] + "*"
                text.append(
                    f" {branch_display:<{self._COL_BRANCH}s}"[:self._COL_BRANCH + 1],
                    style=f"bold {CYAN}" if agent.git_dirty_count == 0 else f"bold {YELLOW}",
                )
            else:
                text.append(" " * (self._COL_BRANCH + 1), style=palette.muted)

        # Col 10: Sparkline (10 chars)
        if "sparkline" in cols:
            text.append("  ", style=palette.muted)
            sparkline = self._render_sparkline(agent.activity_history)
            text.append_text(sparkline)

        # Compute used width for notification/action hints
        used_width = self._compute_used_width(cols)
        remaining = content_width - used_width

        # Determine action hint width: "[y][n]" = 6, "[->]" = 4, plus 2 separator each
        hint_width = 0
        if self._action:
            hint_width = 8 if self._action.actionable else 6  # 2 sep + content

        msg = agent.notification_message or ""
        if remaining > hint_width and msg:
            msg_budget = remaining - hint_width - 2  # 2 for "  " separator before msg
            if msg_budget > 0:
                if len(msg) > msg_budget:
                    msg = msg[: max(msg_budget - 1, 0)] + "\u2026"
                text.append(f"  {msg}", style=palette.secondary_italic)

        if self._action and remaining >= hint_width:
            text.append("  ", style=palette.muted)
            if self._action.actionable:
                text.append("[y]", style=f"bold {GREEN}")
                text.append("[n]", style=f"bold {palette.danger}")
            else:
                text.append("[->]", style=f"bold {CYAN}")

        # Focused action expansion
        if self._action_focused and self._action and self._action.actionable:
            summary = self._action.summary or ""
            text.append(f'\n  "{summary}"', style=palette.secondary_italic)
            text.append("\n  >>> ", style=f"bold {GREEN}")
            text.append("[y]", style=f"bold reverse {GREEN}")
            text.append(" APPROVE  ", style=palette.muted)
            text.append("[n]", style=f"bold reverse {palette.danger}")
            text.append(" DENY  ", style=palette.muted)
            text.append("[Esc]", style=f"bold {CYAN}")
            text.append(" cancel", style=palette.muted)

        # Dim the entire row for unreachable agents (different terminal, not tmux)
        if self._dim and not selected:
            for i in range(len(text._spans)):
                text._spans[i] = text._spans[i]._replace(style=f"dim {GREY}")

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

    Agents are grouped by terminal emulator.  The local terminal's
    group appears first, then tmux, then other terminals alphabetically.
    Separator rows (``GroupSeparator``) are inserted between groups.
    Agents in unreachable terminals (not local, not tmux) are dimmed.
    """

    DEFAULT_CSS = """
    SessionList {
        height: 1fr;
        min-height: 8;
        scrollbar-size: 1 1;
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
        self._usage_map: dict[str, SessionUsage] = {}
        self._focused_letter: str | None = None
        # Mapping: child index → agent index (None for separators)
        self._child_to_agent: list[int | None] = []
        # Ordered agent list after grouping (used for external access)
        self._ordered_agents: list[AgentState] = []
        # Dim flags per ordered agent index
        self._dim_flags: list[bool] = []
        # Local terminal label (resolved once)
        self._local_terminal: str = get_terminal_label()
        # Whether the backend can map PIDs to tabs (False for Ghostty)
        self._backend_can_resolve: bool = self._check_backend_resolve()

    @property
    def ordered_agents(self) -> list[AgentState]:
        """Agents in current display order (after grouping/sorting)."""
        return self._ordered_agents

    @staticmethod
    def _check_backend_resolve() -> bool:
        """Check if the active terminal backend can map PIDs to tabs."""
        from clorch.terminal import get_backend
        backend = get_backend()
        return getattr(backend, "can_resolve_tabs", lambda: False)()

    def _is_group_reachable(self, group: str) -> bool:
        """Check if agents in a given terminal group are reachable.

        - Same terminal as us → reachable.
        - tmux → always reachable (via tmux select-window).
        - Unknown (no term_program) → reachable only if our backend
          can resolve tabs (iTerm/Terminal.app can, Ghostty cannot).
        - Known different terminal → not reachable.
        """
        if group == self._local_terminal or group == "tmux":
            return True
        if group == "unknown":
            return self._backend_can_resolve
        return False

    def _group_agents(self, agents: list[AgentState]) -> tuple[
        list[AgentState], list[int | None], list[bool], list[tuple[int, str]]
    ]:
        """Sort agents into terminal groups and compute child mapping.

        Returns:
            ordered_agents: agents in grouped + alphabetical order
            child_to_agent: mapping from child index to agent index (None for separators)
            dim_flags: whether each agent should be dimmed
            separators: list of (child_index, label) for separator insertion
        """
        local = self._local_terminal

        # Group agents by terminal
        groups: dict[str, list[AgentState]] = {}
        for agent in agents:
            group = _agent_terminal_group(agent)
            groups.setdefault(group, []).append(agent)

        # Sort each group alphabetically by project name
        for g in groups.values():
            g.sort(key=lambda a: a.project_name.lower())

        # Sort groups: local first, tmux second, then others alphabetically
        sorted_groups = sorted(groups.keys(), key=lambda g: _group_sort_key(g, local))

        ordered: list[AgentState] = []
        child_map: list[int | None] = []
        dim_flags: list[bool] = []
        separators: list[tuple[int, str]] = []

        # Only show separators when there are multiple groups
        show_separators = len(sorted_groups) > 1

        child_idx = 0
        for group in sorted_groups:
            group_agents = groups[group]
            if show_separators:
                label = group if group else "unknown"
                if group == local:
                    label = f"{label} (local)"
                separators.append((child_idx, label))
                child_map.append(None)
                child_idx += 1

            reachable = self._is_group_reachable(group)
            for agent in group_agents:
                agent_idx = len(ordered)
                ordered.append(agent)
                dim_flags.append(not reachable)
                child_map.append(agent_idx)
                child_idx += 1

        return ordered, child_map, dim_flags, separators

    def set_usage_map(self, usage_sessions: dict[str, SessionUsage]) -> None:
        """Set per-session usage data."""
        self._usage_map = usage_sessions

    def _ctx_pct_for(self, session_id: str) -> int:
        """Return context window % for a session, or -1 if no data."""
        su = self._usage_map.get(session_id)
        if su is None:
            return -1
        pct = su.tokens.context_window_pct(model_context_capacity(su.model))
        return int(pct)

    def update_agents(self, agents: list[AgentState]) -> None:
        """Refresh the list with grouped terminal sorting.

        Agents are grouped by terminal, with separator headers between groups.
        Updates existing rows in-place when possible to avoid flicker.
        """
        ordered, child_map, dim_flags, separators = self._group_agents(agents)

        new_ids = [a.session_id for a in ordered]
        old_ids = [a.session_id for a in self._ordered_agents]

        if new_ids == old_ids and len(child_map) == len(self._child_to_agent):
            # Same agents in same order — update in-place (no flicker)
            self._agents = agents
            self._ordered_agents = ordered
            self._child_to_agent = child_map
            self._dim_flags = dim_flags
            agent_num = 0
            for child in self.children:
                if isinstance(child, SessionRow):
                    agent = ordered[agent_num]
                    agent_num += 1
                    row_num = agent_num  # 1-based
                    child.update_row(agent, row_num, dim=dim_flags[agent_num - 1],
                                     ctx_pct=self._ctx_pct_for(agent.session_id))
                    action = self._action_map.get(agent.session_id)
                    child.set_action(action)
                    if action and self._focused_letter and action.letter == self._focused_letter:
                        child.set_action_focused(True)
                    else:
                        child.set_action_focused(False)
            return

        # Agent set or grouping changed — full rebuild
        prev_id: str | None = None
        if self._ordered_agents and self.index is not None:
            prev_agent = self.get_selected_agent()
            if prev_agent:
                prev_id = prev_agent.session_id

        self._agents = agents
        self._ordered_agents = ordered
        self._child_to_agent = child_map
        self._dim_flags = dim_flags

        self.clear()
        sep_iter = iter(separators)
        next_sep = next(sep_iter, None)
        agent_num = 0
        for child_idx, agent_idx in enumerate(child_map):
            if agent_idx is None:
                # Separator row
                if next_sep and next_sep[0] == child_idx:
                    self.append(GroupSeparator(next_sep[1]))
                    next_sep = next(sep_iter, None)
            else:
                agent = ordered[agent_idx]
                agent_num += 1
                dim = dim_flags[agent_idx]
                row = SessionRow(agent, agent_num, dim=dim,
                                 ctx_pct=self._ctx_pct_for(agent.session_id))
                action = self._action_map.get(agent.session_id)
                if action:
                    row.set_action(action)
                    if self._focused_letter and action.letter == self._focused_letter:
                        row.set_action_focused(True)
                self.append(row)

        # Restore cursor position by session_id, skipping separators.
        new_child_index = self._first_agent_child_index()
        if prev_id is not None:
            for ci, ai in enumerate(child_map):
                if ai is not None and ordered[ai].session_id == prev_id:
                    new_child_index = ci
                    break
        if ordered and new_child_index is not None:
            self.call_after_refresh(setattr, self, "index", new_child_index)

    def _first_agent_child_index(self) -> int | None:
        """Return the child index of the first actual agent row."""
        for ci, ai in enumerate(self._child_to_agent):
            if ai is not None:
                return ci
        return None

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
        """Get the currently highlighted agent (skipping separators)."""
        if self.index is not None and 0 <= self.index < len(self._child_to_agent):
            agent_idx = self._child_to_agent[self.index]
            if agent_idx is not None and agent_idx < len(self._ordered_agents):
                return self._ordered_agents[agent_idx]
        return None

    def get_agent_by_number(self, num: int) -> AgentState | None:
        """Get an agent by its 1-based display number.

        Number keys: 1-9 map to rows 1-9, 0 maps to row 10.
        Returns None if the number is out of range.
        """
        if num == 0:
            num = 10
        idx = num - 1
        if 0 <= idx < len(self._ordered_agents):
            return self._ordered_agents[idx]
        return None

    def move_cursor(self, row: int) -> None:
        """Move the cursor to the child index for the given agent index.

        Accounts for separator rows when translating agent index to
        child index.
        """
        # Find the child index for this agent index
        for ci, ai in enumerate(self._child_to_agent):
            if ai == row:
                self.index = ci
                return

    def move_cursor_to_agent(self, session_id: str) -> None:
        """Move the cursor to the child row for a given session_id."""
        for ci, ai in enumerate(self._child_to_agent):
            if ai is not None and self._ordered_agents[ai].session_id == session_id:
                self.index = ci
                return

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

    def is_agent_reachable(self, agent: AgentState) -> bool:
        """Check if an agent is reachable from the current terminal.

        Uses the same logic as grouping: local and tmux are always
        reachable; unknown agents are reachable only when the backend
        supports PID-to-tab mapping (iTerm yes, Ghostty no).
        """
        return self._is_group_reachable(_agent_terminal_group(agent))
