"""Navigate to the next agent that needs user attention.

Supports multiple terminal backends via the ``clorch.terminal`` package:
- **iTerm2** — full AppleScript API (tty map, tab activation, tmux -CC).
- **Terminal.app** — AppleScript API (tty map, tab activation).
- **Ghostty** — minimal (bring to front only).

Tmux navigation (select-window / select-pane) works in all terminals.
"""
from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

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

    # 3. Match by cwd across ALL panes (not just the active one per window)
    if agent.cwd:
        agent_cwd = _normalise_path(agent.cwd)
        for pane in tmux.list_panes():
            if _normalise_path(pane["pane_path"]) == agent_cwd:
                return pane["window_name"]

    return None


def jump_to_tmux_tab(tmux: TmuxSession, window: str) -> bool:
    """Activate the terminal tab whose tmux client is viewing *window*.

    Scans all tmux clients to find one whose active window matches,
    then maps its tty to a terminal tab via the active backend.

    Falls back to matching the window name in terminal tab titles.

    Returns ``True`` on success, ``False`` if no matching tab was found.
    """
    from clorch.terminal import get_backend
    backend = get_backend()

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
                    tty_map = backend.get_tty_map()
                for term_tty, tab_ref in tty_map.items():
                    if term_tty == parts[0]:
                        return backend.activate_tab(tab_ref)

    # Strategy 2: match window name in terminal tab titles
    return backend.activate_by_name(window)


def jump_to_tab(agent: AgentState) -> bool:
    """Switch the terminal to the tab running the agent's session.

    Uses PID -> tty -> terminal tab for precise matching.

    Returns ``True`` on success, ``False`` if no matching tab was found.
    """
    from clorch.terminal import get_backend

    if not agent.pid:
        return False

    backend = get_backend()
    tty_map = backend.get_tty_map()
    if not tty_map:
        return False

    agent_tty = _tty_from_pid(agent.pid)
    if agent_tty and agent_tty in tty_map:
        return backend.activate_tab(tty_map[agent_tty])

    return False


def select_tmux_pane(agent: AgentState) -> bool:
    """Focus the tmux window + pane for this agent.

    In iTerm CC mode, ``select-window`` causes iTerm to switch to the
    corresponding tab automatically.  Returns ``True`` on success.

    Targets the window by index first (unambiguous), falling back to
    name when no index is stored in the state file.
    """
    if not agent.tmux_window:
        return False
    tmux = TmuxSession(session_name=agent.tmux_session or None)
    if not (tmux.is_available() and tmux.exists()):
        return False
    # Prefer window index — names can be duplicated across windows,
    # and tmux refuses to select-window by an ambiguous name.
    window_target = agent.tmux_window_index or agent.tmux_window
    target = f"{tmux.session}:{window_target}"
    result = tmux.run_command("select-window", "-t", target, check=False)
    if result.returncode != 0:
        return False
    if agent.tmux_pane:
        tmux.run_command(
            "select-pane", "-t", f"{target}.{agent.tmux_pane}", check=False,
        )
    return True


def bring_terminal_to_front() -> None:
    """Activate the terminal application and bring it to the foreground."""
    from clorch.terminal import get_backend
    get_backend().bring_to_front()


def pid_alive(pid: int) -> bool:
    """Check if a process is still running."""
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # alive, just can't signal


def _tty_from_pid(pid: int) -> str | None:
    """Get the controlling terminal of a process by PID."""
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "tty="],
            capture_output=True, text=True, timeout=3,
        )
        tty = result.stdout.strip()
        if tty and tty != "??":
            if not tty.startswith("/dev/"):
                tty = f"/dev/{tty}"
            return tty
    except (subprocess.TimeoutExpired, OSError) as exc:
        log.debug("Failed to get tty for pid %d: %s", pid, exc)
    return None


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
    chosen_agent: AgentState | None = None
    target: str | None = None
    past_current = False
    for agent, win in candidates:
        if win == current_window:
            past_current = True
            continue
        if past_current or current_window is None:
            chosen_agent, target = agent, win
            break

    # Wrap-around: if we went past current without finding another, take
    # the first candidate that differs; otherwise just use the first one.
    if target is None:
        for agent, win in candidates:
            if win != current_window:
                chosen_agent, target = agent, win
                break

    if target is None:
        # All attention agents map to the current window -- already there.
        chosen_agent, target = candidates[0]

    log.info("Jumping to window '%s'", target)
    tmux.select_window(target)

    # Also select the specific pane so the right agent gets focus
    if chosen_agent and chosen_agent.tmux_pane:
        pane_target = f"{tmux.session}:{target}.{chosen_agent.tmux_pane}"
        tmux.run_command("select-pane", "-t", pane_target, check=False)

    return True


# ------------------------------------------------------------------
# Backward-compat aliases
# ------------------------------------------------------------------
jump_to_iterm_tab = jump_to_tab
jump_to_tmux_iterm_tab = jump_to_tmux_tab
bring_iterm_to_front = bring_terminal_to_front


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
