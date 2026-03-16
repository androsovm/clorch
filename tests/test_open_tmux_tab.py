"""Tests for OrchestratorApp._open_tmux_tab command construction."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestOpenTmuxTab:
    """Unit tests for _open_tmux_tab without a running Textual app.

    We instantiate OrchestratorApp.__new__ (bypassing __init__) and call
    the method directly, mocking out the terminal backend.
    """

    def _make_app(self):
        from clorch.tui.app import OrchestratorApp

        app = object.__new__(OrchestratorApp)
        return app

    def _make_tmux(self, session: str = "main") -> MagicMock:
        tmux = MagicMock()
        tmux.session = session
        return tmux

    def test_win_index_is_shell_quoted(self):
        """win_index must go through shlex.quote (security fix)."""
        app = self._make_app()
        tmux = self._make_tmux()

        with patch("clorch.terminal.get_backend") as mock_get:
            backend = MagicMock()
            backend.open_tab.return_value = True
            mock_get.return_value = backend

            app._open_tmux_tab(tmux, "mywindow", win_index="3")

        cmd = backend.open_tab.call_args[0][0]
        # win_index=3 should be quoted (shlex.quote("3") == "3" for simple values)
        assert "select-window -t" in cmd
        assert ":3" in cmd or ":'3'" in cmd

    def test_win_index_special_chars_quoted(self):
        """win_index with special chars must be safely quoted."""
        app = self._make_app()
        tmux = self._make_tmux()

        with patch("clorch.terminal.get_backend") as mock_get:
            backend = MagicMock()
            backend.open_tab.return_value = True
            mock_get.return_value = backend

            app._open_tmux_tab(tmux, "mywindow", win_index="3; rm -rf /")

        cmd = backend.open_tab.call_args[0][0]
        # The dangerous payload must be quoted, not executed as separate command
        assert "rm -rf" not in cmd or "'" in cmd
        # shlex.quote wraps in single quotes
        assert "'3; rm -rf /'" in cmd

    def test_no_win_index_uses_quoted_window(self):
        """Without win_index, the quoted window name is used for select-window."""
        app = self._make_app()
        tmux = self._make_tmux()

        with patch("clorch.terminal.get_backend") as mock_get:
            backend = MagicMock()
            backend.open_tab.return_value = True
            mock_get.return_value = backend

            app._open_tmux_tab(tmux, "mywindow")

        cmd = backend.open_tab.call_args[0][0]
        assert "select-window -t" in cmd
        assert ":mywindow" in cmd

    def test_title_passed_to_backend(self):
        """The window name is passed as title to the backend."""
        app = self._make_app()
        tmux = self._make_tmux()

        with patch("clorch.terminal.get_backend") as mock_get:
            backend = MagicMock()
            backend.open_tab.return_value = True
            mock_get.return_value = backend

            app._open_tmux_tab(tmux, "agent-project")

        backend.open_tab.assert_called_once()
        assert backend.open_tab.call_args[1]["title"] == "agent-project"

    def test_fallback_when_open_tab_fails(self):
        """When backend.open_tab returns False, falls back to select_window."""
        app = self._make_app()
        tmux = self._make_tmux()

        with patch("clorch.terminal.get_backend") as mock_get:
            backend = MagicMock()
            backend.open_tab.return_value = False
            mock_get.return_value = backend

            app._open_tmux_tab(tmux, "mywindow")

        tmux.select_window.assert_called_once_with("mywindow")
        backend.bring_to_front.assert_called_once()

    def test_monitor_starts_after_session_created(self):
        """Background monitor must launch after new-session to avoid race."""
        app = self._make_app()
        tmux = self._make_tmux()

        with patch("clorch.terminal.get_backend") as mock_get:
            backend = MagicMock()
            backend.open_tab.return_value = True
            mock_get.return_value = backend

            app._open_tmux_tab(tmux, "mywindow")

        cmd = backend.open_tab.call_args[0][0]
        new_session_pos = cmd.index("new-session -d")
        monitor_pos = cmd.index("(trap '' HUP;")
        assert new_session_pos < monitor_pos

    def test_linked_session_naming(self):
        """Linked session should be named session-window."""
        app = self._make_app()
        tmux = self._make_tmux(session="clorch")

        with patch("clorch.terminal.get_backend") as mock_get:
            backend = MagicMock()
            backend.open_tab.return_value = True
            mock_get.return_value = backend

            app._open_tmux_tab(tmux, "dev")

        cmd = backend.open_tab.call_args[0][0]
        assert "clorch-dev" in cmd
        assert "new-session -d -t clorch -s clorch-dev" in cmd

    def test_destroy_unattached_hook(self):
        """destroy-unattached should be set via client-attached hook."""
        app = self._make_app()
        tmux = self._make_tmux()

        with patch("clorch.terminal.get_backend") as mock_get:
            backend = MagicMock()
            backend.open_tab.return_value = True
            mock_get.return_value = backend

            app._open_tmux_tab(tmux, "mywindow")

        cmd = backend.open_tab.call_args[0][0]
        assert "set-hook" in cmd
        assert "client-attached" in cmd
        assert "destroy-unattached" in cmd
