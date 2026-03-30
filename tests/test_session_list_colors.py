"""Tests for session-list color handling and selection contrast."""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.app import App, ComposeResult

from clorch.constants import AgentStatus
from clorch.state.models import AgentState
from clorch.tui.widgets.session_list import (
    _SELECTED_DANGER,
    _SELECTED_ERROR,
    _SELECTED_MUTED,
    _SELECTED_ROW_BG,
    SessionList,
    SessionRow,
    _row_context_color,
    _row_status_color,
)


class SessionListColorApp(App):
    """Minimal app that loads the real TUI CSS for row-style assertions."""

    CSS_PATH = str(Path(__file__).resolve().parents[1] / "src/clorch/tui/app.tcss")

    def compose(self) -> ComposeResult:
        yield SessionList(id="session-list")


@pytest.mark.asyncio
async def test_selected_row_uses_custom_highlight_background():
    """Session rows should use the app's custom highlight, not Textual's ANSI blue."""
    async with SessionListColorApp().run_test() as pilot:
        session_list = pilot.app.query_one("#session-list", SessionList)
        session_list.update_agents(
            [AgentState(session_id="a1", project_name="Alpha", term_program="iTerm.app")]
        )
        await pilot.pause()

        row = session_list.query_one(SessionRow)
        assert row.highlighted is True
        assert row.styles.background.hex == _SELECTED_ROW_BG


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (AgentStatus.IDLE, _SELECTED_MUTED),
        (AgentStatus.WAITING_PERMISSION, _SELECTED_DANGER),
        (AgentStatus.ERROR, _SELECTED_ERROR),
    ],
)
def test_selected_status_colors_use_high_contrast_overrides(
    status: AgentStatus,
    expected: str,
):
    """Low-contrast statuses get brighter colors on selected rows."""
    assert _row_status_color(status, selected=True) == expected


def test_selected_context_red_uses_selected_danger_color():
    """Critical context usage keeps contrast on the selected-row background."""
    assert _row_context_color(80.0, selected=True) == _SELECTED_DANGER


def test_selected_perm_row_renders_selected_palette():
    """A highlighted PERM row should emit selected-state styles in the rendered text."""
    row = SessionRow(
        AgentState(
            session_id="a1",
            project_name="Alpha",
            status=AgentStatus.WAITING_PERMISSION,
            term_program="iTerm.app",
        ),
        row_num=1,
    )

    row.highlighted = True
    text = row._render_row()
    styles = {span.style for span in text.spans}

    assert f"bold {_SELECTED_DANGER}" in styles
    assert _SELECTED_MUTED in styles
