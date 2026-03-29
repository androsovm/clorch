"""Tests for jump_to_tmux_tab — all three strategies.

Strategy 1: tty map (client tty → terminal tab)
Strategy 2: activate_by_name(window_name)
Strategy 3: activate_by_name(client_session_name / suffix) — Ghostty linked sessions
"""
from __future__ import annotations

from subprocess import CompletedProcess
from unittest.mock import MagicMock, patch

from clorch.tmux.navigator import jump_to_tmux_tab


def _make_tmux(
    *,
    client_session_output: str = "",
    all_clients_output: str = "",
    session_has_client: bool = True,
    group: str = "",
    sessions: str = "",
) -> MagicMock:
    """Create a mock TmuxSession with configurable run_command responses."""
    tmux = MagicMock()
    tmux.session = "claude"

    def run_command(*args, check=True):
        cmd = args[0] if args else ""
        if cmd == "list-clients":
            # Distinguish filtered (-t session) vs unfiltered calls
            if "-t" in args:
                return CompletedProcess(
                    args, 0 if session_has_client else 1,
                    stdout=client_session_output,
                )
            return CompletedProcess(args, 0, stdout=all_clients_output)
        if cmd == "display-message":
            return CompletedProcess(args, 0, stdout=group)
        if cmd == "list-sessions":
            return CompletedProcess(args, 0, stdout=sessions)
        return CompletedProcess(args, 0, stdout="")

    tmux.run_command = run_command
    return tmux


def _make_backend(*, tty_map: dict | None = None, activate_names: set[str] | None = None):
    """Create a mock terminal backend."""
    backend = MagicMock()
    backend.get_tty_map.return_value = tty_map or {}
    activate_names = activate_names or set()
    backend.activate_by_name.side_effect = lambda name: name in activate_names
    backend.activate_tab.return_value = True
    return backend


class TestStrategy1TtyMap:
    """Strategy 1: client tty matched via terminal tty_map."""

    def test_tty_match_activates_tab(self):
        tmux = _make_tmux(client_session_output="/dev/ttys002\tneon\n")
        backend = _make_backend(tty_map={"/dev/ttys002": "tab-1"})

        with patch("clorch.terminal.get_backend", return_value=backend):
            with patch("clorch.tmux.navigator._resolve_client_session", return_value="claude"):
                assert jump_to_tmux_tab(tmux, "neon") is True

        backend.activate_tab.assert_called_once_with("tab-1")

    def test_tty_no_match_falls_through(self):
        tmux = _make_tmux(client_session_output="/dev/ttys002\tneon\n")
        backend = _make_backend(tty_map={"/dev/ttys099": "tab-other"})

        with patch("clorch.terminal.get_backend", return_value=backend):
            with patch("clorch.tmux.navigator._resolve_client_session", return_value="claude"):
                assert jump_to_tmux_tab(tmux, "neon") is False

    def test_empty_tty_map_falls_through(self):
        """Ghostty returns empty tty_map — should not match."""
        tmux = _make_tmux(client_session_output="/dev/ttys002\tneon\n")
        backend = _make_backend(tty_map={})

        with patch("clorch.terminal.get_backend", return_value=backend):
            with patch("clorch.tmux.navigator._resolve_client_session", return_value="claude"):
                assert jump_to_tmux_tab(tmux, "neon") is False


class TestStrategy2WindowName:
    """Strategy 2: activate_by_name(window_name) in terminal tab titles."""

    def test_window_name_matches_tab(self):
        tmux = _make_tmux(client_session_output="")
        backend = _make_backend(activate_names={"neon"})

        with patch("clorch.terminal.get_backend", return_value=backend):
            with patch("clorch.tmux.navigator._resolve_client_session", return_value="claude"):
                assert jump_to_tmux_tab(tmux, "neon") is True

    def test_window_name_no_match_falls_through(self):
        tmux = _make_tmux(client_session_output="")
        backend = _make_backend(activate_names=set())

        with patch("clorch.terminal.get_backend", return_value=backend):
            with patch("clorch.tmux.navigator._resolve_client_session", return_value="claude"):
                assert jump_to_tmux_tab(tmux, "neon") is False


class TestStrategy3ClientSessionName:
    """Strategy 3: Ghostty tabs named after linked tmux sessions."""

    def test_full_session_name_matches(self):
        """Tab named 'claude-surge' matches full client session name."""
        tmux = _make_tmux(
            client_session_output="",
            all_clients_output="claude-surge\tneon\nclaude-nova\tpulse\n",
        )
        backend = _make_backend(activate_names={"claude-surge"})

        with patch("clorch.terminal.get_backend", return_value=backend):
            with patch("clorch.tmux.navigator._resolve_client_session", return_value="claude"):
                assert jump_to_tmux_tab(tmux, "neon") is True

        # Should have tried window name first, then session name
        calls = [c[0][0] for c in backend.activate_by_name.call_args_list]
        assert calls == ["neon", "claude-surge"]

    def test_suffix_matches(self):
        """Tab named 'surge' matches suffix of 'claude-surge'."""
        tmux = _make_tmux(
            client_session_output="",
            all_clients_output="claude-surge\tneon\n",
        )
        backend = _make_backend(activate_names={"surge"})

        with patch("clorch.terminal.get_backend", return_value=backend):
            with patch("clorch.tmux.navigator._resolve_client_session", return_value="claude"):
                assert jump_to_tmux_tab(tmux, "neon") is True

        calls = [c[0][0] for c in backend.activate_by_name.call_args_list]
        assert calls == ["neon", "claude-surge", "surge"]

    def test_no_hyphen_in_session_skips_suffix(self):
        """Session name without hyphen — no suffix attempt."""
        tmux = _make_tmux(
            client_session_output="",
            all_clients_output="mysession\tneon\n",
        )
        backend = _make_backend(activate_names=set())

        with patch("clorch.terminal.get_backend", return_value=backend):
            with patch("clorch.tmux.navigator._resolve_client_session", return_value="claude"):
                assert jump_to_tmux_tab(tmux, "neon") is False

        # "mysession" has no hyphen, suffix == full name → skipped
        calls = [c[0][0] for c in backend.activate_by_name.call_args_list]
        assert calls == ["neon", "mysession"]

    def test_multiple_clients_picks_correct_window(self):
        """Only the client viewing the target window is tried."""
        tmux = _make_tmux(
            client_session_output="",
            all_clients_output=(
                "claude-nova\tpulse\n"
                "claude-surge\tneon\n"
                "claude-shade\tshade\n"
            ),
        )
        backend = _make_backend(activate_names={"surge"})

        with patch("clorch.terminal.get_backend", return_value=backend):
            with patch("clorch.tmux.navigator._resolve_client_session", return_value="claude"):
                assert jump_to_tmux_tab(tmux, "neon") is True

        calls = [c[0][0] for c in backend.activate_by_name.call_args_list]
        assert "claude-nova" not in calls
        assert "claude-shade" not in calls

    def test_all_strategies_fail(self):
        """When no strategy matches, returns False."""
        tmux = _make_tmux(
            client_session_output="",
            all_clients_output="claude-surge\tneon\n",
        )
        backend = _make_backend(activate_names=set())

        with patch("clorch.terminal.get_backend", return_value=backend):
            with patch("clorch.tmux.navigator._resolve_client_session", return_value="claude"):
                assert jump_to_tmux_tab(tmux, "neon") is False
