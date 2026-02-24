"""Action queue widget — letter-addressed items needing user attention."""
from __future__ import annotations

from textual.widget import Widget
from rich.text import Text

from clorch.state.models import ActionItem
from clorch.constants import RED, YELLOW, PINK, CYAN, GREEN, GREY


class ActionQueue(Widget):
    """Renders the action queue with [y]/[n]/[->] inline controls.

    Hidden (via ``hidden`` CSS class) when no actions are present.
    """

    DEFAULT_CSS = """
    ActionQueue {
        height: auto;
        max-height: 14;
        padding: 0 1;
    }
    ActionQueue.hidden {
        display: none;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._items: list[ActionItem] = []
        self._focused_letter: str | None = None

    def update_actions(self, items: list[ActionItem]) -> None:
        """Replace the action list and toggle visibility."""
        self._items = items
        # Clear focus if the focused item is gone
        if self._focused_letter:
            if not any(i.letter == self._focused_letter for i in items):
                self._focused_letter = None
        if items:
            self.remove_class("hidden")
        else:
            self.add_class("hidden")
        self.refresh()

    def set_focus(self, letter: str) -> None:
        """Focus an action by its assigned letter."""
        self._focused_letter = letter
        self.refresh()

    def clear_focus(self) -> None:
        """Clear the focused action."""
        self._focused_letter = None
        self.refresh()

    @property
    def focused_letter(self) -> str | None:
        return self._focused_letter

    def get_action(self, letter: str) -> ActionItem | None:
        """Look up an action by its assigned letter."""
        for item in self._items:
            if item.letter == letter:
                return item
        return None

    @property
    def has_approvable(self) -> bool:
        """True if any action is approvable (PERM status)."""
        return any(item.actionable for item in self._items)

    def render(self) -> Text:
        if not self._items:
            return Text("")

        text = Text()

        # Header line
        count = len(self._items)
        text.append(f"  ACTIONS ({count})", style=f"bold {CYAN}")
        if self.has_approvable:
            text.append("".rjust(40), style="dim")
            text.append("[Y]", style=f"bold {GREEN}")
            text.append(" approve all !", style="dim")
        text.append("\n")

        # Separate PERM items from non-PERM for visual grouping
        perm_items = [i for i in self._items if i.actionable]
        other_items = [i for i in self._items if not i.actionable]
        need_separator = bool(perm_items) and bool(other_items)

        for idx, item in enumerate(self._items):
            is_focused = self._focused_letter == item.letter

            # Determine type label and style
            if item.actionable:
                symbol = "[!]"
                type_label = "PERM"
                color = RED
                accent = "┃"
            elif item.agent.status.value == "WAITING_ANSWER":
                symbol = "[?]"
                type_label = "ASK "
                color = YELLOW
                accent = " "
            else:
                symbol = "[X]"
                type_label = "ERR "
                color = PINK
                accent = " "

            # Draw separator between PERM and non-PERM groups
            if need_separator and item == other_items[0]:
                text.append("  " + "─" * 70 + "\n", style=f"dim {GREY}")

            # Left accent for PERM items
            if item.actionable:
                text.append(f" {accent} ", style=f"bold {RED}")
            else:
                text.append("   ", style="dim")

            # Letter badge
            letter_style = f"bold {GREEN}" if is_focused else f"bold {CYAN}"
            text.append(f"[{item.letter}] ", style=letter_style)

            # Type label + symbol
            text.append(f"{symbol} ", style=f"bold {color}")
            text.append(f"{type_label}  ", style=f"bold {color}")

            # Project name
            project = item.agent.project_name or item.agent.session_id[:12]
            text.append(f"{project:<15s}", style="bold white")

            if is_focused and item.actionable:
                # Focused PERM: show full message (no truncation)
                summary = item.summary or ""
                text.append(f'"{summary}"', style="italic")
                text.append("\n")
                # Approval bar
                if item.actionable:
                    text.append(f" {accent} ", style=f"bold {RED}")
                else:
                    text.append("   ", style="dim")
                text.append("       >>> ", style=f"bold {GREEN}")
                text.append("APPROVE ", style=f"bold {GREEN}")
                text.append("[y]", style=f"bold reverse {GREEN}")
                text.append("  or  ", style="dim")
                text.append("DENY ", style=f"bold {RED}")
                text.append("[n]", style=f"bold reverse {RED}")
                text.append("  │  ", style="dim")
                text.append("[Esc]", style=f"bold {CYAN}")
                text.append(" cancel", style="dim")
                text.append("\n")
            else:
                # Normal row: truncated summary
                summary = item.summary[:80] if item.summary else ""
                text.append(f'"{summary}"', style="dim italic")

                # Controls
                if item.actionable:
                    pad = max(1, 50 - len(project) - min(len(summary), 80))
                    text.append(" " * pad)
                    text.append("[y]", style=f"bold {GREEN}")
                    text.append(" ", style="dim")
                    text.append("[n]", style=f"bold {RED}")
                    text.append(" ", style="dim")
                else:
                    pad = max(1, 58 - len(project) - min(len(summary), 80))
                    text.append(" " * pad)

                text.append("[->]", style=f"bold {CYAN}")
                text.append("\n")

        return text
