"""Tests for terminal backend implementations."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from clorch.terminal.iterm import ITermBackend
from clorch.terminal.apple_terminal import AppleTerminalBackend
from clorch.terminal.ghostty import GhosttyBackend


class TestITermBackend:
    """Tests for ITermBackend."""

    def test_get_tty_map_parses_output(self):
        raw = "/dev/ttys001=1,1,1\n/dev/ttys002=1,2,1\n/dev/ttys003=2,1,1\n"
        backend = ITermBackend()
        with patch("clorch.terminal.iterm._run_applescript", return_value=raw):
            result = backend.get_tty_map()
        assert result == {
            "/dev/ttys001": "1,1,1",
            "/dev/ttys002": "1,2,1",
            "/dev/ttys003": "2,1,1",
        }

    def test_get_tty_map_empty(self):
        backend = ITermBackend()
        with patch("clorch.terminal.iterm._run_applescript", return_value=""):
            result = backend.get_tty_map()
        assert result == {}

    def test_get_tty_map_skips_bad_lines(self):
        raw = "/dev/ttys001=1,1,1\nbadline\n\n/dev/ttys002=1,2,1\n"
        backend = ITermBackend()
        with patch("clorch.terminal.iterm._run_applescript", return_value=raw):
            result = backend.get_tty_map()
        assert result == {
            "/dev/ttys001": "1,1,1",
            "/dev/ttys002": "1,2,1",
        }

    def test_activate_tab_with_session(self):
        backend = ITermBackend()
        with patch("clorch.terminal.iterm._run_applescript", return_value="found") as mock:
            result = backend.activate_tab("1,2,3")
        assert result is True
        # Check that the script contains session selection
        script = mock.call_args[0][0]
        assert "item 3 of sessions" in script

    def test_activate_tab_without_session(self):
        backend = ITermBackend()
        with patch("clorch.terminal.iterm._run_applescript", return_value="found") as mock:
            result = backend.activate_tab("1,2")
        assert result is True
        script = mock.call_args[0][0]
        assert "sessions" not in script

    def test_activate_tab_invalid_ref(self):
        backend = ITermBackend()
        result = backend.activate_tab("1")
        assert result is False

    def test_activate_tab_not_found(self):
        backend = ITermBackend()
        with patch("clorch.terminal.iterm._run_applescript", return_value="not_found"):
            result = backend.activate_tab("1,2")
        assert result is False

    def test_activate_by_name_found(self):
        backend = ITermBackend()
        with patch("clorch.terminal.iterm._run_applescript", return_value="found"):
            result = backend.activate_by_name("myproject")
        assert result is True

    def test_activate_by_name_not_found(self):
        backend = ITermBackend()
        with patch("clorch.terminal.iterm._run_applescript", return_value="not_found"):
            result = backend.activate_by_name("myproject")
        assert result is False

    def test_bring_to_front(self):
        backend = ITermBackend()
        with patch("clorch.terminal.iterm._run_applescript") as mock:
            backend.bring_to_front()
        mock.assert_called_once()
        script = mock.call_args[0][0]
        assert "iTerm2" in script

    def test_open_tab(self):
        backend = ITermBackend()
        with patch("clorch.terminal.iterm._run_applescript", return_value="") as mock:
            result = backend.open_tab("echo hello")
        assert result is True
        script = mock.call_args[0][0]
        assert "create tab" in script
        assert "echo hello" in script

    def test_open_tab_with_title(self):
        backend = ITermBackend()
        with patch("clorch.terminal.iterm._run_applescript", return_value="") as mock:
            result = backend.open_tab("echo hello", title="my-agent")
        assert result is True
        script = mock.call_args[0][0]
        assert 'set name to "my-agent"' in script

    def test_open_tab_without_title(self):
        backend = ITermBackend()
        with patch("clorch.terminal.iterm._run_applescript", return_value="") as mock:
            result = backend.open_tab("echo hello")
        assert result is True
        script = mock.call_args[0][0]
        assert "set name to" not in script

    def test_supports_control_mode(self):
        backend = ITermBackend()
        assert backend.supports_control_mode() is True


class TestAppleTerminalBackend:
    """Tests for AppleTerminalBackend."""

    def test_get_tty_map_parses_output(self):
        raw = "/dev/ttys001=123,1\n/dev/ttys002=123,2\n/dev/ttys003=456,1\n"
        backend = AppleTerminalBackend()
        with patch("clorch.terminal.apple_terminal._run_applescript", return_value=raw):
            result = backend.get_tty_map()
        assert result == {
            "/dev/ttys001": "123,1",
            "/dev/ttys002": "123,2",
            "/dev/ttys003": "456,1",
        }

    def test_get_tty_map_empty(self):
        backend = AppleTerminalBackend()
        with patch("clorch.terminal.apple_terminal._run_applescript", return_value=""):
            result = backend.get_tty_map()
        assert result == {}

    def test_activate_tab_found(self):
        backend = AppleTerminalBackend()
        with patch("clorch.terminal.apple_terminal._run_applescript", return_value="found"):
            result = backend.activate_tab("123,2")
        assert result is True

    def test_activate_tab_not_found(self):
        backend = AppleTerminalBackend()
        with patch("clorch.terminal.apple_terminal._run_applescript", return_value="not_found"):
            result = backend.activate_tab("123,2")
        assert result is False

    def test_activate_tab_invalid_ref(self):
        backend = AppleTerminalBackend()
        result = backend.activate_tab("123")
        assert result is False

    def test_activate_by_name_found(self):
        backend = AppleTerminalBackend()
        with patch("clorch.terminal.apple_terminal._run_applescript", return_value="found"):
            result = backend.activate_by_name("myproject")
        assert result is True

    def test_activate_by_name_not_found(self):
        backend = AppleTerminalBackend()
        with patch("clorch.terminal.apple_terminal._run_applescript", return_value="not_found"):
            result = backend.activate_by_name("myproject")
        assert result is False

    def test_bring_to_front(self):
        backend = AppleTerminalBackend()
        with patch("clorch.terminal.apple_terminal._run_applescript") as mock:
            backend.bring_to_front()
        mock.assert_called_once()
        assert "Terminal" in mock.call_args[0][0]

    def test_open_tab(self):
        backend = AppleTerminalBackend()
        with patch("clorch.terminal.apple_terminal._run_applescript") as mock:
            result = backend.open_tab("echo hello")
        assert result is True
        assert "do script" in mock.call_args[0][0]

    def test_open_tab_with_title(self):
        backend = AppleTerminalBackend()
        with patch("clorch.terminal.apple_terminal._run_applescript") as mock:
            result = backend.open_tab("echo hello", title="my-agent")
        assert result is True
        script = mock.call_args[0][0]
        # The escape sequence gets double-escaped by _escape for AppleScript
        assert "my-agent" in script
        assert "033]0;" in script

    def test_open_tab_without_title(self):
        backend = AppleTerminalBackend()
        with patch("clorch.terminal.apple_terminal._run_applescript") as mock:
            result = backend.open_tab("echo hello")
        assert result is True
        script = mock.call_args[0][0]
        assert "033]0;" not in script

    def test_supports_control_mode(self):
        backend = AppleTerminalBackend()
        assert backend.supports_control_mode() is False


class TestGhosttyBackend:
    """Tests for GhosttyBackend."""

    def test_get_tty_map_returns_empty(self):
        backend = GhosttyBackend()
        assert backend.get_tty_map() == {}

    def test_activate_tab_returns_false(self):
        backend = GhosttyBackend()
        assert backend.activate_tab("1,2") is False

    def test_activate_by_name_returns_false(self):
        backend = GhosttyBackend()
        assert backend.activate_by_name("test") is False

    def test_bring_to_front(self):
        backend = GhosttyBackend()
        with patch("subprocess.run") as mock:
            backend.bring_to_front()
        mock.assert_called_once()
        args = mock.call_args
        assert "Ghostty" in args[0][0][2]

    def test_bring_to_front_handles_error(self):
        backend = GhosttyBackend()
        with patch("subprocess.run", side_effect=OSError("not found")):
            # Should not raise
            backend.bring_to_front()

    def test_open_tab_returns_false(self):
        backend = GhosttyBackend()
        with patch("subprocess.run", side_effect=OSError("not found")):
            assert backend.open_tab("echo hello") is False

    def test_open_tab_with_title_prepends_escape(self):
        backend = GhosttyBackend()
        with patch.object(backend, "_open_tab_applescript", return_value=True) as mock:
            result = backend.open_tab("echo hello", title="my-agent")
        assert result is True
        cmd = mock.call_args[0][0]
        assert cmd.startswith("printf '\\033]0;my-agent\\033\\\\'")
        assert "echo hello" in cmd

    def test_open_tab_without_title_no_escape(self):
        backend = GhosttyBackend()
        with patch.object(backend, "_open_tab_applescript", return_value=True) as mock:
            result = backend.open_tab("echo hello")
        assert result is True
        cmd = mock.call_args[0][0]
        assert "\\033]0;" not in cmd

    def test_supports_control_mode(self):
        backend = GhosttyBackend()
        assert backend.supports_control_mode() is False


class TestBackendProtocol:
    """Verify all backends satisfy the TerminalBackend protocol."""

    @pytest.mark.parametrize("cls", [ITermBackend, AppleTerminalBackend, GhosttyBackend])
    def test_is_terminal_backend(self, cls):
        from clorch.terminal.backend import TerminalBackend

        assert isinstance(cls(), TerminalBackend)
