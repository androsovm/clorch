"""Main Textual TUI dashboard application — action-first control plane."""
from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.events import Key
from textual.screen import ModalScreen
from textual.containers import Horizontal, Vertical
from textual.widgets import Input, Label, Static

from clorch.state.manager import StateManager
from clorch.state.models import AgentState, StatusSummary, ActionItem, build_action_queue
from clorch.constants import AgentStatus, ANIM_INTERVAL
from clorch.tui.widgets.session_list import SessionList
from clorch.tui.widgets.agent_detail import AgentDetail
from clorch.tui.widgets.header_bar import HeaderBar
from clorch.tui.widgets.action_panel import ActionPanel
from clorch.tui.widgets.context_footer import ContextFooter


class PromptScreen(ModalScreen[str | None]):
    """Modal prompt that returns user input or None on escape."""

    DEFAULT_CSS = """
    PromptScreen {
        align: center middle;
    }
    PromptScreen > Vertical {
        width: 50;
        height: auto;
        border: solid;
        padding: 1 2;
    }
    PromptScreen Label {
        margin-bottom: 1;
        text-style: bold;
    }
    PromptScreen Input {
        width: 100%;
    }
    """

    def __init__(self, prompt: str, placeholder: str = "") -> None:
        super().__init__()
        self._prompt = prompt
        self._placeholder = placeholder

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(self._prompt)
            yield Input(placeholder=self._placeholder)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        self.dismiss(value if value else None)

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            self.dismiss(None)
            event.prevent_default()


class HelpScreen(ModalScreen[None]):
    """Modal overlay showing grouped keybinding help."""

    DEFAULT_CSS = """
    HelpScreen {
        align: center middle;
    }
    HelpScreen > Vertical {
        width: 60;
        height: auto;
        max-height: 30;
        border: solid;
        padding: 1 2;
    }
    HelpScreen Static {
        width: 100%;
    }
    """

    def compose(self) -> ComposeResult:
        from rich.text import Text
        from clorch.constants import CYAN, GREEN, RED, GREY, YELLOW

        text = Text()
        text.append("CLAUDE ORCH HELP\n\n", style=f"bold {CYAN}")

        text.append("PERMISSION APPROVAL\n", style=f"bold {YELLOW}")
        text.append("  1. Press ", style="")
        text.append("[a-z]", style=f"bold {CYAN}")
        text.append(" to select a pending action\n")
        text.append("  2. Read the full request message\n")
        text.append("  3. Press ", style="")
        text.append("[y]", style=f"bold {GREEN}")
        text.append(" to approve or ", style="")
        text.append("[n]", style=f"bold {RED}")
        text.append(" to deny\n")
        text.append("  Shortcut: ", style="")
        text.append("[Y]", style=f"bold {GREEN}")
        text.append(" approves ALL pending permissions\n\n")

        text.append("NAVIGATION\n", style=f"bold {YELLOW}")
        text.append("  [j/k]", style=f"bold {CYAN}")
        text.append("     Move cursor up/down\n")
        text.append("  [1-0]", style=f"bold {CYAN}")
        text.append("     Select agent by number\n")
        text.append("  [->]", style=f"bold {CYAN}")
        text.append("      Jump to agent's tmux window\n")
        text.append("  [d]", style=f"bold {CYAN}")
        text.append("       Cycle detail: normal/expanded/hidden\n\n")

        text.append("TMUX MANAGEMENT\n", style=f"bold {YELLOW}")
        text.append("  [N]", style=f"bold {CYAN}")
        text.append("       Create new tmux window\n")
        text.append("  [R]", style=f"bold {CYAN}")
        text.append("       Open iTerm tab for selected agent\n")
        text.append("  [X]", style=f"bold {CYAN}")
        text.append("       Kill selected agent's window\n")
        text.append("  [S/V]", style=f"bold {CYAN}")
        text.append("     Split window (horizontal/vertical)\n\n")

        text.append("Press ", style=f"dim {GREY}")
        text.append("[?]", style=f"bold {CYAN}")
        text.append(" or ", style=f"dim {GREY}")
        text.append("[Esc]", style=f"bold {CYAN}")
        text.append(" to close", style=f"dim {GREY}")

        with Vertical():
            yield Static(text)

    def on_key(self, event: Key) -> None:
        if event.key in ("escape", "question_mark"):
            self.dismiss(None)
            event.prevent_default()


