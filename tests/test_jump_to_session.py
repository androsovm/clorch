"""Tests for OrchestratorApp._jump_to_session tmux tab-jump branching.

Covers the fix for shared-tmux-session tab corruption: jump_to_tmux_tab is
called before select_tmux_pane, and select_tmux_pane is skipped entirely when
jump_to_tmux_tab succeeds (avoids session-wide select-window side-effects).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from clorch.state.models import AgentState


def _make_agent(
    tmux_window: str = "cre-1",
    tmux_session: str = "claude",
    tmux_pane: str = "",
    pid: int = 12345,
    project_name: str = "cre-project",
    session_id: str = "sess-abc",
) -> AgentState:
    return AgentState(
        session_id=session_id,
        project_name=project_name,
        tmux_window=tmux_window,
        tmux_session=tmux_session,
        tmux_pane=tmux_pane,
        pid=pid,
    )


def _make_app():
    from clorch.tui.app import OrchestratorApp
    app = object.__new__(OrchestratorApp)
    app.notify = MagicMock()  # type: ignore[attr-defined]
    return app


class TestJumpToSessionTmuxBranch:
    """Unit tests for the tmux path of _jump_to_session."""

    def _run(self, app, agent, *, tab_found: bool, pane_selected: bool):
        """Run _jump_to_session with the tmux navigator functions mocked.

        Patches are applied at the source modules because the functions are
        lazy-imported inside _jump_to_session.
        """
        table_mock = MagicMock()
        table_mock.is_agent_reachable.return_value = True

        with (
            patch.object(type(app), "query_one", return_value=table_mock),
            patch("clorch.tmux.navigator.pid_alive", return_value=True),
            patch("clorch.tmux.session.TmuxSession"),
            patch("clorch.tmux.navigator.jump_to_tmux_tab", return_value=tab_found) as mock_tab,
            patch(
                "clorch.tmux.navigator.select_tmux_pane", return_value=pane_selected
            ) as mock_pane,
            patch("clorch.tmux.navigator.bring_terminal_to_front") as mock_front,
            patch("clorch.tmux.navigator.jump_to_tab", return_value=False),
        ):
            app._jump_to_session(agent)
            return mock_tab, mock_pane, mock_front

    def test_tab_found_skips_select_window(self):
        """When jump_to_tmux_tab succeeds, select_tmux_pane must NOT be called.

        Calling select-window in a shared session corrupts other clients' views.
        """
        app = _make_app()
        agent = _make_agent()
        mock_tab, mock_pane, _ = self._run(app, agent, tab_found=True, pane_selected=False)

        mock_tab.assert_called_once()
        mock_pane.assert_not_called()

    def test_tab_found_brings_terminal_to_front(self):
        """When jump_to_tmux_tab succeeds, terminal must be raised."""
        app = _make_app()
        agent = _make_agent()
        _, _, mock_front = self._run(app, agent, tab_found=True, pane_selected=False)

        mock_front.assert_called_once()

    def test_tab_found_notifies(self):
        """When jump_to_tmux_tab succeeds, user sees a 'Jumped to' notification."""
        app = _make_app()
        agent = _make_agent()
        self._run(app, agent, tab_found=True, pane_selected=False)

        app.notify.assert_called_once()
        assert "Jumped" in app.notify.call_args[0][0]

    def test_fallback_calls_select_pane_when_tab_not_found(self):
        """When jump_to_tmux_tab fails, select_tmux_pane is called as fallback."""
        app = _make_app()
        agent = _make_agent()
        mock_tab, mock_pane, _ = self._run(app, agent, tab_found=False, pane_selected=True)

        mock_tab.assert_called_once()
        mock_pane.assert_called_once_with(agent)

    def test_fallback_brings_terminal_to_front(self):
        """When select_tmux_pane fallback succeeds, terminal must also be raised."""
        app = _make_app()
        agent = _make_agent()
        _, _, mock_front = self._run(app, agent, tab_found=False, pane_selected=True)

        mock_front.assert_called_once()

    def test_fallback_notifies(self):
        """When select_tmux_pane fallback succeeds, user sees a notification."""
        app = _make_app()
        agent = _make_agent()
        self._run(app, agent, tab_found=False, pane_selected=True)

        app.notify.assert_called_once()
        assert "Jumped" in app.notify.call_args[0][0]

    def test_no_tmux_window_skips_tmux_path(self):
        """Agents without tmux_window bypass the tmux branch entirely."""
        app = _make_app()
        agent = _make_agent(tmux_window="")
        mock_tab, mock_pane, mock_front = self._run(
            app, agent, tab_found=False, pane_selected=False
        )

        mock_tab.assert_not_called()
        mock_pane.assert_not_called()

    def test_both_strategies_fail_no_jumped_notification(self):
        """When both tmux strategies fail, no 'Jumped' notification is shown."""
        app = _make_app()
        agent = _make_agent()
        self._run(app, agent, tab_found=False, pane_selected=False)

        jumped_calls = [
            c for c in app.notify.call_args_list
            if "Jumped" in (c[0][0] if c[0] else "")
        ]
        assert not jumped_calls


class TestJumpToSessionDeadProcess:
    """Dead-process path uses StateManager.remove_session() (not direct file access)."""

    def test_dead_process_calls_remove_session(self):
        """When the agent PID is dead, remove_session() is called on the manager."""
        from clorch.tui.app import OrchestratorApp

        app = object.__new__(OrchestratorApp)
        app.notify = MagicMock()  # type: ignore[attr-defined]
        app._manager = MagicMock()

        agent = _make_agent(pid=99999)
        table_mock = MagicMock()
        table_mock.is_agent_reachable.return_value = True

        with (
            patch.object(type(app), "query_one", return_value=table_mock),
            patch("clorch.tmux.navigator.pid_alive", return_value=False),
        ):
            app._jump_to_session(agent)

        app._manager.remove_session.assert_called_once_with(agent.session_id)
        app.notify.assert_called_once()
        assert "dead" in app.notify.call_args[0][0]
