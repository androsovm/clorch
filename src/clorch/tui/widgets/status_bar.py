"""Status summary bar — replaces AsciiHeader + old StatusBar.

Left: "CLAUDE ORCH" branding. Right: W/I/[!]/[?]/E counts + "N agents".
"""
from __future__ import annotations

from textual.widgets import Static
from rich.text import Text

from clorch.state.models import StatusSummary
from clorch.constants import GREEN, RED, YELLOW, PINK, GREY, CYAN


class StatusBar(Static):
    """Compact status bar: branding left, aggregate counts right."""

    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        padding: 0 2;
        text-style: bold;
    }
    """

    def update_summary(self, summary: StatusSummary) -> None:
        text = Text()
        # Left: branding
        text.append("CLAUDE ORCH", style=f"bold {GREEN}")
        text.append("  ", style="dim")

        # Right: counts
        text.append("W:", style="dim")
        text.append(str(summary.working), style=f"bold {GREEN}")
        text.append("  I:", style="dim")
        text.append(str(summary.idle), style=f"{GREY}")
        text.append("  [!]:", style="dim")
        text.append(str(summary.waiting_permission), style=f"bold {RED}")
        text.append("  [?]:", style="dim")
        text.append(str(summary.waiting_answer), style=f"bold {YELLOW}")
        text.append("  E:", style="dim")
        text.append(str(summary.error), style=f"bold {PINK}")
        text.append("    ", style="dim")
        text.append(f"{summary.total} agents", style=f"bold {CYAN}")
        self.update(text)
