"""Navigate to the next agent that needs user attention.

Supports two backends:
- **tmux** — when running inside a tmux session.
- **iTerm2 AppleScript** — when running in plain iTerm tabs (no tmux).
"""
from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from clorch.notifications.macos import _escape
from clorch.state.manager import StateManager
from clorch.state.models import AgentState
from clorch.tmux.session import TmuxSession

log = logging.getLogger(__name__)


def map_agent_to_window(agent: AgentState, tmux: TmuxSession) -> str | None:
    """Map an *AgentState* to a tmux window name.

    Resolution order:

    1. ``agent.tmux_window`` -- explicit mapping stored in the state file.
    2. ``agent.project_name`` matches a window name (case-insensitive).
    3. ``agent.cwd`` matches the ``pane_current_path`` of a window.

    Returns the window name/index on success, or ``None``.
    """
    # 1. Explicit mapping
    if agent.tmux_window:
        return agent.tmux_window

    windows = tmux.list_windows()
    if not windows:
        return None

    # 2. Match by project name == window name
    if agent.project_name:
        project_lower = agent.project_name.lower()
        for win in windows:
            if win["name"].lower() == project_lower:
                return win["name"]

    # 3. Match by cwd == pane current path
    if agent.cwd:
        agent_cwd = _normalise_path(agent.cwd)
        for win in windows:
            if _normalise_path(win["pane_path"]) == agent_cwd:
                return win["name"]

    return None


def jump_to_tmux_iterm_tab(tmux: TmuxSession, window: str) -> bool:
    """Activate the iTerm tab whose tmux client is viewing *window*.

    Scans all tmux clients to find one whose active window matches,
    then maps its tty to an iTerm tab via AppleScript.

    Falls back to matching the window name in iTerm tab titles.

    Returns ``True`` on success, ``False`` if no matching tab was found.
    """
    # Strategy 1: find client whose active window matches
    result = tmux.run_command(
        "list-clients", "-F", "#{client_tty}\t#{window_name}",
        check=False,
    )
    if result.returncode == 0 and result.stdout.strip():
        tty_map = None  # lazy load
        for line in result.stdout.strip().splitlines():
            parts = line.split("\t", 1)
            if len(parts) == 2 and parts[1] == window:
                if tty_map is None:
                    tty_map = _iterm_get_tty_map()
                for iterm_tty, tab_ref in tty_map.items():
                    if iterm_tty == parts[0]:
                        return _iterm_activate_tab(tab_ref)

    # Strategy 2: match window name in iTerm tab titles
    return _iterm_activate_by_name(window)


# ------------------------------------------------------------------
# iTerm2 backend (AppleScript + lsof)
# ------------------------------------------------------------------

def jump_to_iterm_tab(agent: AgentState) -> bool:
    """Switch iTerm2 to the tab running the agent's session.

    Uses a two-step approach:
    1. AppleScript to get each iTerm session's ``tty``.
    2. ``lsof`` to resolve the foreground process's cwd from that tty.
    3. Match cwd against ``agent.cwd``.

    Falls back to matching ``agent.project_name`` in the tab title.

    Returns ``True`` on success, ``False`` if no matching tab was found.
    """
    # Strategy 1: match by cwd via tty → lsof
    if agent.cwd:
        target_cwd = _normalise_path(agent.cwd)
        tty_map = _iterm_get_tty_map()
        for tty, tab_ref in tty_map.items():
            cwd = _cwd_from_tty(tty)
            if cwd and _normalise_path(cwd) == target_cwd:
                if _iterm_activate_tab(tab_ref):
                    return True

    # Strategy 2: match by project name in tab title
    if agent.project_name:
        if _iterm_activate_by_name(agent.project_name):
            return True

    return False


