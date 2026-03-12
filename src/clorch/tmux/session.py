"""Tmux session management."""
from __future__ import annotations

import logging
import shutil
import subprocess

from clorch.config import TMUX_SESSION_NAME, TMUX_ORCH_WINDOW

log = logging.getLogger(__name__)


class TmuxSession:
    """Create, attach, and manage tmux sessions for Clorch."""

    def __init__(self, session_name: str | None = None, orch_window: str | None = None) -> None:
        self.session = session_name or TMUX_SESSION_NAME
        self.orch_window = orch_window or TMUX_ORCH_WINDOW

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    @staticmethod
    def is_available() -> bool:
        """Check if tmux is installed and on PATH."""
        return shutil.which("tmux") is not None

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def exists(self) -> bool:
        """Return True if the tmux session already exists."""
        result = self.run_command("has-session", "-t", self.session, check=False)
        return result.returncode == 0

    def create_or_attach(self) -> None:
        """Start the session or attach if it already exists.

        When running inside iTerm2, ``tmux -CC attach`` is used so iTerm
        can render native tabs/windows for each tmux window.
        """
        if not self.exists():
            self._create_session()

        self._apply_options()
        self._apply_keybindings()
        self._attach()

    def add_window(self, name: str, cwd: str | None = None) -> None:
        """Create a new tmux window with an optional working directory."""
        cmd = ["new-window", "-t", self.session, "-n", name]
        if cwd:
            cmd.extend(["-c", cwd])
        self.run_command(*cmd)

        # Store the cwd as a user option on the pane so the navigator can
        # map agents back to windows later.
        if cwd:
            self.run_command(
                "set-option", "-p",
                "-t", f"{self.session}:{name}",
                "@orch_cwd", cwd,
            )

    def list_windows(self) -> list[dict[str, str]]:
        """List all windows with pane metadata.

        Returns a list of dicts with keys:
        ``name``, ``index``, ``pane_path``, ``pane_command``.
        """
        fmt = "#{window_name}\t#{window_index}\t#{pane_current_path}\t#{pane_current_command}"
        result = self.run_command(
            "list-windows",
            "-t", self.session,
            "-F", fmt,
            check=False,
        )
        if result.returncode != 0:
            return []

        windows: list[dict[str, str]] = []
        for line in result.stdout.strip().splitlines():
            parts = line.split("\t")
            if len(parts) < 4:
                continue
            windows.append({
                "name": parts[0],
                "index": parts[1],
                "pane_path": parts[2],
                "pane_command": parts[3],
            })
        return windows

    def list_panes(self) -> list[dict[str, str]]:
        """List all panes across all windows in the session.

        Returns a list of dicts with keys:
        ``window_name``, ``window_index``, ``pane_path``, ``pane_index``.
        """
        fmt = "#{window_name}\t#{window_index}\t#{pane_current_path}\t#{pane_index}"
        result = self.run_command(
            "list-panes",
            "-s",
            "-t", self.session,
            "-F", fmt,
            check=False,
        )
        if result.returncode != 0:
            return []

        panes: list[dict[str, str]] = []
        for line in result.stdout.strip().splitlines():
            parts = line.split("\t")
            if len(parts) < 4:
                continue
            panes.append({
                "window_name": parts[0],
                "window_index": parts[1],
                "pane_path": parts[2],
                "pane_index": parts[3],
            })
        return panes

    def select_window(self, window: str) -> None:
        """Switch the active tmux window.

        *window* can be a name or an index.
        """
        self.run_command("select-window", "-t", f"{self.session}:{window}")

    def create_linked_session(self, window: str) -> str:
        """Create a grouped session pinned to a specific window.

        A linked session shares the same window set as the main session
        but can independently select which window is active.  When the
        client detaches the linked session is automatically destroyed.

        Returns the linked session name.
        """
        linked = f"{self.session}-{window}"
        # Kill leftover linked session from a previous run
        self.run_command("kill-session", "-t", linked, check=False)
        # Create linked session grouped with main
        self.run_command(
            "new-session", "-d",
            "-t", self.session,
            "-s", linked,
            check=False,
        )
        # Pin to the requested window
        self.run_command(
            "select-window",
            "-t", f"{linked}:{window}",
            check=False,
        )
        # Auto-destroy when client detaches
        self.run_command(
            "set-option", "-t", linked,
            "destroy-unattached", "on",
            check=False,
        )
        return linked

    def split_window(
        self,
        window: str,
        horizontal: bool = True,
        cwd: str | None = None,
    ) -> bool:
        """Split *window* into a new pane.

        Args:
            window: Window name or index.
            horizontal: ``True`` for side-by-side (``-h``),
                ``False`` for top-bottom (``-v``).
            cwd: Working directory for the new pane.

        Returns ``True`` on success.
        """
        cmd = [
            "split-window",
            "-h" if horizontal else "-v",
            "-t", f"{self.session}:{window}",
        ]
        if cwd:
            cmd.extend(["-c", cwd])
        result = self.run_command(*cmd, check=False)
        return result.returncode == 0

    # ------------------------------------------------------------------
    # Keystroke control
    # ------------------------------------------------------------------

    def send_keys(self, target: str, keys: str, literal: bool = False) -> bool:
        """Send keystrokes to a tmux pane.

        Args:
            target: Tmux target string (``session:window.pane``).
            keys: The keys to send (e.g. ``"y"``, ``"Enter"``).
            literal: If *True*, send keys literally (``-l`` flag) so
                special key names like ``Enter`` are typed as text.

        Returns ``True`` if the command succeeded, ``False`` otherwise.
        """
        cmd = ["send-keys", "-t", target]
        if literal:
            cmd.append("-l")
        cmd.append(keys)
        result = self.run_command(*cmd, check=False)
        return result.returncode == 0

    def get_pane_target(self, window: str, pane: str = "0") -> str:
        """Build a ``session:window.pane`` target string."""
        return f"{self.session}:{window}.{pane}"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _create_session(self) -> None:
        """Create a new detached session with the orchestrator window."""
        self.run_command(
            "new-session",
            "-d",
            "-s", self.session,
            "-n", self.orch_window,
        )
        log.info("Created tmux session '%s'", self.session)

    def _apply_options(self) -> None:
        """Set session-level tmux options."""
        opts: list[tuple[str, str]] = [
            ("allow-rename", "off"),
            ("automatic-rename", "off"),
            ("renumber-windows", "on"),
            ("status-style", "default"),
            ("status-left", " ORCH "),
            ("status-right", '^B+←→ pane  ^B+" split-h  ^B+% split-v  ^B+N win  ^B+! attn'),
            ("status-right-length", "80"),
        ]
        for key, value in opts:
            self.run_command(
                "set-option", "-t", self.session, key, value,
                check=False,
            )

    def _apply_keybindings(self) -> None:
        """Bind custom key shortcuts within this session.

        prefix + N  --  prompt for a new window name and create it.
        prefix + !  --  jump to the next agent needing attention.
        """
        # prefix+N: prompt for window name, then create it
        self.run_command(
            "bind-key", "-T", "prefix", "N",
            "command-prompt", "-p", "new window name:",
            f"new-window -t {self.session} -n '%%'",
            check=False,
        )
        # prefix+!: jump to next attention agent via the navigator CLI
        self.run_command(
            "bind-key", "-T", "prefix", "!",
            "run-shell", "python -m clorch.tmux.navigator",
            check=False,
        )

    def _attach(self) -> None:
        """Attach to the session.

        Uses ``tmux -CC attach`` when the terminal backend supports
        control mode (e.g. iTerm2) so it renders native windows instead
        of the raw terminal UI.
        """
        from clorch.terminal import get_backend
        if get_backend().supports_control_mode():
            subprocess.run(["tmux", "-CC", "attach-session", "-t", self.session])
        else:
            subprocess.run(["tmux", "attach-session", "-t", self.session])

    def run_command(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        """Run a tmux sub-command and return the completed process."""
        cmd = ["tmux", *args]
        log.debug("Running: %s", " ".join(cmd))
        try:
            return subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=check,
            )
        except subprocess.CalledProcessError as exc:
            log.error(
                "tmux command failed (rc=%d): %s\nstderr: %s",
                exc.returncode, " ".join(cmd), exc.stderr.strip(),
            )
            raise