class OrchestratorApp(App):
    """Clorch TUI Dashboard."""

    CSS_PATH = "app.tcss"
    TITLE = "Clorch"
    THEME = "textual-ansi"

    BINDINGS = [
        Binding("q", "quit", "Quit", show=False),
        Binding("d", "toggle_detail", "Detail", show=False),
        Binding("r", "refresh", "Refresh", show=False),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("right", "jump_to_agent", "Jump", show=False),
        Binding("enter", "jump_to_agent", "Jump", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._manager = StateManager()
        self._prev_states: dict[str, AgentStatus] = {}
        self._detail_visible = True
        self._detail_mode = "normal"  # "normal" | "expanded" | "hidden"
        self._focused_action: ActionItem | None = None
        self._action_items: list[ActionItem] = []
        self._has_ever_approved: bool = False
        self._hint_shown: bool = False
        self._anim_frame: int = 0
        self._is_narrow: bool = False

    # Responsive breakpoint (columns)
    NARROW_THRESHOLD = 120

    def compose(self) -> ComposeResult:
        yield HeaderBar(id="header-bar")
        with Horizontal(id="main"):
            yield SessionList(id="session-list")
            with Vertical(id="sidebar"):
                yield AgentDetail(id="detail-panel")
                yield ActionPanel(id="action-panel")
        yield AgentDetail(id="narrow-detail")
        yield ContextFooter(id="context-footer")

    def on_mount(self) -> None:
        self._refresh_timer = self.set_interval(0.5, self._poll_state)
        self._cleanup_timer = self.set_interval(30, self._run_cleanup)
        self._anim_timer = self.set_interval(ANIM_INTERVAL, self._tick_animation)
        self._run_cleanup()
        self._poll_state()
        self._apply_tmux_statusbar()
        self._init_header_tmux()
        # Initial responsive check
        self._is_narrow = self.size.width < self.NARROW_THRESHOLD
        self._apply_responsive_mode()

    def on_resize(self, event) -> None:
        """Switch between wide/narrow layout based on terminal width."""
        narrow = self.size.width < self.NARROW_THRESHOLD
        if narrow != self._is_narrow:
            self._is_narrow = narrow
            self._apply_responsive_mode()

    def _apply_responsive_mode(self) -> None:
        """Toggle CSS classes for wide/narrow layout."""
        if self._is_narrow:
            self.add_class("narrow")
        else:
            self.remove_class("narrow")
        # Update the appropriate detail panel
        if self._detail_mode != "hidden":
            table = self.query_one("#session-list", SessionList)
            agent = table.get_selected_agent()
            if self._is_narrow:
                self.query_one("#narrow-detail", AgentDetail).show_agent(agent)
            else:
                self.query_one("#detail-panel", AgentDetail).show_agent(agent)

    def _run_cleanup(self) -> None:
        """Remove stale state files (no activity for 30+ minutes)."""
        removed = self._manager.cleanup_stale(max_age_seconds=1800)
        if removed:
            self.notify(f"Cleaned {removed} stale session(s)")

    def _tick_animation(self) -> None:
        """Global animation tick — advances spinners and pulses."""
        self._anim_frame += 1
        self.query_one("#header-bar", HeaderBar).tick_animation(self._anim_frame)
        self.query_one("#session-list", SessionList).tick_animation(self._anim_frame)

    def _poll_state(self) -> None:
        agents = self._manager.scan()
        summary = StatusSummary.from_agents(agents)

        # Update header bar
        self.query_one("#header-bar", HeaderBar).update_summary(summary)

        # Build action queue
        self._action_items = build_action_queue(agents)
        self.query_one("#action-panel", ActionPanel).update_actions(self._action_items)

        # Update session list (agents + inline action hints)
        table = self.query_one("#session-list", SessionList)
        table.update_agents(agents)
        table.update_actions(self._action_items)

        # Toast on state changes
        current_states: dict[str, AgentStatus] = {}
        for agent in agents:
            current_states[agent.session_id] = agent.status
            old = self._prev_states.get(agent.session_id)
            if old is not None and old != agent.status:
                name = agent.project_name or agent.session_id[:12]
                from clorch.constants import STATUS_DISPLAY
                _, old_label, _ = STATUS_DISPLAY[old]
                _, new_label, _ = STATUS_DISPLAY[agent.status]
                severity = "warning" if agent.needs_attention else "information"
                self.notify(f"{name}: {old_label} \u2192 {new_label}", severity=severity)
        self._prev_states = current_states

        # Update detail if visible
        if self._detail_mode != "hidden":
            selected = table.get_selected_agent()
            if self._is_narrow:
                self.query_one("#narrow-detail", AgentDetail).show_agent(selected)
            else:
                self.query_one("#detail-panel", AgentDetail).show_agent(selected)

        # First-permission hint (one-time toast)
        has_perm = any(item.actionable for item in self._action_items)
        if has_perm and not self._has_ever_approved and not self._hint_shown:
            self._hint_shown = True
            self.notify(
                "Permission needed! Press letter (e.g. [a]) to select, "
                "then [y] to approve. [?] for help",
                severity="warning",
                timeout=8,
            )

        # Update footer context
        self._update_footer_mode()

    def _update_footer_mode(self) -> None:
        """Set the footer mode based on current state."""
        footer = self.query_one("#context-footer", ContextFooter)
        if self._focused_action:
            footer.set_mode("approval")
        elif self._action_items:
            footer.set_mode("actions")
        else:
            footer.set_mode("default")

    # ------------------------------------------------------------------
    # Key dispatch
    # ------------------------------------------------------------------

    def on_key(self, event: Key) -> None:
        """Dynamic key dispatch: letters for actions, numbers for sessions."""
        key = event.key

        # ? — help overlay
        if key == "question_mark":
            self.push_screen(HelpScreen())
            event.prevent_default()
            return

        # Esc — cancel focused action
        if key == "escape":
            if self._focused_action:
                self._clear_focused_action()
                event.prevent_default()
                return

        # Shift+N: new tmux window
        if key == "N":
            self._prompt_new_window()
            event.prevent_default()
            return

        # Shift+S: split selected agent's window (horizontal)
        # Shift+V: split selected agent's window (vertical)
        if key == "S":
            self._split_agent_window(horizontal=True)
            event.prevent_default()
            return
        if key == "V":
            self._split_agent_window(horizontal=False)
            event.prevent_default()
            return

        # Shift+X: kill selected agent's tmux window
        if key == "X":
            self._kill_agent_window()
            event.prevent_default()
            return

        # Shift+R: reattach — open iTerm tab to selected agent's tmux window
        if key == "R":
            self._reattach_agent_window()
            event.prevent_default()
            return

        # Shift+Y: batch approve all PERM
        if key == "Y":
            self._confirm_approve_all()
            event.prevent_default()
            return

        # y/n: approve/deny the focused action
        if key == "y" and self._focused_action:
            self._approve_action(self._focused_action)
            event.prevent_default()
            return
        if key == "n" and self._focused_action:
            self._deny_action(self._focused_action)
            event.prevent_default()
            return

        # a-z: select action by letter
        if len(key) == 1 and "a" <= key <= "z":
            action_panel = self.query_one("#action-panel", ActionPanel)
            action = action_panel.get_action(key)
            if action:
                if action.actionable:
                    # PERM: focus the action for y/n
                    self._focused_action = action
                    action_panel.set_focus(key)
                    self.query_one("#session-list", SessionList).set_action_focus(key)
                    self._update_footer_mode()
                    name = action.agent.project_name or action.agent.session_id[:12]
                    self.notify(f"Selected [{key}] {name} — press [y] approve / [n] deny")
                else:
                    # Non-actionable (ASK/ERR): jump directly
                    self._jump_to_session(action.agent)
                event.prevent_default()
                return

        # 0-9: jump to agent by row number
        if key.isdigit():
            num = int(key)
            self._select_agent_by_number(num)
            event.prevent_default()
            return

    # ------------------------------------------------------------------
    # Focus helpers
    # ------------------------------------------------------------------

    def _clear_focused_action(self) -> None:
        """Clear the focused action and reset footer/queue state."""
        self._focused_action = None
        self.query_one("#action-panel", ActionPanel).clear_focus()
        self.query_one("#session-list", SessionList).clear_action_focus()
        self._update_footer_mode()

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------

    def _approve_action(self, action: ActionItem) -> None:
        """Approve a permission request: verify status, then send 'y' + Enter."""
        agent = action.agent
        name = agent.project_name or agent.session_id[:12]

        # Safety re-poll
        if not self._manager.verify_status(agent.session_id, AgentStatus.WAITING_PERMISSION):
            self.notify(f"{name}: status changed, aborting approve", severity="warning")
            self._clear_focused_action()
            return

        if not self._send_approval(agent, "y"):
            return

        self._has_ever_approved = True
        self.notify(f"Approved: {name}")
        self._clear_focused_action()

    def _deny_action(self, action: ActionItem) -> None:
        """Deny a permission request: verify status, then send 'n' + Enter."""
        agent = action.agent
        name = agent.project_name or agent.session_id[:12]

        # Safety re-poll
        if not self._manager.verify_status(agent.session_id, AgentStatus.WAITING_PERMISSION):
            self.notify(f"{name}: status changed, aborting deny", severity="warning")
            self._clear_focused_action()
            return

        if not self._send_approval(agent, "n"):
            return

        self._has_ever_approved = True
        self.notify(f"Denied: {name}")
        self._clear_focused_action()

    def _send_approval(self, agent: AgentState, key: str) -> bool:
        """Map agent to tmux window and send keystroke.

        If tmux is not available, falls back to jumping to the iTerm tab
        so the user can approve/deny manually.
        """
        from clorch.tmux.navigator import map_agent_to_window, jump_to_iterm_tab
        from clorch.tmux.session import TmuxSession

        name = agent.project_name or agent.session_id[:12]

        tmux = TmuxSession()
        if tmux.is_available() and tmux.exists():
            window = map_agent_to_window(agent, tmux)
            if window:
                target = tmux.get_pane_target(window, agent.tmux_pane or "0")
                tmux.send_keys(target, key, literal=True)
                tmux.send_keys(target, "Enter")
                return True

        # No tmux — try iTerm tab switch so user can respond manually
        if jump_to_iterm_tab(agent):
            action = "approve" if key == "y" else "deny"
            self.notify(f"Switched to {name} — please {action} manually", severity="information")
            return True

        self.notify(f"No window/tab found for {name}", severity="error")
        return False

    def _confirm_approve_all(self) -> None:
        """Batch-approve all PERM action items."""
        approvable = [item for item in self._action_items if item.actionable]
        if not approvable:
            self.notify("No permission requests to approve", severity="information")
            return

        approved = 0
        for item in approvable:
            agent = item.agent
            if self._manager.verify_status(agent.session_id, AgentStatus.WAITING_PERMISSION):
                if self._send_approval(agent, "y"):
                    approved += 1

        self._has_ever_approved = True
        self.notify(f"Approved {approved}/{len(approvable)} permission requests")
        self._clear_focused_action()

    def _select_agent_by_number(self, num: int) -> None:
        """Select an agent by number key and optionally jump to its session."""
        table = self.query_one("#session-list", SessionList)
        agent = table.get_agent_by_number(num)
        if agent:
            # Move cursor to that row
            idx = num - 1 if num != 0 else 9
            if 0 <= idx < len(table._agents):
                table.move_cursor(row=idx)
            if self._detail_mode != "hidden":
                detail_id = "#narrow-detail" if self._is_narrow else "#detail-panel"
                self.query_one(detail_id, AgentDetail).show_agent(agent)

    def _jump_to_session(self, agent: AgentState) -> None:
        """Jump to the terminal running the agent's Claude process.

        Two paths depending on how the agent is running:
        - **tmux**: ``select-window`` + ``select-pane`` (CC mode
          auto-switches the iTerm tab), then bring iTerm to front.
        - **plain iTerm**: PID → tty → iTerm tab activation.

        Dead processes are cleaned up inline so the user never lands
        on a stale tab.
        """
        from clorch.tmux.navigator import (
            jump_to_iterm_tab, select_tmux_pane, bring_iterm_to_front,
            pid_alive,
        )

        name = agent.project_name or agent.session_id[:12]

        # Dead process check — remove stale state file immediately
        if agent.pid and not pid_alive(agent.pid):
            state_file = self._manager._state_dir / f"{agent.session_id}.json"
            state_file.unlink(missing_ok=True)
            self.notify(f"{name}: process dead, removed", severity="warning")
            return

        # tmux session: select-window + select-pane (CC mode follows)
        if agent.tmux_window:
            if select_tmux_pane(agent):
                bring_iterm_to_front()
                self.notify(f"Jumped to {name}")
                return

        # Plain iTerm: PID → tty → tab
        if jump_to_iterm_tab(agent):
            self.notify(f"Jumped to {name}")
            return

        if not agent.pid:
            self.notify(f"{name}: no PID — restart session", severity="warning")
        else:
            self.notify(f"No tab found for {name}", severity="warning")

    def _apply_tmux_statusbar(self) -> None:
        """Apply clorch status bar options to an existing tmux session."""
        from clorch.tmux.session import TmuxSession
        tmux = TmuxSession()
        if tmux.is_available() and tmux.exists():
            tmux._apply_options()
            tmux._apply_keybindings()

    def _init_header_tmux(self) -> None:
        """Set the tmux session name in the header bar."""
        from clorch.tmux.session import TmuxSession
        tmux = TmuxSession()
        if tmux.is_available() and tmux.exists():
            self.query_one("#header-bar", HeaderBar).set_tmux_session(tmux.session)

    # ------------------------------------------------------------------
    # Tmux window / pane management
    # ------------------------------------------------------------------

    def _get_tmux(self, create: bool = False):
        """Return a TmuxSession if available, else None with a toast.

        When *create* is ``True``, a new detached session is created
        automatically if one doesn't exist yet.
        """
        from clorch.tmux.session import TmuxSession
        tmux = TmuxSession()
        if not tmux.is_available():
            self.notify("tmux not installed", severity="error")
            return None
        if not tmux.exists():
            if create:
                tmux._create_session()
                tmux._apply_options()
                tmux._apply_keybindings()
            else:
                self.notify("No tmux session — press [N] to create a window", severity="warning")
                return None
        return tmux

    def _open_tmux_tab(self, tmux, window: str) -> None:
        """Open an iTerm tab attached to a specific tmux window.

        Uses ``exec tmux new-session`` (no ``-d``) so the shell in the
        new tab is replaced by the tmux client immediately.  A linked
        session is created grouped with the main session and pinned to
        *window*.  ``destroy-unattached`` is set via ``\\;`` *after*
        the attach so the session isn't killed prematurely.
        """
        import os
        import shlex
        import subprocess

        session = tmux.session
        linked = f"{session}-{window}"
        q_linked = shlex.quote(linked)
        q_session = shlex.quote(session)
        q_window = shlex.quote(window)
        # Background monitor approach:
        # 1. Spawn a HUP-immune subshell that polls for the linked session
        # 2. exec replaces the shell with the tmux client
        # 3. When Cmd+W closes the tab → tmux client exits →
        #    destroy-unattached kills linked session →
        #    monitor detects it → kill-window cleans up the tmux window
        cmd = (
            f"(trap '' HUP; while tmux has-session -t {q_linked} 2>/dev/null; "
            f"do sleep 1; done; "
            f"tmux kill-window -t {q_session}:{q_window} 2>/dev/null) & "
            f"tmux kill-session -t {q_linked} 2>/dev/null; "
            f"sleep 0.2; "
            f"exec tmux new-session -t {q_session} -s {q_linked} "
            f"\\; select-window -t :{q_window} "
            f"\\; set-option destroy-unattached on"
        )

        if os.environ.get("TERM_PROGRAM", "") == "iTerm.app":
            from clorch.notifications.macos import _escape
            safe_cmd = _escape(cmd)
            script = f'''
                tell application "iTerm2"
                    tell current window
                        set newTab to (create tab with default profile)
                        tell current session of newTab
                            write text "{safe_cmd}"
                        end tell
                    end tell
                end tell
            '''
            subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, timeout=5,
            )
        else:
            self.notify(
                f"Run: {cmd}",
                severity="information",
            )

    def _prompt_new_window(self) -> None:
        """Show a modal prompt and create a new tmux window."""
        def on_result(name: str | None) -> None:
            if not name:
                return
            from clorch.tmux.session import TmuxSession
            tmux = TmuxSession()
            if not tmux.is_available():
                self.notify("tmux not installed", severity="error")
                return

            if not tmux.exists():
                # Create session with this window as the first
                tmux.run_command(
                    "new-session", "-d", "-s", tmux.session, "-n", name,
                )
                tmux._apply_options()
                tmux._apply_keybindings()
            else:
                # Check if window already exists — reattach instead of creating a duplicate
                existing = [w["name"] for w in tmux.list_windows()]
                if name not in existing:
                    tmux.add_window(name)

            self._open_tmux_tab(tmux, name)
            self.notify(f"Opened window: {name}")

        self.push_screen(PromptScreen("New window name:", placeholder="backend"), on_result)

    def _split_agent_window(self, horizontal: bool) -> None:
        """Split the selected agent's tmux window."""
        tmux = self._get_tmux()
        if not tmux:
            return

        table = self.query_one("#session-list", SessionList)
        agent = table.get_selected_agent()
        if not agent:
            self.notify("No agent selected", severity="warning")
            return

        from clorch.tmux.navigator import map_agent_to_window
        window = map_agent_to_window(agent, tmux)
        if not window:
            self.notify(f"No tmux window for {agent.project_name}", severity="warning")
            return

        direction = "horizontal" if horizontal else "vertical"
        if tmux.split_window(window, horizontal=horizontal, cwd=agent.cwd or None):
            self.notify(f"Split {agent.project_name} ({direction})")
        else:
            self.notify(f"Failed to split {agent.project_name}", severity="error")

    def _kill_agent_window(self) -> None:
        """Kill the selected agent's tmux window (and processes inside it)."""
        tmux = self._get_tmux()
        if not tmux:
            return

        table = self.query_one("#session-list", SessionList)
        agent = table.get_selected_agent()
        if not agent:
            self.notify("No agent selected", severity="warning")
            return

        from clorch.tmux.navigator import map_agent_to_window
        window = map_agent_to_window(agent, tmux)
        if not window:
            self.notify(f"No tmux window for {agent.project_name}", severity="warning")
            return

        name = agent.project_name or agent.session_id[:12]
        result = tmux.run_command(
            "kill-window", "-t", f"{tmux.session}:{window}", check=False,
        )
        if result.returncode == 0:
            self.notify(f"Killed window: {name}")
        else:
            self.notify(f"Failed to kill {name}", severity="error")

    def _reattach_agent_window(self) -> None:
        """Open an iTerm tab attached to the selected agent's tmux window."""
        tmux = self._get_tmux()
        if not tmux:
            return

        table = self.query_one("#session-list", SessionList)
        agent = table.get_selected_agent()
        if not agent:
            self.notify("No agent selected", severity="warning")
            return

        from clorch.tmux.navigator import map_agent_to_window
        window = map_agent_to_window(agent, tmux)
        if not window:
            self.notify(f"No tmux window for {agent.project_name}", severity="warning")
            return

        name = agent.project_name or agent.session_id[:12]
        self._open_tmux_tab(tmux, window)
        self.notify(f"Reattached: {name}")

    # ------------------------------------------------------------------
    # Standard actions
    # ------------------------------------------------------------------

    def on_session_list_agent_highlighted(self, event: SessionList.AgentHighlighted) -> None:
        """Update detail panel when cursor moves to a new agent."""
        if self._detail_mode != "hidden":
            if self._is_narrow:
                self.query_one("#narrow-detail", AgentDetail).show_agent(event.agent)
            else:
                self.query_one("#detail-panel", AgentDetail).show_agent(event.agent)

    def action_toggle_detail(self) -> None:
        """Cycle detail panel: normal -> expanded -> hidden -> normal."""
        detail = self.query_one("#detail-panel", AgentDetail)
        action_panel = self.query_one("#action-panel", ActionPanel)

        if self._detail_mode == "normal":
            self._detail_mode = "expanded"
        elif self._detail_mode == "expanded":
            self._detail_mode = "hidden"
        else:
            self._detail_mode = "normal"

        self._detail_visible = self._detail_mode != "hidden"
        self._apply_detail_mode(detail, action_panel)

    def _apply_detail_mode(self, detail: AgentDetail, action_panel: ActionPanel) -> None:
        """Apply CSS classes and content based on current detail mode."""
        narrow_detail = self.query_one("#narrow-detail", AgentDetail)

        # Reset all mode classes
        detail.remove_class("expanded", "detail-hidden")
        action_panel.remove_class("detail-expanded")

        table = self.query_one("#session-list", SessionList)
        agent = table.get_selected_agent()

        if self._detail_mode == "normal":
            # Both visible, detail has max-height cap
            if self._is_narrow:
                narrow_detail.show_agent(agent)
            else:
                detail.show_agent(agent)
        elif self._detail_mode == "expanded":
            # Detail takes full sidebar, action panel hidden
            detail.add_class("expanded")
            action_panel.add_class("detail-expanded")
            if self._is_narrow:
                narrow_detail.show_agent(agent)
            else:
                detail.show_agent(agent)
        else:
            # Hidden — detail gone, action panel takes full sidebar
            detail.add_class("detail-hidden")
            detail.show_agent(None)
            narrow_detail.show_agent(None)

    def action_jump_to_agent(self) -> None:
        """Jump to the selected agent's tmux window."""
        table = self.query_one("#session-list", SessionList)
        agent = table.get_selected_agent()
        if agent:
            self._jump_to_session(agent)

    def action_refresh(self) -> None:
        self._poll_state()
        self.notify("Refreshed")

    def action_cursor_down(self) -> None:
        self.query_one("#session-list", SessionList).action_cursor_down()

    def action_cursor_up(self) -> None:
        self.query_one("#session-list", SessionList).action_cursor_up()


def run_dashboard() -> None:
    """Entry point to launch the dashboard."""
    app = OrchestratorApp()
    app.run()
