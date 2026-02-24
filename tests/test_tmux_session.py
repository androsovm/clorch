"""Tests for TmuxSession.send_keys() and get_pane_target()."""
from __future__ import annotations

import subprocess
from unittest.mock import patch, MagicMock

import pytest

from clorch.tmux.session import TmuxSession


class TestSendKeys:
    """Tests for TmuxSession.send_keys()."""

    def test_send_keys_literal(self):
        """Literal mode passes -l flag."""
        tmux = TmuxSession(session_name="test")
        with patch.object(tmux, "run_command") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = tmux.send_keys("test:win.0", "y", literal=True)

        assert result is True
        mock_run.assert_called_once_with(
            "send-keys", "-t", "test:win.0", "-l", "y", check=False,
        )

    def test_send_keys_special(self):
        """Non-literal mode sends special key names (e.g. Enter)."""
        tmux = TmuxSession(session_name="test")
        with patch.object(tmux, "run_command") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = tmux.send_keys("test:win.0", "Enter")

        assert result is True
        mock_run.assert_called_once_with(
            "send-keys", "-t", "test:win.0", "Enter", check=False,
        )

    def test_send_keys_failure(self):
        """Returns False when tmux command fails."""
        tmux = TmuxSession(session_name="test")
        with patch.object(tmux, "run_command") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            result = tmux.send_keys("test:win.0", "y")

        assert result is False


class TestGetPaneTarget:
    """Tests for TmuxSession.get_pane_target()."""

    def test_default_pane(self):
        """Default pane is '0'."""
        tmux = TmuxSession(session_name="claude")
        assert tmux.get_pane_target("mywin") == "claude:mywin.0"

    def test_custom_pane(self):
        """Custom pane number is included."""
        tmux = TmuxSession(session_name="sess")
        assert tmux.get_pane_target("backend", pane="2") == "sess:backend.2"
