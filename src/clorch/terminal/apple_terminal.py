"""Terminal.app backend — AppleScript control."""

from __future__ import annotations

import logging
import subprocess

from clorch.notifications.macos import _escape

log = logging.getLogger(__name__)


def _run_applescript(script: str) -> str:
    """Execute an AppleScript and return stripped stdout, or empty string on error."""
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, OSError) as exc:
        log.debug("AppleScript failed: %s", exc)
        return ""


class AppleTerminalBackend:
    """Terminal.app backend using AppleScript."""

    def get_tty_map(self) -> dict[str, str]:
        """Return ``{tty: "window_id,tab_idx"}`` for every Terminal.app tab."""
        script = """
            tell application "Terminal"
                set output to ""
                repeat with w in windows
                    set wId to id of w
                    set tIdx to 0
                    repeat with t in tabs of w
                        set tIdx to tIdx + 1
                        try
                            set tabTty to tty of t
                            set output to output & tabTty & "=" & wId & "," & tIdx & linefeed
                        end try
                    end repeat
                end repeat
                return output
            end tell
        """
        raw = _run_applescript(script)
        result: dict[str, str] = {}
        for line in raw.splitlines():
            line = line.strip()
            if "=" not in line:
                continue
            tty, ref = line.split("=", 1)
            result[tty] = ref
        return result

    def activate_tab(self, tab_ref: str) -> bool:
        """Activate the Terminal.app tab identified by ``"window_id,tab_idx"``."""
        parts = tab_ref.split(",")
        if len(parts) < 2:
            return False
        w_id, t_idx = parts[0], parts[1]

        script = f"""
            tell application "Terminal"
                repeat with w in windows
                    if id of w is {w_id} then
                        set selected tab of w to tab {t_idx} of w
                        set index of w to 1
                        activate
                        return "found"
                    end if
                end repeat
                return "not_found"
            end tell
        """
        return _run_applescript(script) == "found"

    def activate_by_name(self, name: str) -> bool:
        """Find and activate a Terminal.app tab whose custom title contains *name*."""
        safe_name = _escape(name)
        script = f'''
            tell application "Terminal"
                set targetName to "{safe_name}"
                set lowerTarget to do shell script "echo " & quoted form of targetName & " | tr '[:upper:]' '[:lower:]'"
                repeat with w in windows
                    set tIdx to 0
                    repeat with t in tabs of w
                        set tIdx to tIdx + 1
                        try
                            set tabTitle to custom title of t
                            set lowerTitle to do shell script "echo " & quoted form of tabTitle & " | tr '[:upper:]' '[:lower:]'"
                            if lowerTitle contains lowerTarget then
                                set selected tab of w to tab tIdx of w
                                set index of w to 1
                                activate
                                return "found"
                            end if
                        end try
                    end repeat
                end repeat
                return "not_found"
            end tell
        '''
        return _run_applescript(script) == "found"

    def bring_to_front(self) -> None:
        """Activate Terminal.app and bring it to the foreground."""
        _run_applescript('tell application "Terminal" to activate')

    def open_tab(self, command: str, *, title: str | None = None) -> bool:
        """Open a new Terminal.app window and run *command* in it."""
        if title:
            command = f"printf '\\033]0;{title}\\033\\\\' && {command}"
        safe_cmd = _escape(command)
        script = f'tell application "Terminal" to do script "{safe_cmd}"'
        _run_applescript(script)
        return True

    def can_resolve_tabs(self) -> bool:
        return True

    def supports_control_mode(self) -> bool:
        """Terminal.app does not support tmux CC mode."""
        return False
