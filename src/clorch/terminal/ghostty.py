"""Ghostty terminal backend.

Ghostty lacks an AppleScript dictionary, so tab creation uses
System Events menu clicks + keystrokes (requires Accessibility
permission for ``osascript``).  Falls back gracefully when
Accessibility is not granted.
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile

log = logging.getLogger(__name__)


def _run_applescript(script: str) -> tuple[bool, str]:
    """Run AppleScript, return ``(success, stdout)``."""
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            log.debug("AppleScript stderr: %s", result.stderr.strip())
            return False, result.stderr.strip()
        return True, result.stdout.strip()
    except (subprocess.TimeoutExpired, OSError) as exc:
        log.debug("AppleScript failed: %s", exc)
        return False, str(exc)


class GhosttyBackend:
    """Ghostty backend — uses System Events AppleScript for tab control."""

    def get_tty_map(self) -> dict[str, str]:
        return {}

    def activate_tab(self, tab_ref: str) -> bool:
        return False

    def activate_by_name(self, name: str) -> bool:
        """Switch to a Ghostty tab whose title matches *name*.

        Ghostty lists open tabs as menu items at the bottom of the
        Window menu.  Clicking the item activates that tab.

        Performs exact match first, then substring match to handle
        titles like ``"✳ Claude Code"`` when searching for
        ``"Claude Code"``.
        """
        tab_names = self.list_tab_names()
        if not tab_names:
            return False

        # Exact match
        if name in tab_names:
            return self._click_window_menu_item(name)

        # Substring match (handles "✳ " prefix on the active tab)
        name_lower = name.lower()
        for tab in tab_names:
            if name_lower in tab.lower():
                return self._click_window_menu_item(tab)

        return False

    def list_tab_names(self) -> list[str]:
        """Return tab/window titles from the Ghostty Window menu.

        Ghostty appends tab titles after a separator at the bottom
        of the Window menu.  Standard menu items (Minimize, Zoom, …)
        are filtered out by checking against known system items.
        """
        script = '''
            tell application "System Events"
                tell process "Ghostty"
                    set menuItems to name of every menu item of menu "Window" of menu bar 1
                    set output to ""
                    repeat with itemName in menuItems
                        if itemName is not missing value then
                            set output to output & (itemName as text) & linefeed
                        end if
                    end repeat
                    return output
                end tell
            end tell
        '''
        ok, stdout = _run_applescript(script)
        if not ok or not stdout:
            return []

        # Known system menu items to skip
        system_items = {
            "missing value",
            "Minimize", "Minimize All", "Zoom", "Zoom All", "Fill", "Center",
            "Move & Resize", "Full Screen Tile", "Remove Window from Set",
            "Toggle Full Screen", "Show/Hide All Terminals",
            "Show Previous Tab", "Show Next Tab",
            "Move Tab to New Window", "Merge All Windows",
            "Zoom Split", "Select Previous Split", "Select Next Split",
            "Select Split", "Resize Split", "Return To Default Size",
            "Float on Top", "Use as Default",
            "Bring All to Front", "Arrange in Front",
        }
        return [
            line for line in stdout.strip().splitlines()
            if line and line not in system_items
        ]

    def _click_window_menu_item(self, menu_item: str) -> bool:
        """Click a specific item in the Ghostty Window menu."""
        safe = menu_item.replace("\\", "\\\\").replace('"', '\\"')
        script = f'''
            tell application "Ghostty" to activate
            tell application "System Events"
                tell process "Ghostty"
                    click menu item "{safe}" of menu "Window" of menu bar 1
                end tell
            end tell
        '''
        ok, _err = _run_applescript(script)
        if ok:
            log.debug("Ghostty: activated tab '%s' via Window menu", menu_item)
        return ok

    def bring_to_front(self) -> None:
        """Activate Ghostty and bring it to the foreground."""
        _run_applescript('tell application "Ghostty" to activate')

    def open_tab(self, command: str, *, title: str | None = None) -> bool:
        """Open a new Ghostty tab and run *command* in it.

        Strategy chain:
        1. AppleScript via System Events (needs Accessibility for osascript)
           — opens a tab in the current window.
        2. ``open -na Ghostty --args -e /bin/zsh -c …``
           — opens a new window (no Accessibility needed).

        Returns ``False`` only if both strategies fail.
        """
        if title:
            command = f"printf '\\033]0;{title}\\033\\\\' && {command}"
        if self._open_tab_applescript(command):
            return True
        log.debug("AppleScript tab failed, falling back to new window")
        return self._open_tab_new_window(command)

    def _open_tab_applescript(self, command: str) -> bool:
        """Try to open a tab via System Events menu click + keystroke."""
        fd, path = tempfile.mkstemp(prefix="clorch_tab_", suffix=".sh")
        try:
            os.write(fd, command.encode())
        finally:
            os.close(fd)

        source_cmd = f"source {path} && rm -f {path}"

        script = f'''
            tell application "Ghostty" to activate
            delay 0.2
            tell application "System Events"
                tell process "Ghostty"
                    click menu item "New Tab" of menu "File" of menu bar 1
                    delay 0.3
                    keystroke "{source_cmd}"
                    key code 36
                end tell
            end tell
        '''
        ok, err = _run_applescript(script)
        if not ok:
            try:
                os.unlink(path)
            except OSError:
                pass
            log.debug("Ghostty AppleScript tab failed: %s", err)
            return False
        return True

    def _open_tab_new_window(self, command: str) -> bool:
        """Fallback: open a new Ghostty window with *command*."""
        try:
            subprocess.run(
                ["open", "-na", "Ghostty", "--args", "-e", "/bin/zsh", "-c", command],
                capture_output=True,
                timeout=5,
            )
            return True
        except (subprocess.TimeoutExpired, OSError) as exc:
            log.debug("Ghostty new window failed: %s", exc)
            return False

    def can_resolve_tabs(self) -> bool:
        return False

    def supports_control_mode(self) -> bool:
        return False
