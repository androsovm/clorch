"""Tests for EventLog widget eviction logic."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from clorch.tui.widgets.event_log import MAX_EVENTS, EventLog


class EventLogApp(App):
    """Minimal app hosting an EventLog for testing."""

    def compose(self) -> ComposeResult:
        yield EventLog(id="log")


@pytest.mark.asyncio
async def test_eviction_caps_at_max_events():
    """After MAX_EVENTS+5 writes, exactly MAX_EVENTS entries remain."""
    async with EventLogApp().run_test() as pilot:
        log = pilot.app.query_one("#log", EventLog)
        total = MAX_EVENTS + 5
        for i in range(total):
            log.write_event("agent", ">>", f"msg-{i}", "green")
        await pilot.pause()

        assert log.event_count == MAX_EVENTS
        entries = log.query(".event-entry")
        assert len(entries) == MAX_EVENTS


@pytest.mark.asyncio
async def test_oldest_entry_evicted_first():
    """The oldest (bottom) entry is evicted, newest stays at top."""
    async with EventLogApp().run_test() as pilot:
        log = pilot.app.query_one("#log", EventLog)
        for i in range(MAX_EVENTS + 3):
            log.write_event("agent", ">>", f"msg-{i}", "green")
        await pilot.pause()

        # Newest entry is first in the deque (mounted at top)
        newest = log._entries[0]
        oldest = log._entries[-1]
        # msg-{MAX_EVENTS+2} is the newest
        assert f"msg-{MAX_EVENTS + 2}" in str(newest.render())
        # The oldest surviving should be msg-3 (0,1,2 were evicted)
        assert "msg-3" in str(oldest.render())
