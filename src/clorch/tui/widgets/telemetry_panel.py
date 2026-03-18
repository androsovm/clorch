"""Telemetry panel — per-agent context gauge + activity sparkline."""
from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

from clorch.constants import (
    CYAN,
    GREEN,
    GREY,
    RED,
    SPARKLINE_CHARS,
    YELLOW,
    SubAgentStatus,
    context_pct_color,
    model_context_capacity,
)
from clorch.state.models import AgentState
from clorch.usage.models import SessionUsage

# Gauge bar width
_GAUGE_W = 8
# Sparkline width
_SPARKLINE_W = 15
# Agent name column width
_NAME_W = 12
# Max sub-agent rows per parent
_MAX_SUBAGENT_ROWS = 6


class TelemetryPanel(Static):
    """Displays gauge bars and sparklines for all agents."""

    def __init__(self, **kwargs) -> None:
        super().__init__("", **kwargs)
        self._usage_map: dict[str, SessionUsage] = {}

    def set_usage_map(self, usage_sessions: dict[str, SessionUsage]) -> None:
        """Set per-session usage data."""
        self._usage_map = usage_sessions

    def update_agents(
        self,
        agents: list[AgentState],
        selected_id: str | None,
        history_map: dict[str, list[int]],
    ) -> None:
        if not agents:
            self.update("")
            return

        text = Text()

        # Column header
        text.append(f"{'AGENT':<{_NAME_W}s} ", style=f"dim {GREY}")
        text.append(f"{'CONTEXT':^{_GAUGE_W + 2}s}", style=f"dim {GREY}")
        text.append("       ", style="dim")  # label gap
        text.append("ACTIVITY", style=f"dim {GREY}")
        text.append("\n")

        for i, agent in enumerate(agents):
            if i > 0:
                text.append("\n")

            # Agent name (highlighted if selected)
            name = (agent.project_name or agent.session_id[:_NAME_W])[:_NAME_W]
            is_selected = agent.session_id == selected_id
            name_style = "bold white" if is_selected else f"dim {GREY}"
            text.append(f"{name:<{_NAME_W}s}", style=name_style)
            text.append(" ")

            # Context gauge from real usage data, fallback to compact_count
            cc = agent.compact_count
            su = self._usage_map.get(agent.session_id)
            pct = su.tokens.context_window_pct(model_context_capacity(su.model)) if su else 0.0

            if pct > 0:
                filled = round(pct / 100 * _GAUGE_W)
                bar_color = context_pct_color(pct)
                label = f"{pct:.0f}%"
            else:
                # Fallback: compact_count proxy
                filled = min(cc, _GAUGE_W)
                if cc <= 1:
                    bar_color = GREEN
                elif cc <= 3:
                    bar_color = YELLOW
                else:
                    bar_color = RED
                label = f"{cc}c"

            bar = "\u2588" * filled + "\u2591" * (_GAUGE_W - filled)
            text.append("[", style=f"dim {GREY}")
            text.append(bar, style=bar_color)
            text.append("]", style=f"dim {GREY}")
            text.append(f" {label}", style=f"dim {GREY}")
            if pct > 0 and cc:
                text.append(f" {cc}c", style=f"dim {GREY}")
            text.append("  ")

            # Sparkline from extended history
            hist = history_map.get(agent.session_id, [])
            recent = hist[-_SPARKLINE_W:] if len(hist) >= _SPARKLINE_W else hist
            if not recent or max(recent) == 0:
                spark = "\u2581" * min(len(recent) or 1, _SPARKLINE_W)
                text.append(spark, style=f"dim {GREY}")
            else:
                max_val = max(recent)
                chars = []
                for v in recent:
                    idx = min(int(v / max(max_val, 1) * 7), 7)
                    chars.append(SPARKLINE_CHARS[idx])
                text.append("".join(chars), style=CYAN)

            # Warning icon at 4+ compacts
            if cc >= 4:
                text.append(" \u26a0", style=f"bold {RED}")

            # Sub-agent hierarchy (indented children)
            visible = agent.visible_subagents(limit=_MAX_SUBAGENT_ROWS)
            for sa in visible:
                text.append("\n")
                sa_name = (sa.agent_type or "?")[:_NAME_W - 2]
                if sa.status == SubAgentStatus.RUNNING:
                    text.append("  >>> ", style=f"bold {GREEN}")
                    text.append(f"{sa_name:<{_NAME_W - 2}s}", style=GREEN)
                    sa_suffix = sa.duration
                else:
                    text.append("  --- ", style=f"dim {GREY}")
                    text.append(f"{sa_name:<{_NAME_W - 2}s}", style=f"dim {GREY}")
                    sa_suffix = sa.duration + " \u2713"
                # Right-align duration where activity column is
                gap = _GAUGE_W + 10  # gauge + label + spacing
                text.append(f"{sa_suffix:>{gap}s}", style=f"dim {GREY}")

        self.update(text)
