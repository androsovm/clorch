"""Event log panel — streaming event log from all agents."""
from __future__ import annotations

from datetime import datetime, timezone

from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import Static

from clorch.constants import GREY, THEME

MAX_EVENTS = 200


class EventLog(VerticalScroll):
    """Scrolling event log with colored entries, newest on top."""

    _event_count: int = 0

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.can_focus = True

    def write_event(
        self,
        agent_name: str,
        icon: str,
        message: str,
        color: str,
    ) -> None:
        hex_color = THEME.get(color, color)
        now = datetime.now(timezone.utc).strftime("%H:%M:%S")
        text = Text()
        text.append(now, style=f"dim {GREY}")
        text.append("  ")
        text.append(f"{agent_name:<12s}", style="white")
        text.append("  ")
        text.append(icon, style=hex_color)
        text.append(" ")
        text.append(message, style=hex_color)

        entry = Static(text, classes="event-entry event-new")
        children = self.query(".event-entry")
        if children:
            self.mount(entry, before=children.first())
        else:
            self.mount(entry)
        self.set_timer(1.5, lambda: entry.remove_class("event-new"))

        self._event_count += 1
        if self._event_count > MAX_EVENTS:
            last = children.last()
            if last is not None:
                last.remove()
                self._event_count -= 1

    def clear(self) -> None:
        """Remove all event entries."""
        for child in self.query(".event-entry"):
            child.remove()
        self._event_count = 0
