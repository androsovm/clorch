"""Event log panel — streaming event log from all agents."""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone

from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import Static

from clorch.constants import GREY, THEME

MAX_EVENTS = 200


class EventLog(VerticalScroll):
    """Scrolling event log with colored entries, newest on top."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.can_focus = True
        self._entries: deque[Static] = deque()

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
        if self._entries:
            self.mount(entry, before=self._entries[0])
        else:
            self.mount(entry)
        self._entries.appendleft(entry)
        self.set_timer(1.5, lambda: entry.remove_class("event-new"))

        while len(self._entries) > MAX_EVENTS:
            old = self._entries.pop()
            old.remove()

    @property
    def event_count(self) -> int:
        """Number of entries currently tracked."""
        return len(self._entries)

    def clear(self) -> None:
        """Remove all event entries."""
        for child in self._entries:
            child.remove()
        self._entries.clear()