def _iterm_get_tty_map() -> dict[str, str]:
    """Return ``{tty: "window_idx,tab_idx"}`` for every iTerm session.

    The value is a string that ``_iterm_activate_tab`` can parse to
    select the right window and tab via AppleScript.
    """
    script = '''
        tell application "iTerm2"
            set output to ""
            set wIdx to 0
            repeat with w in windows
                set wIdx to wIdx + 1
                set tIdx to 0
                repeat with t in tabs of w
                    set tIdx to tIdx + 1
                    repeat with s in sessions of t
                        try
                            set sessionTty to tty of s
                            set output to output & sessionTty & "=" & wIdx & "," & tIdx & linefeed
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


def _cwd_from_tty(tty: str) -> str | None:
    """Get the working directory of the foreground process on *tty*.

    Uses ``ps`` to find the foreground process (stat contains ``+``)
    then ``lsof -d cwd`` to get its working directory.
    """
    tty_short = tty.replace("/dev/", "")
    try:
        # Find foreground process on this tty
        ps_result = subprocess.run(
            ["ps", "-t", tty_short, "-o", "pid=,stat="],
            capture_output=True, text=True, timeout=3,
        )
        pid = None
        for ps_line in ps_result.stdout.strip().splitlines():
            parts = ps_line.split()
            if len(parts) >= 2 and "+" in parts[1]:
                pid = parts[0]
                break
        if not pid:
            return None

        # Get cwd via lsof
        lsof_result = subprocess.run(
            ["lsof", "-a", "-d", "cwd", "-p", pid, "-Fn"],
            capture_output=True, text=True, timeout=3,
        )
        for lsof_line in lsof_result.stdout.splitlines():
            if lsof_line.startswith("n/"):
                return lsof_line[1:]
    except (subprocess.TimeoutExpired, OSError) as exc:
        log.debug("Failed to get cwd for tty %s: %s", tty, exc)
    return None


def _iterm_activate_tab(tab_ref: str) -> bool:
    """Activate the iTerm tab identified by ``"window_idx,tab_idx"``."""
    parts = tab_ref.split(",")
    if len(parts) != 2:
        return False
    w_idx, t_idx = parts
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


def _iterm_activate_by_name(name: str) -> bool:
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


def jump_to_next_attention(session_name: str = "claude") -> bool:
    """Find the next agent needing attention and switch tmux to its window.

    Returns ``True`` if the window was switched, ``False`` if no agents
    need attention or no matching window was found.

    Strategy
    --------
    1. Retrieve all agents whose status requires attention.
    2. For each agent, resolve the corresponding tmux window.
    3. Switch to the first match that is *not* the currently active window
       (so repeated invocations cycle through them).  If every match is
       the active window, stay put and return ``True`` (already there).
    """
    mgr = StateManager()
    tmux = TmuxSession(session_name=session_name)

    if not tmux.is_available() or not tmux.exists():
        log.warning("tmux session '%s' not found", session_name)
        return False

    attention_agents = mgr.get_attention_agents()
    if not attention_agents:
        log.info("No agents need attention")
        return False

    # Determine the currently active window so we can skip past it.
    current_window = _get_active_window(tmux)

    # Build an ordered list of (agent, window) pairs.
    candidates: list[tuple[AgentState, str]] = []
    for agent in attention_agents:
        win = map_agent_to_window(agent, tmux)
        if win is not None:
            candidates.append((agent, win))

    if not candidates:
        log.info("Attention agents exist but none map to a tmux window")
        return False

    # Try to pick a window that is *not* the current one (cycle behaviour).
    target: str | None = None
    past_current = False
    for _agent, win in candidates:
        if win == current_window:
            past_current = True
            continue
        if past_current or current_window is None:
            target = win
            break

    # Wrap-around: if we went past current without finding another, take
    # the first candidate that differs; otherwise just use the first one.
    if target is None:
        for _agent, win in candidates:
            if win != current_window:
                target = win
                break

    if target is None:
        # All attention agents map to the current window -- already there.
        target = candidates[0][1]

    log.info("Jumping to window '%s'", target)
    tmux.select_window(target)
    return True


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _normalise_path(p: str) -> str:
    """Resolve symlinks and expand ``~`` so paths compare reliably."""
    try:
        return str(Path(p).expanduser().resolve())
    except (OSError, ValueError):
        return p


def _get_active_window(tmux: TmuxSession) -> str | None:
    """Return the name of the currently active window, or ``None``."""
    result = tmux.run_command(
        "display-message", "-p", "-t", tmux.session,
        "#{window_name}",
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return result.stdout.strip()


# Allow tmux keybinding to call this directly:
#   bind-key ! run-shell "python -m clorch.tmux.navigator"
if __name__ == "__main__":
    import sys

    from clorch.config import TMUX_SESSION_NAME

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    jumped = jump_to_next_attention(session_name=TMUX_SESSION_NAME)
    sys.exit(0 if jumped else 1)
