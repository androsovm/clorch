"""Tmux status bar widget renderer."""
from __future__ import annotations

from clorch.constants import THEME
from clorch.state.manager import StateManager
from clorch.state.models import StatusSummary


def render_status_widget() -> str:
    """Generate a tmux ``status-right`` string with agent status counts.

    Output uses tmux hex colour markup, for example::

        #[fg=#00FF88]orch#[default] #[fg=#00FF88]W:3  #[fg=#FF0040][!]:2  …

    Zero-count segments are omitted.  If no agents are running, returns
    an empty string so tmux shows nothing.
    """
    mgr = StateManager()
    summary: StatusSummary = mgr.get_summary()

    if summary.total == 0:
        return ""

    parts: list[str] = []

    if summary.working:
        parts.append(f"#[fg={THEME['green']}]W:{summary.working}")

    if summary.waiting_permission:
        parts.append(f"#[fg={THEME['red']}][!]:{summary.waiting_permission}")

    if summary.waiting_answer:
        parts.append(f"#[fg={THEME['yellow']}][?]:{summary.waiting_answer}")

    if summary.error:
        parts.append(f"#[fg={THEME['pink']}]E:{summary.error}")

    if summary.idle:
        parts.append(f"#[fg={THEME['grey']}]I:{summary.idle}")

    status = " ".join(parts)
    return f"#[fg={THEME['cyan']}]orch#[default] {status}#[default]"


def print_status_widget() -> None:
    """Print the widget string to stdout for tmux to consume."""
    print(render_status_widget())


# Allow tmux to call this directly:
#   set -g status-right '#(python -m clorch.tmux.statusbar)'
if __name__ == "__main__":
    print_status_widget()
