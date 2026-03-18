"""Agent detail panel — bottom panel showing agent info or PERM details."""

from __future__ import annotations

from datetime import datetime, timezone

from rich.text import Text
from textual.widgets import Static

from clorch.constants import (
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
from clorch.state.models import AgentState
from clorch.usage.models import SessionUsage

# Label column width for alignment
_LABEL_W = 12
# Context window gauge bar width
_CTX_GAUGE_W = 16


class AgentDetail(Static):
    """Shows detailed information about the selected agent.

    When the agent is WAITING_PERMISSION and has a tool_request_summary,
    renders a special PERM view with syntax-highlighted request details.
    Otherwise renders the normal key-value detail view.
    """

    DEFAULT_CSS = """
    AgentDetail {
        height: auto;
        max-height: 12;
        padding: 0 1;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__("", **kwargs)
        self._agent: AgentState | None = None
        self._session_usage: SessionUsage | None = None

    def set_usage(self, session_usage: SessionUsage | None) -> None:
        """Set per-agent usage data (SessionUsage or None)."""
        self._session_usage = session_usage
        # Re-render if we have an agent displayed
        if self._agent is not None:
            self.show_agent(self._agent)

    def show_agent(self, agent: AgentState | None) -> None:
        self._agent = agent
        if agent is None:
            self.update("")
            return

        if agent.status == AgentStatus.WAITING_PERMISSION and agent.tool_request_summary:
            self._render_perm_view(agent)
        else:
            self._render_normal_view(agent)

    def _render_perm_view(self, agent: AgentState) -> None:
        """Render PERM request detail with syntax highlighting."""
        text = Text()

        # Header: [!] PERM  project_name  session_name  ToolName
        text.append("[!] PERM", style=f"bold {RED}")
        text.append("  ", style="dim")
        text.append(agent.project_name or agent.session_id[:12], style="bold white")
        if agent.session_name:
            text.append(f"  {agent.session_name[:40]}", style="dim italic")
        text.append("  ", style="dim")
        text.append(agent.last_tool or "?", style=f"bold {YELLOW}")
        text.append("\n")

        # Body: summary with syntax highlighting
        summary = agent.tool_request_summary or ""
        for line in summary.split("\n")[:6]:  # cap to 6 lines
            if line.startswith("$ "):
                text.append(line, style=f"bold {GREEN}")
            elif line.startswith("- "):
                text.append(line, style=RED)
            elif line.startswith("+ "):
                text.append(line, style=GREEN)
            elif line.startswith("/") or line.startswith("~"):
                text.append(line, style=CYAN)
            else:
                text.append(line, style="white")
            text.append("\n")

        # Footer: action hints
        text.append("[y]", style=f"bold reverse {GREEN}")
        text.append(" APPROVE  ", style="dim")
        text.append("[n]", style=f"bold reverse {RED}")
        text.append(" DENY  ", style="dim")
        text.append("[->]", style=f"bold {CYAN}")
        text.append(" jump", style="dim")

        self.update(text)

    def _render_normal_view(self, agent: AgentState) -> None:
        """Render normal key-value detail view."""
        symbol, label, color = STATUS_DISPLAY[agent.status]

        text = Text()

        # Project name + session name
        text.append(agent.project_name or agent.session_id[:12], style="bold white")
        if agent.session_name:
            text.append(f"  {agent.session_name[:60]}", style="dim italic")
        text.append("\n")

        # Status + Uptime
        text.append(f"{'Status':<{_LABEL_W}s}", style=f"dim {GREY}")
        text.append(f"{symbol} {label}", style=f"bold {color}")
        text.append("    ", style="dim")
        text.append(f"{'Uptime':<8s}", style=f"dim {GREY}")
        text.append(f"{agent.uptime}", style="white")
        text.append("\n")

        # Path
        if agent.cwd:
            # Shorten home directory
            path = agent.cwd.replace("/Users/", "~/", 1)
            if path.startswith("~/"):
                # Further shorten: ~/username/... -> ~/...
                parts = path.split("/", 2)
                if len(parts) >= 3:
                    path = "~/" + parts[2]
            text.append(f"{'Path':<{_LABEL_W}s}", style=f"dim {GREY}")
            text.append(f"{path}", style=GREEN)
            text.append("\n")

        # Git info
        if agent.git_branch:
            text.append(f"{'Git':<{_LABEL_W}s}", style=f"dim {GREY}")
            text.append(agent.git_branch, style=f"bold {CYAN}")
            if agent.git_dirty_count > 0:
                text.append(f" ({agent.git_dirty_count} dirty)", style=f"bold {YELLOW}")
            else:
                text.append(" \u2713", style=f"dim {GREEN}")
            text.append("\n")

        # Last event age
        if agent.last_event_time:
            try:
                last_t = datetime.fromisoformat(agent.last_event_time.replace("Z", "+00:00"))
                age_s = (datetime.now(timezone.utc) - last_t).total_seconds()
                text.append(f"{'Last event':<{_LABEL_W}s}", style=f"dim {GREY}")
                if age_s > 120:
                    mins = int(age_s) // 60
                    secs = int(age_s) % 60
                    text.append(f"{mins}m{secs:02d}s ago", style=f"bold {RED}")
                elif age_s > 30:
                    text.append(f"{int(age_s)}s ago", style=f"bold {YELLOW}")
                else:
                    text.append(f"{int(age_s)}s ago", style=GREEN)
                text.append("\n")
            except (ValueError, TypeError):
                pass

        # Model + Last tool
        text.append(f"{'Model':<{_LABEL_W}s}", style=f"dim {GREY}")
        text.append(f"{agent.model or '-'}", style=CYAN)
        if agent.last_tool:
            text.append("    ", style="dim")
            text.append(f"{'Last tool':<10s}", style=f"dim {GREY}")
            text.append(f"{agent.last_tool}", style="white")
        text.append("\n")

        # Counts line: Tools, Errors, Subagents, Compacts, Tasks
        text.append(f"{'Tools':<{_LABEL_W}s}", style=f"dim {GREY}")
        text.append(f"{agent.tool_count}", style="white")
        text.append("    ", style="dim")
        text.append("Errors ", style=f"dim {GREY}")
        text.append(
            f"{agent.error_count}",
            style=f"bold {PINK}" if agent.error_count else f"dim {GREY}",
        )
        if agent.subagent_count:
            text.append("    ", style="dim")
            text.append("Subs ", style=f"dim {GREY}")
            text.append(f"{agent.subagent_count}", style=CYAN)
        if agent.compact_count:
            text.append("    ", style="dim")
            text.append("Compacts ", style=f"dim {GREY}")
            text.append(f"{agent.compact_count}", style=PINK)
        if agent.task_completed_count:
            text.append("    ", style="dim")
            text.append("Tasks ", style=f"dim {GREY}")
            text.append(f"{agent.task_completed_count}", style=GREEN)
        text.append("\n")

        # Token usage line (if data available)
        if self._session_usage is not None:
            su = self._session_usage
            text.append(f"{'Tokens':<{_LABEL_W}s}", style=f"dim {GREY}")
            text.append(self._fmt_tokens(su.tokens.total_input), style="white")
            text.append(" in", style="dim")
            text.append(" / ", style=f"dim {GREY}")
            text.append(self._fmt_tokens(su.tokens.output_tokens), style="white")
            text.append(" out", style="dim")
            if su.cost >= 0.01:
                text.append("  ~$", style="dim")
                text.append(f"{su.cost:.2f}", style=f"bold {GREEN}")
            text.append("\n")

            # Context window gauge (last message = current context size)
            capacity = model_context_capacity(su.model)
            pct = su.tokens.context_window_pct(capacity)
            filled = round(pct / 100 * _CTX_GAUGE_W)
            bar = "\u2588" * filled + "\u2591" * (_CTX_GAUGE_W - filled)
            bar_color = context_pct_color(pct)
            text.append(f"{'Context':<{_LABEL_W}s}", style=f"dim {GREY}")
            text.append(f"[{bar}]", style=bar_color)
            text.append(f" {pct:.0f}%", style=f"bold {bar_color}")
            if agent.compact_count:
                text.append(f" ({agent.compact_count}c)", style=f"dim {PINK}")
            text.append("\n")

        # Extended sparkline (use all available history, up to 20 chars)
        text.append(f"{'Activity':<{_LABEL_W}s}", style=f"dim {GREY}")
        sparkline = self._render_extended_sparkline(agent.activity_history)
        text.append_text(sparkline)
        text.append("\n")

        # Notification message
        if agent.notification_message:
            text.append(f"{'Msg':<{_LABEL_W}s}", style=f"dim {GREY}")
            msg = agent.notification_message
            if len(msg) > 80:
                msg = msg[:78] + ".."
            text.append(f'"{msg}"', style=f"italic {YELLOW}")

        self.update(text)

    @staticmethod
    def _fmt_tokens(n: int) -> str:
        """Format token count: 1234567 -> '1.2M', 12345 -> '12K', 999 -> '999'."""
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M"
        if n >= 1_000:
            return f"{n / 1_000:.0f}K"
        return str(n)

    @staticmethod
    def _render_extended_sparkline(history: list[int]) -> Text:
        """Render an extended sparkline (up to 20 chars)."""
        # Use up to 20 most recent data points
        recent = history[-20:] if len(history) >= 20 else history
        if not recent or max(recent) == 0:
            return Text("\u2581" * min(len(recent), 20), style=f"dim {GREY}")
        max_val = max(recent)
        chars = []
        for v in recent:
            idx = min(int(v / max(max_val, 1) * 7), 7)
            chars.append(SPARKLINE_CHARS[idx])
        return Text("".join(chars), style=CYAN)
