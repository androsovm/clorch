"""Styled header bar with Unicode separators, tmux session name, and counts."""
from __future__ import annotations

import time

from textual.widgets import Static
from rich.text import Text

from clorch.state.models import StatusSummary
from clorch.constants import GREEN, RED, YELLOW, PINK, GREY, CYAN, BRAILLE_SPINNER


class HeaderBar(Static):
    """1-line header: CLORCH --- tmux:session --- counts --- N agents."""

    DEFAULT_CSS = """
    HeaderBar {
        height: 1;
        padding: 0 1;
        text-style: bold;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(Text(" CLORCH", style=f"bold {GREEN}"), **kwargs)
        self._tmux_session: str = ""
        self._anim_frame: int = 0
        self._summary: StatusSummary | None = None
        # tools/min tracking
        self._prev_total_tools: int = 0
        self._prev_time: float = time.monotonic()
        self._tools_per_min: float = 0.0

    def set_tmux_session(self, name: str) -> None:
        """Set the tmux session name for display."""
        self._tmux_session = name

    def tick_animation(self, frame: int) -> None:
        """Advance animation frame and re-render if there are working agents."""
        self._anim_frame = frame
        if self._summary and self._summary.working > 0:
            self._refresh_display()

    def update_summary(self, summary: StatusSummary) -> None:
        self._summary = summary
        # Compute tools/min delta rate
        now = time.monotonic()
        elapsed = now - self._prev_time
        if elapsed >= 3.0:  # Update rate every 3+ seconds to avoid jitter
            delta_tools = summary.total_tools - self._prev_total_tools
            if delta_tools >= 0:
                self._tools_per_min = delta_tools / elapsed * 60.0
            self._prev_total_tools = summary.total_tools
            self._prev_time = now
        self._refresh_display()

    def _refresh_display(self) -> None:
        summary = self._summary
        if summary is None:
            return
        text = Text()

        # Branding
        text.append(" CLORCH", style=f"bold {GREEN}")
        text.append(" \u2500\u2500\u2500 ", style=f"dim {GREY}")

        # tmux session name (if available)
        if self._tmux_session:
            text.append(self._tmux_session, style=f"{CYAN}")
            text.append(" \u2500\u2500\u2500 ", style=f"dim {GREY}")

        # Status counts — full words
        if summary.working > 0:
            spinner = BRAILLE_SPINNER[self._anim_frame % len(BRAILLE_SPINNER)]
            text.append(f"{spinner} ", style=f"bold {GREEN}")
        text.append("Working: ", style="dim")
        text.append(str(summary.working), style=f"bold {GREEN}")
        text.append(" \u2502 ", style=f"dim {GREY}")

        text.append("Idle: ", style="dim")
        text.append(str(summary.idle), style=f"{GREY}")
        text.append(" \u2502 ", style=f"dim {GREY}")

        text.append("Perm: ", style="dim")
        text.append(str(summary.waiting_permission), style=f"bold {RED}")
        text.append(" \u2502 ", style=f"dim {GREY}")

        text.append("Ask: ", style="dim")
        text.append(str(summary.waiting_answer), style=f"bold {YELLOW}")
        text.append(" \u2502 ", style=f"dim {GREY}")

        text.append("Errors: ", style="dim")
        text.append(str(summary.error), style=f"bold {PINK}")

        # tools/min rate
        if self._tools_per_min >= 1.0:
            text.append(" \u2502 ", style=f"dim {GREY}")
            text.append(f"{int(self._tools_per_min)} t/m", style="dim")

        # Agent total
        text.append(" \u2500\u2500\u2500 ", style=f"dim {GREY}")
        text.append(f"{summary.total} agents", style=f"bold {CYAN}")

        self.update(text)
