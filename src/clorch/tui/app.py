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
from clorch.constants import AgentStatus, ANIM_INTERVAL, TELEMETRY_HISTORY_LEN, TELEMETRY_BUCKET_TICKS
from clorch.config import RULES_PATH
from clorch.rules import RulesConfig, load_rules, evaluate
from clorch.tui.widgets.session_list import SessionList, ListHeader
from clorch.tui.widgets.agent_detail import AgentDetail
from clorch.tui.widgets.header_bar import HeaderBar
from clorch.tui.widgets.context_footer import ContextFooter
from clorch.tui.widgets.telemetry_panel import TelemetryPanel
from clorch.tui.widgets.event_log import EventLog
from clorch.tui.widgets.settings_panel import SettingsPanel


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
        max-height: 38;
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

        text.append("SETTINGS\n", style=f"bold {YELLOW}")
        text.append("  [s]", style=f"bold {CYAN}")
        text.append("       Toggle sound notifications\n")
        text.append("  [!]", style=f"bold {CYAN}")
        text.append("       Toggle YOLO mode (auto-approve)\n\n")

        text.append("YOLO MODE & AUTO-APPROVE RULES\n", style=f"bold {YELLOW}")
        text.append("  Config: ", style="dim")
        text.append("~/.config/clorch/rules.yaml\n", style=f"{CYAN}")
        text.append("  YOLO auto-approves all tools (tmux-only)\n", style="")
        text.append("  ", style="")
        text.append("Deny rules \u2192 manual review", style=f"bold {RED}")
        text.append(", even in YOLO\n")
        text.append("  Rules: tools + optional regex pattern\n", style="")
        text.append("  First matching rule wins, default: ask\n\n", style="dim")

        text.append("TMUX MANAGEMENT\n", style=f"bold {YELLOW}")
        text.append("  [N]", style=f"bold {CYAN}")
        text.append("       Create new tmux window\n")
        text.append("  [R]", style=f"bold {CYAN}")
        text.append("       Open terminal tab for selected agent\n")
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
        self._prev_tool_counts: dict[str, int] = {}
        self._extended_history: dict[str, list[int]] = {}
        self._pending_deltas: dict[str, int] = {}
        self._telemetry_tick: int = 0
        self._rules_config: RulesConfig = RulesConfig()
        self._skip_warned: set[str] = set()  # session IDs already warned about no-tmux skip
        self._usage_tracker = None  # lazy-init UsageTracker
        self._usage_summary = None  # cached UsageSummary

    def compose(self) -> ComposeResult:
        yield HeaderBar(id="header-bar")
        with Horizontal(id="main-split"):
            with Vertical(id="list-pane") as lp:
                lp.border_title = "Agents"
                yield ListHeader(id="list-header")
                yield SessionList(id="session-list")
            with Vertical(id="right-panel"):
                settings = SettingsPanel(id="settings-panel")
                settings.border_title = "Settings"
                yield settings
                detail = AgentDetail(id="detail-panel")
                detail.border_title = "Detail"
                yield detail
                telemetry = TelemetryPanel(id="telemetry-panel")
                telemetry.border_title = "Telemetry"
                yield telemetry
                event_log = EventLog(id="event-log-panel")
                event_log.border_title = "Events"
                yield event_log
        yield ContextFooter(id="context-footer")

    def on_mount(self) -> None:
        self._refresh_timer = self.set_interval(0.5, self._poll_state)
        self._cleanup_timer = self.set_interval(30, self._run_cleanup)
        self._perm_check_timer = self.set_interval(5, self._check_stale_permissions)
        self._anim_timer = self.set_interval(ANIM_INTERVAL, self._tick_animation)
        from clorch.config import USAGE_POLL_INTERVAL
        self._usage_timer = self.set_interval(USAGE_POLL_INTERVAL, self._poll_usage)
        self._load_rules()
        self._run_cleanup()
        self._poll_state()
        self._poll_usage()
        self._apply_tmux_statusbar()
        self._init_header_tmux()

    def _load_rules(self) -> None:
        """Load auto-approve rules from config file."""
        self._rules_config = load_rules(RULES_PATH)
        settings = self.query_one("#settings-panel", SettingsPanel)
        settings.set_rules_count(len(self._rules_config.rules))
        settings.set_yolo(self._rules_config.yolo)
        self.query_one("#header-bar", HeaderBar).set_yolo(self._rules_config.yolo)

    def _check_stale_permissions(self) -> None:
        """Reset WAITING_PERMISSION states stuck after denial (no Stop event)."""
        self._manager.reset_stale_permissions()

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

        # Auto-approve/deny via rules engine (tmux-only)
        self._auto_evaluate_actions()

        # Update session list (agents + inline action hints)
        table = self.query_one("#session-list", SessionList)
        table.update_agents(agents)
        table.update_actions(self._action_items)

        # --- Event detection (BEFORE updating _prev_states and _prev_tool_counts) ---
        event_log = self.query_one("#event-log-panel", EventLog)
        for agent in agents:
            sid = agent.session_id
            old_status = self._prev_states.get(sid)
            if old_status is None:
                continue  # new agent, skip
            if old_status != agent.status:
                # Reset skip-warning when agent leaves WAITING_PERMISSION
                if old_status == AgentStatus.WAITING_PERMISSION:
                    self._skip_warned.discard(sid)
                # Status transition events
                if agent.status == AgentStatus.WORKING:
                    event_log.write_event(agent.project_name, "\u25b6", agent.last_tool or "working", "green")
                elif agent.status == AgentStatus.IDLE:
                    event_log.write_event(agent.project_name, "\u25fc", "idle", "grey")
                elif agent.status == AgentStatus.WAITING_PERMISSION:
                    summary_text = (agent.tool_request_summary or "")[:60]
                    event_log.write_event(agent.project_name, "\u26a0", f"PERM: {summary_text}", "red")
                elif agent.status == AgentStatus.ERROR:
                    event_log.write_event(agent.project_name, "\u2717", "error", "pink")
            # Tool usage (delta > 0 and status stayed WORKING)
            elif agent.status == AgentStatus.WORKING:
                delta = max(0, agent.tool_count - self._prev_tool_counts.get(sid, agent.tool_count))
                if delta > 0 and agent.last_tool:
                    event_log.write_event(agent.project_name, "\u2699", agent.last_tool, "cyan")

        # --- Toast on state changes + sound alerts ---
        sound_status: AgentStatus | None = None
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
                # Track highest-priority attention status for sound
                if agent.needs_attention and sound_status is None:
                    sound_status = agent.status
        self._prev_states = current_states

        # Play sound alert (once per poll cycle, highest priority)
        if sound_status and self.query_one("#settings-panel", SettingsPanel).sound_enabled:
            from clorch.notifications.sound import play_status_sound
            play_status_sound(sound_status)

        # --- Extended history update (bucketed) ---
        for agent in agents:
            sid = agent.session_id
            prev_tc = self._prev_tool_counts.get(sid, agent.tool_count)
            delta = max(0, agent.tool_count - prev_tc)
            self._prev_tool_counts[sid] = agent.tool_count
            self._pending_deltas[sid] = self._pending_deltas.get(sid, 0) + delta

        self._telemetry_tick += 1
        if self._telemetry_tick >= TELEMETRY_BUCKET_TICKS:
            self._telemetry_tick = 0
            for sid, accumulated in self._pending_deltas.items():
                hist = self._extended_history.setdefault(sid, [0] * TELEMETRY_HISTORY_LEN)
                hist.append(accumulated)
                if len(hist) > TELEMETRY_HISTORY_LEN:
                    self._extended_history[sid] = hist[-TELEMETRY_HISTORY_LEN:]
            self._pending_deltas.clear()

        # Cleanup dead sessions
        dead = set(self._extended_history) - {a.session_id for a in agents}
        for sid in dead:
            self._extended_history.pop(sid, None)
            self._prev_tool_counts.pop(sid, None)
            self._pending_deltas.pop(sid, None)
            self._skip_warned.discard(sid)

        # --- Update detail + telemetry if visible ---
        if self._detail_mode != "hidden":
            selected = table.get_selected_agent()
            detail_panel = self.query_one("#detail-panel", AgentDetail)
            # Set per-agent usage data before rendering
            if selected and self._usage_summary:
                session_usage = self._usage_summary.sessions.get(selected.session_id)
                detail_panel.set_usage(session_usage)
            else:
                detail_panel.set_usage(None)
            detail_panel.show_agent(selected)
            selected_id = selected.session_id if selected else None
            self.query_one("#telemetry-panel", TelemetryPanel).update_agents(
                agents, selected_id, self._extended_history
            )

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
    # Auto-approve / YOLO
    # ------------------------------------------------------------------

    def _auto_evaluate_actions(self) -> None:
        """Run rules engine on WAITING_PERMISSION agents and auto-approve/deny."""
        event_log = self.query_one("#event-log-panel", EventLog)
        remaining: list[ActionItem] = []

        for item in self._action_items:
            if not item.actionable:
                remaining.append(item)
                continue

            agent = item.agent
            tool_name = agent.last_tool or ""
            tool_summary = agent.tool_request_summary or ""
            decision = evaluate(self._rules_config, tool_name, tool_summary)

            if decision == "ask":
                remaining.append(item)
                continue

            # Only auto-approve/deny agents in tmux sessions
            if not agent.tmux_window:
                if agent.session_id not in self._skip_warned:
                    self._skip_warned.add(agent.session_id)
                    name = agent.project_name or agent.session_id[:12]
                    event_log.write_event(name, "\u26a0", "skip auto-approve: no tmux", "yellow")
                remaining.append(item)
                continue

            name = agent.project_name or agent.session_id[:12]

            # Safety re-poll before acting
            if not self._manager.verify_status(agent.session_id, AgentStatus.WAITING_PERMISSION):
                remaining.append(item)
                continue

            key = "y" if decision == "approve" else "n"
            if self._send_approval(agent, key):
                label = "auto-approved" if decision == "approve" else "auto-denied"
                icon = "\u2714" if decision == "approve" else "\u2718"
                color = "green" if decision == "approve" else "red"
                event_log.write_event(name, icon, f"{label}: {tool_name}", color)
            else:
                remaining.append(item)

        self._action_items = remaining

    def _toggle_yolo(self) -> None:
        """Toggle YOLO mode on/off (runtime override of config)."""
        self._rules_config.yolo = not self._rules_config.yolo
        yolo = self._rules_config.yolo
        self.query_one("#header-bar", HeaderBar).set_yolo(yolo)
        self.query_one("#settings-panel", SettingsPanel).set_yolo(yolo)
        if yolo:
            self.notify("YOLO mode ON \u2014 auto-approve all (tmux only)", severity="warning")
        else:
            self.notify("YOLO mode OFF")

    # ------------------------------------------------------------------
    # Key dispatch
    # ------------------------------------------------------------------

    def on_key(self, event: Key) -> None:
        """Dynamic key dispatch: letters for actions, numbers for sessions."""
        key = event.key

        # ! — toggle YOLO mode
        if key == "exclamation_mark":
            self._toggle_yolo()
            event.prevent_default()
            return

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

        # s — toggle sound notifications
        if key == "s":
            panel = self.query_one("#settings-panel", SettingsPanel)
            enabled = panel.toggle_sound()
            self.notify(f"Sound {'ON' if enabled else 'OFF'}")
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

        # y/n: approve/deny the focused action (or auto-select if single PERM)
        if key == "y":
            if self._focused_action:
                self._approve_action(self._focused_action)
            else:
                approvable = [i for i in self._action_items if i.actionable]
                if len(approvable) == 1:
                    self._approve_action(approvable[0])
                elif approvable:
                    self._focused_action = approvable[0]
                    self.query_one("#session-list", SessionList).set_action_focus(approvable[0].letter)
                    self._update_footer_mode()
                    name = approvable[0].agent.project_name or approvable[0].agent.session_id[:12]
                    self.notify(f"Multiple PERMs — focused [{approvable[0].letter}] {name}. Press [y] again to approve, or select another.")
                else:
                    return  # no PERM items, let fall through to a-z
            event.prevent_default()
            return
        if key == "n" and self._focused_action:
            self._deny_action(self._focused_action)
            event.prevent_default()
            return

        # a-z: select action by letter
        if len(key) == 1 and "a" <= key <= "z":
            action = self._get_action(key)
            if action:
                if action.actionable:
                    # PERM: focus the action for y/n
                    self._focused_action = action
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
        self.query_one("#session-list", SessionList).clear_action_focus()
        self._update_footer_mode()

    def _get_action(self, letter: str) -> ActionItem | None:
        """Look up an action by its assigned letter."""
        for item in self._action_items:
            if item.letter == letter:
                return item
        return None

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
        self.query_one("#event-log-panel", EventLog).write_event(name, "\u2714", "approved", "green")
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
        self.query_one("#event-log-panel", EventLog).write_event(name, "\u2718", "denied", "red")
        self._clear_focused_action()

    def _send_approval(self, agent: AgentState, key: str) -> bool:
        """Map agent to tmux window and send keystroke.

        Only uses tmux send-keys when the agent actually lives in a tmux
        pane (``tmux_window`` is set by the hook).  Falls back to jumping
        to the terminal tab so the user can approve/deny manually.
        Agents in unreachable terminals are blocked with a warning.
        """
        from clorch.tmux.navigator import map_agent_to_window, jump_to_tab
        from clorch.tmux.session import TmuxSession

        name = agent.project_name or agent.session_id[:12]

        # Reachability check
        table = self.query_one("#session-list", SessionList)
        if not table.is_agent_reachable(agent):
            from clorch.tui.widgets.session_list import _agent_terminal_group
            remote = _agent_terminal_group(agent)
            local = table._local_terminal
            self.notify(f"Cannot reach {name} from {local} (agent in {remote})", severity="warning")
            return False

        # Only attempt tmux send-keys when the hook confirmed the agent
        # is inside a tmux pane (tmux_window is non-empty).  Without this
        # guard, cwd-based matching can send keystrokes to an unrelated
        # zsh pane that happens to share the same working directory.
        if agent.tmux_window:
            tmux = TmuxSession(session_name=agent.tmux_session or None)
            if tmux.is_available() and tmux.exists():
                window_target = agent.tmux_window_index or agent.tmux_window
                target = tmux.get_pane_target(window_target, agent.tmux_pane or "0")
                ok = tmux.send_keys(target, key, literal=True)
                if ok:
                    tmux.send_keys(target, "Enter")
                    return True
                self.notify(f"tmux send-keys failed for {name}", severity="warning")

        # Agent is not in tmux — switch to its terminal tab
        if jump_to_tab(agent):
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
        event_log = self.query_one("#event-log-panel", EventLog)
        event_log.write_event("all", "\u2714", f"batch approved {approved}/{len(approvable)}", "green")
        self._clear_focused_action()

    def _select_agent_by_number(self, num: int) -> None:
        """Select an agent by number key and optionally jump to its session."""
        table = self.query_one("#session-list", SessionList)
        agent = table.get_agent_by_number(num)
        if agent:
            # Move cursor to that row (accounts for separators)
            idx = num - 1 if num != 0 else 9
            table.move_cursor(row=idx)
            if self._detail_mode != "hidden":
                self.query_one("#detail-panel", AgentDetail).show_agent(agent)

    def _jump_to_session(self, agent: AgentState) -> None:
        """Jump to the terminal running the agent's Claude process.

        Two paths depending on how the agent is running:
        - **tmux**: ``select-window`` + ``select-pane`` (CC mode
          auto-switches the terminal tab), then bring terminal to front.
        - **plain terminal**: PID → tty → terminal tab activation.

        Dead processes are cleaned up inline so the user never lands
        on a stale tab.  Agents in unreachable terminals are blocked
        with a warning.
        """
        from clorch.tmux.navigator import (
            jump_to_tab, jump_to_tmux_tab, select_tmux_pane,
            bring_terminal_to_front, pid_alive,
        )
        from clorch.tmux.session import TmuxSession

        name = agent.project_name or agent.session_id[:12]

        # Reachability check — can't jump to agent in a different terminal
        table = self.query_one("#session-list", SessionList)
        if not table.is_agent_reachable(agent):
            from clorch.tui.widgets.session_list import _agent_terminal_group
            remote = _agent_terminal_group(agent)
            local = table._local_terminal
            self.notify(f"Cannot reach {name} from {local} (agent in {remote})", severity="warning")
            return

        # Dead process check — remove stale state file immediately
        if agent.pid and not pid_alive(agent.pid):
            state_file = self._manager._state_dir / f"{agent.session_id}.json"
            state_file.unlink(missing_ok=True)
            self.notify(f"{name}: process dead, removed", severity="warning")
            return

        # tmux session: select-window + select-pane, then switch terminal tab
        if agent.tmux_window:
            if select_tmux_pane(agent):
                tmux = TmuxSession(session_name=agent.tmux_session or None)
                if jump_to_tmux_tab(tmux, agent.tmux_window):
                    bring_terminal_to_front()
                self.notify(f"Jumped to {name}")
                return

        # Plain terminal: PID → tty → tab
        if jump_to_tab(agent):
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

    def _poll_usage(self) -> None:
        """Poll Claude Code JSONL logs for token usage and cost data."""
        from clorch.usage.tracker import UsageTracker

        if self._usage_tracker is None:
            self._usage_tracker = UsageTracker()

        # Build list of active session JSONL paths from current agents
        # Agent cwd gives us the project dir → map to ~/.claude/projects/<slug>/*.jsonl
        active_paths: list[str] = []
        try:
            agents = self._manager.scan()
            from clorch.usage.parser import CLAUDE_PROJECTS_DIR
            if CLAUDE_PROJECTS_DIR.is_dir():
                for agent in agents:
                    if not agent.cwd:
                        continue
                    # Claude Code uses the cwd path as project slug (with - replacing /)
                    slug = agent.cwd.replace("/", "-")
                    if slug.startswith("-"):
                        slug = slug[1:]  # strip leading dash
                    project_dir = CLAUDE_PROJECTS_DIR / slug
                    if project_dir.is_dir():
                        for jsonl in project_dir.glob("*.jsonl"):
                            active_paths.append(str(jsonl))
        except Exception:
            pass

        try:
            self._usage_summary = self._usage_tracker.poll(active_paths or None)
            self.query_one("#header-bar", HeaderBar).update_usage(self._usage_summary)
        except Exception:
            pass

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
        """Open a terminal tab attached to a specific tmux window.

        Uses ``exec tmux new-session`` (no ``-d``) so the shell in the
        new tab is replaced by the tmux client immediately.  A linked
        session is created grouped with the main session and pinned to
        *window*.  ``destroy-unattached`` is set via ``\\;`` *after*
        the attach so the session isn't killed prematurely.
        """
        import shlex

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

        from clorch.terminal import get_backend
        backend = get_backend()
        if not backend.open_tab(cmd):
            # Terminal can't open tabs (e.g. Ghostty) — just switch to the
            # window inside the existing tmux session and bring terminal forward.
            tmux.select_window(window)
            backend.bring_to_front()

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
            self.query_one("#detail-panel", AgentDetail).show_agent(event.agent)

    def action_toggle_detail(self) -> None:
        """Cycle right panel: normal -> expanded -> hidden -> normal."""
        panel = self.query_one("#right-panel", Vertical)

        if self._detail_mode == "normal":
            self._detail_mode = "expanded"
        elif self._detail_mode == "expanded":
            self._detail_mode = "hidden"
        else:
            self._detail_mode = "normal"

        self._detail_visible = self._detail_mode != "hidden"
        self._apply_detail_mode(panel)

    def _apply_detail_mode(self, panel) -> None:
        """Apply CSS classes and content based on current detail mode."""
        panel.remove_class("expanded", "detail-hidden")

        if self._detail_mode == "expanded":
            panel.add_class("expanded")
        elif self._detail_mode == "hidden":
            panel.add_class("detail-hidden")

        if self._detail_mode != "hidden":
            table = self.query_one("#session-list", SessionList)
            agent = table.get_selected_agent()
            self.query_one("#detail-panel", AgentDetail).show_agent(agent)
        else:
            self.query_one("#detail-panel", AgentDetail).show_agent(None)

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
