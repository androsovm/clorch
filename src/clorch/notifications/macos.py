"""macOS native notifications via osascript."""
from __future__ import annotations

import subprocess
import sys


def notify(title: str, message: str, sound: str = "Ping") -> bool:
    """Send a macOS notification.

    Returns True if successful, False if not on macOS or failed.
    """
    if sys.platform != "darwin":
        return False

    script = (
        f'display notification "{_escape(message)}" '
        f'with title "{_escape(title)}" '
        f'sound name "{sound}"'
    )
    try:
        subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            check=True,
            timeout=5,
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _escape(text: str) -> str:
    """Escape string for AppleScript."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def notify_permission_request(project: str, tool: str) -> bool:
    """Notify about a permission request."""
    return notify(
        title=f"Clorch — {project}",
        message=f"⚠️ Permission needed: {tool}",
        sound="Sosumi",
    )


def notify_question(project: str, message: str) -> bool:
    """Notify about a question/elicitation."""
    # Truncate message for notification
    short = message[:100] + "..." if len(message) > 100 else message
    return notify(
        title=f"Clorch — {project}",
        message=f"❓ {short}",
        sound="Ping",
    )


def notify_error(project: str, message: str) -> bool:
    """Notify about an error."""
    short = message[:100] + "..." if len(message) > 100 else message
    return notify(
        title=f"Clorch — {project}",
        message=f"❌ {short}",
        sound="Basso",
    )
