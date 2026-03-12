"""iTerm2 terminal backend — full AppleScript control."""
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
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, OSError) as exc:
        log.debug("AppleScript failed: %s", exc)
        return ""


class ITermBackend:
    """Full-featured iTerm2 backend using AppleScript."""

    def get_tty_map(self) -> dict[str, str]:
        """Return ``{tty: "window_idx,tab_idx,session_idx"}`` for every iTerm session."""
        script = '''
            tell application "iTerm2"
                set output to ""
                set wIdx to 0
                repeat with w in windows
                    set wIdx to wIdx + 1
                    set tIdx to 0
                    repeat with t in tabs of w
                        set tIdx to tIdx + 1
                        set sIdx to 0
                        repeat with s in sessions of t
                            set sIdx to sIdx + 1
                            try
                                set sessionTty to tty of s
                                set output to output & sessionTty & "=" & wIdx & "," & tIdx & "," & sIdx & linefeed
                            end try
                        end repeat
                    end repeat
                end repeat
                return output
            end tell
        '''
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
        """Activate the iTerm tab and session identified by ``"window_idx,tab_idx[,session_idx]"``."""
        parts = tab_ref.split(",")
        if len(parts) < 2:
            return False
        w_idx, t_idx = parts[0], parts[1]
        s_idx = parts[2] if len(parts) >= 3 else None

        if s_idx:
            script = f'''
                tell application "iTerm2"
                    set w to item {w_idx} of windows
                    set t to item {t_idx} of tabs of w
                    tell w to select
                    select t
                    set s to item {s_idx} of sessions of t
                    select s
                    tell application "System Events" to tell process "iTerm2" to set frontmost to true
                    return "found"
                end tell
            '''
        else:
            script = f'''
                tell application "iTerm2"
                    set w to item {w_idx} of windows
                    set t to item {t_idx} of tabs of w
                    select t
                    tell w to select
                    tell application "System Events" to tell process "iTerm2" to set frontmost to true
                    return "found"
                end tell
            '''
        return _run_applescript(script) == "found"

    def activate_by_name(self, name: str) -> bool:
        """Find and activate an iTerm tab whose name contains *name*."""
        safe_name = _escape(name)
        script = f'''
            tell application "iTerm2"
                set targetName to "{safe_name}"
                set lowerTarget to do shell script "echo " & quoted form of targetName & " | tr '[:upper:]' '[:lower:]'"
                repeat with w in windows
                    repeat with t in tabs of w
                        try
                            set tabName to name of current session of t
                            set lowerTab to do shell script "echo " & quoted form of tabName & " | tr '[:upper:]' '[:lower:]'"
                            if lowerTab contains lowerTarget then
                                select t
                                tell w to select
                                tell application "System Events" to tell process "iTerm2" to set frontmost to true
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
        """Activate iTerm2 and bring it to the foreground."""
        _run_applescript(
            'tell application "iTerm2" to activate\n'
            'tell application "System Events" to tell process "iTerm2" '
            'to set frontmost to true'
        )

    def open_tab(self, command: str, *, title: str | None = None) -> bool:
        """Open a new iTerm tab and run *command* in it."""
        safe_cmd = _escape(command)
        set_name = ""
        if title:
            safe_title = _escape(title)
            set_name = f'\n                        set name to "{safe_title}"'
        script = f'''
            tell application "iTerm2"
                tell current window
                    set newTab to (create tab with default profile)
                    tell current session of newTab{set_name}
                        write text "{safe_cmd}"
                    end tell
                end tell
            end tell
        '''
        result = _run_applescript(script)
        # AppleScript returns empty on success for this command
        return True

    def can_resolve_tabs(self) -> bool:
        return True

    def supports_control_mode(self) -> bool:
        """iTerm2 supports ``tmux -CC`` control mode."""
        return True
