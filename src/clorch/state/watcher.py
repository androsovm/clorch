"""Background watcher that polls agent state files for changes."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable

from clorch.config import STATE_DIR, STATE_POLL_INTERVAL_MS
from clorch.state.manager import StateManager
from clorch.state.models import AgentState, StatusSummary

log = logging.getLogger(__name__)

OnChangeCallback = Callable[[list[AgentState], StatusSummary], None]


class StateWatcher:
    """Polls *STATE_DIR* for agent state changes and invokes a callback.

    The watcher runs in a daemon thread so it is automatically cleaned
    up when the main process exits.

    Parameters
    ----------
    on_change:
        Called whenever the set of agents or any individual state
        changes.  Receives the full agent list and an up-to-date
        :class:`StatusSummary`.
    poll_interval_ms:
        Milliseconds between scans.  Defaults to
        :data:`STATE_POLL_INTERVAL_MS` from config.
    state_dir:
        Override the directory to watch (useful for tests).
    """

    def __init__(
        self,
        on_change: OnChangeCallback | None = None,
        poll_interval_ms: int = STATE_POLL_INTERVAL_MS,
        state_dir: Path | None = None,
    ) -> None:
        self._manager = StateManager(state_dir if state_dir is not None else STATE_DIR)  # type: ignore[arg-type]
        self._on_change = on_change
        self._poll_interval_s = poll_interval_ms / 1000.0

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        # Protected by _lock
        self._agents: list[AgentState] = []
        self._summary: StatusSummary = StatusSummary()
        self._snapshot: dict[str, str] = {}  # session_id -> repr key for diff

    # ------------------------------------------------------------------
    # Public properties (thread-safe)
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def agents(self) -> list[AgentState]:
        """Current agent list.  Safe to read from any thread."""
        with self._lock:
            return list(self._agents)

    @property
    def summary(self) -> StatusSummary:
        """Current aggregate summary.  Safe to read from any thread."""
        with self._lock:
            return self._summary

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background polling thread."""
        if self.is_running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="state-watcher",
            daemon=True,
        )
        self._thread.start()
        log.debug("StateWatcher started (interval=%dms)", int(self._poll_interval_s * 1000))

    def stop(self) -> None:
        """Signal the polling thread to stop and wait for it to finish."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        log.debug("StateWatcher stopped")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run(self) -> None:
        """Main loop executed inside the daemon thread."""
        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception:
                log.exception("Unexpected error in state watcher tick")
            self._stop_event.wait(timeout=self._poll_interval_s)

    def _tick(self) -> None:
        """Single poll cycle: scan, diff, notify."""
        agents = self._manager.scan()
        new_snapshot = self._build_snapshot(agents)

        if new_snapshot == self._snapshot:
            return  # nothing changed

        summary = StatusSummary.from_agents(agents)

        with self._lock:
            self._agents = agents
            self._summary = summary
            self._snapshot = new_snapshot

        if self._on_change is not None:
            try:
                self._on_change(agents, summary)
            except Exception:
                log.exception("Error in on_change callback")

    @staticmethod
    def _build_snapshot(agents: list[AgentState]) -> dict[str, str]:
        """Create a lightweight fingerprint dict for change detection.

        Each value encodes the fields we care about for diffing so we
        can cheaply compare two snapshots with ``==``.
        """
        return {
            a.session_id: (
                f"{a.status.value}|{a.last_event_time}|{a.tool_count}"
                f"|{a.error_count}|{a.notification_message}"
                f"|{len(a.running_subagents)}:{len(a.subagents)}|{a.compact_count}|{a.task_completed_count}"
            )
            for a in agents
        }
