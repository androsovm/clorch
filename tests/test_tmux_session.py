"""Tests for TmuxSession.send_keys() and get_pane_target()."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

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


# ------------------------------------------------------------------
# _is_safe_tmux_name()
# ------------------------------------------------------------------


class TestIsSafeTmuxName:
    """Tests for the _is_safe_tmux_name validation helper."""

    def test_plain_name_is_safe(self):
        from clorch.tmux.navigator import _is_safe_tmux_name
        assert _is_safe_tmux_name("cre-1") is True

    def test_alphanumeric_with_underscore_is_safe(self):
        from clorch.tmux.navigator import _is_safe_tmux_name
        assert _is_safe_tmux_name("my_window_2") is True

    def test_empty_string_is_unsafe(self):
        from clorch.tmux.navigator import _is_safe_tmux_name
        assert _is_safe_tmux_name("") is False

    def test_colon_is_unsafe(self):
        """Colon is the tmux session:window separator — must be rejected."""
        from clorch.tmux.navigator import _is_safe_tmux_name
        assert _is_safe_tmux_name("other:window") is False

    def test_double_quote_is_unsafe(self):
        from clorch.tmux.navigator import _is_safe_tmux_name
        assert _is_safe_tmux_name('win"name') is False

    def test_single_quote_is_unsafe(self):
        from clorch.tmux.navigator import _is_safe_tmux_name
        assert _is_safe_tmux_name("win'name") is False

    def test_numeric_index_is_safe(self):
        from clorch.tmux.navigator import _is_safe_tmux_name
        assert _is_safe_tmux_name("3") is True


class TestSelectTmuxPaneValidation:
    """select_tmux_pane must reject unsafe window targets."""

    def test_rejects_colon_in_window_name(self):
        """A window name containing ':' would corrupt the tmux target — must return False."""
        from clorch.state.models import AgentState
        from clorch.tmux.navigator import select_tmux_pane

        agent = AgentState(
            session_id="s",
            tmux_window="evil:session",
            tmux_session="claude",
        )
        with patch("clorch.tmux.navigator.TmuxSession") as mock_cls:
            mock_tmux = MagicMock()
            mock_tmux.is_available.return_value = True
            mock_tmux.exists.return_value = True
            mock_cls.return_value = mock_tmux

            result = select_tmux_pane(agent)

        assert result is False
        # select-window must never be called — that's the dangerous command
        called_subcommands = [c.args[0] for c in mock_tmux.run_command.call_args_list]
        assert "select-window" not in called_subcommands
