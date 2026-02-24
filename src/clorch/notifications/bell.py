"""Terminal bell notification."""
from __future__ import annotations

import sys


def send_bell() -> None:
    """Send terminal bell character to attract attention."""
    sys.stdout.write("\a")
    sys.stdout.flush()


def send_bell_to_tmux(session: str = "claude", window: str = "") -> None:
    """Send bell to a specific tmux pane to trigger tmux visual/audio bell.

    Uses: tmux send-keys -t session:window '' to trigger bell in that window.
    Or: tmux run-shell -t ... 'printf \\a'
    """
    import subprocess

    target = f"{session}:{window}" if window else session
    try:
        subprocess.run(
            ["tmux", "send-keys", "-t", target, ""],
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        # tmux not available, fall back to local bell
        send_bell()
