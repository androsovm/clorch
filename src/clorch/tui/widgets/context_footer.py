"""Context-sensitive footer showing relevant keybindings."""
from __future__ import annotations

from textual.widgets import Static
from rich.text import Text

from clorch.constants import CYAN, GREEN, GREY, PINK, RED


class ContextFooter(Static):
    """Shows different keybindings depending on current state.

    Three tiers:
    - "default"  — no actions pending
    - "actions"  — actions pending, select with letter keys
    - "approval" — action selected, y/n/Esc prompt
    """

    DEFAULT_CSS = """
    ContextFooter {
        height: 1;
        color: #555555;
        padding: 0 1;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__("", **kwargs)
        self._mode = "default"

    def set_mode(self, mode: str) -> None:
        """Switch footer mode: 'default', 'actions', or 'approval'."""
        if mode == self._mode:
            return
        self._mode = mode
        self._render_footer()

    @property
    def mode(self) -> str:
        return self._mode

    def _render_footer(self) -> None:
        text = Text()

        if self._mode == "approval":
            # Tier 3: action selected — only approval keys
            text.append(" >>> ", style=f"bold {GREEN}")
            text.append("[y]", style=f"bold {GREEN}")
            text.append(" APPROVE  ", style=f"{GREY}")
            text.append("[n]", style=f"bold {RED}")
            text.append(" DENY  ", style=f"{GREY}")
            text.append("[Esc]", style=f"bold {CYAN}")
            text.append(" cancel", style=f"{GREY}")

        elif self._mode == "actions":
            # Tier 2: actions pending — action keys prominent
            text.append(" [a-z]", style=f"bold {CYAN}")
            text.append("select action ", style=f"{GREY}")
            text.append("[Y]", style=f"bold {GREEN}")
            text.append("approve all ", style=f"{GREY}")
            text.append("│ ", style=f"dim {GREY}")
            text.append("[j/k]", style=f"bold {CYAN}")
            text.append("nav ", style=f"{GREY}")
            text.append("[->]", style=f"bold {CYAN}")
            text.append("jump ", style=f"{GREY}")
            text.append("[?]", style=f"bold {CYAN}")
            text.append("help ", style=f"{GREY}")
            text.append("[q]", style=f"bold {CYAN}")
            text.append("uit", style=f"{GREY}")

        else:
            # Tier 1: default — navigation keys
            text.append(" [j/k]", style=f"bold {CYAN}")
            text.append("navigate ", style=f"{GREY}")
            text.append("[1-0]", style=f"bold {CYAN}")
            text.append("select ", style=f"{GREY}")
            text.append("[->]", style=f"bold {CYAN}")
            text.append("jump ", style=f"{GREY}")
            text.append("[d]", style=f"bold {CYAN}")
            text.append("detail ", style=f"{GREY}")
            text.append("[?]", style=f"bold {CYAN}")
            text.append("help ", style=f"{GREY}")
            text.append("[q]", style=f"bold {CYAN}")
            text.append("uit", style=f"{GREY}")

        self.update(text)
