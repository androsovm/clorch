"""Scan and aggregate agent state files from disk."""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from clorch.config import STATE_DIR
from clorch.constants import AgentStatus
from clorch.state.history import HistoryResolver
from clorch.state.models import AgentState, StatusSummary

log = logging.getLogger(__name__)


class StateManager:
    """Read-only manager that scans agent state files on disk.

    Each agent writes its own ``<session_id>.json`` into *STATE_DIR*.
    This class reads those files and provides query / cleanup helpers.
    """

    def __init__(self, state_dir: Path = STATE_DIR) -> None:
        self._state_dir = state_dir
        self._history = HistoryResolver()

    # ------------------------------------------------------------------
    # Core scanning
    # ------------------------------------------------------------------

    def scan(self) -> list[AgentState]:
        """Read every ``*.json`` in *state_dir*, return sorted by project name."""
        agents: list[AgentState] = []
        if not self._state_dir.is_dir():
            return agents

        for path in self._state_dir.glob("*.json"):
            try:
                agent = AgentState.from_json_file(path)
                agents.append(agent)
            except (OSError, ValueError, KeyError) as exc:
                log.warning("Skipping corrupt state file %s: %s", path, exc)
                continue

        agents.sort(key=lambda a: a.project_name.lower())
        self._enrich_session_names(agents)
        return agents

    def _enrich_session_names(self, agents: list[AgentState]) -> None:
        """Fill ``session_name`` on each agent from Claude Code history."""
        ids = {a.session_id for a in agents}
        names = self._history.resolve_many(ids)
        for agent in agents:
            agent.session_name = names.get(agent.session_id, "")

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_summary(self) -> StatusSummary:
        """Aggregate all agent states into a single summary."""
        return StatusSummary.from_agents(self.scan())

    def get_agent(self, session_id: str) -> AgentState | None:
        """Return the agent matching *session_id*, or ``None``."""
        path = self._state_dir / f"{session_id}.json"
        if not path.is_file():
            return None
        try:
            agent = AgentState.from_json_file(path)
        except (OSError, ValueError, KeyError) as exc:
            log.warning("Failed to read agent %s: %s", session_id, exc)
            return None
        agent.session_name = self._history.resolve(agent.session_id)
        return agent

    def verify_status(self, session_id: str, expected: "AgentStatus") -> bool:
        """Re-read the state file and confirm the agent is still in *expected* status.

        Safety guard before sending approve/deny keystrokes — prevents
        misfire if the agent changed state between the TUI poll and the
        user pressing a key.
        """
        agent = self.get_agent(session_id)
        if agent is None:
            return False
        return agent.status == expected

    def get_attention_agents(self) -> list[AgentState]:
        """Agents whose status requires user attention.

        This includes ``WAITING_PERMISSION``, ``WAITING_ANSWER``, and
        ``ERROR`` (anything where :pyattr:`AgentState.needs_attention`
        is ``True``).
        """
        return [a for a in self.scan() if a.needs_attention]

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def cleanup_stale(self, max_age_seconds: int = 3600) -> int:
        """Remove state files for dead processes and duplicates.

        Detection strategy:
        1. If a ``pid`` is stored, check ``kill(pid, 0)`` — remove if dead.
        2. If no ``pid``, fall back to *max_age_seconds* on *last_event_time*.
        3. Deduplicate by PID: when multiple state files share the same
           PID, keep the one with the highest ``tool_count`` (most active)
           and remove the rest.

        Returns the number of files removed.
        """
        if not self._state_dir.is_dir():
            return 0

        now = time.time()
        removed = 0

        # First pass: collect all agents, remove dead/stale ones.
        # Track live agents by PID for dedup in second pass.
        pid_map: dict[int, list[tuple[Path, AgentState]]] = {}

        for path in self._state_dir.glob("*.json"):
            try:
                agent = AgentState.from_json_file(path)
            except (OSError, ValueError, KeyError) as exc:
                log.warning("Cannot parse %s during cleanup: %s", path, exc)
                continue

            should_remove = False

            if agent.pid is not None:
                # PID-based: check if process is alive
                try:
                    os.kill(agent.pid, 0)
                except ProcessLookupError:
                    # Process is dead
                    should_remove = True
                except PermissionError:
                    # Process exists but we can't signal it — keep it
                    pass
            else:
                # No PID — fall back to time-based cleanup
                if not agent.last_event_time:
                    file_age = now - path.stat().st_mtime
                else:
                    try:
                        ts = datetime.fromisoformat(
                            agent.last_event_time.replace("Z", "+00:00"),
                        )
                        file_age = (datetime.now(timezone.utc) - ts).total_seconds()
                    except (ValueError, TypeError):
                        file_age = now - path.stat().st_mtime
                if file_age > max_age_seconds:
                    should_remove = True

            if should_remove:
                try:
                    path.unlink()
                    removed += 1
                    log.info("Removed stale state file %s (pid=%s)", path.name, agent.pid)
                except OSError as exc:
                    log.warning("Could not remove %s: %s", path, exc)
            elif agent.pid is not None:
                pid_map.setdefault(agent.pid, []).append((path, agent))

        # Second pass: deduplicate by PID — keep the most active session.
        for pid, entries in pid_map.items():
            if len(entries) <= 1:
                continue
            # Keep the entry with the highest tool_count
            entries.sort(key=lambda e: e[1].tool_count, reverse=True)
            for path, agent in entries[1:]:
                try:
                    path.unlink()
                    removed += 1
                    log.info(
                        "Removed duplicate state file %s (pid=%d, tool_count=%d)",
                        path.name, pid, agent.tool_count,
                    )
                except OSError as exc:
                    log.warning("Could not remove %s: %s", path, exc)

        # Third pass: reset stale WAITING_PERMISSION (called from
        # poll cycle too, but run here as well for completeness).
        self.reset_stale_permissions(now)

        return removed

    def reset_stale_permissions(self, now: float | None = None, ttl_seconds: int = 30) -> None:
        """Reset WAITING_PERMISSION states for dead processes.

        Permission prompts block the Claude turn.  When the user responds
        (approve or deny) the turn continues and new events update the
        state file.  However, Claude Code does NOT fire a ``Stop`` event
        after permission denial — the session goes to an "Interrupted"
        prompt with no hook.  Additionally, async hook race conditions
        can cause PermissionRequest to overwrite Stop's IDLE.

        If the Claude Code process is still alive, the permission is
        legitimately pending (the user may still be reading the request)
        — leave it alone.  Only reset when the process is dead or the
        file has been stale for *ttl_seconds* without a PID to check.
        """
        if now is None:
            now = time.time()
        if not self._state_dir.is_dir():
            return

        for path in self._state_dir.glob("*.json"):
            try:
                file_age = now - path.stat().st_mtime
                if file_age < ttl_seconds:
                    continue
                agent = AgentState.from_json_file(path)
            except (OSError, ValueError, KeyError):
                continue

            if agent.status != AgentStatus.WAITING_PERMISSION:
                continue

            # If the process is still alive, the permission is genuinely
            # pending — the user may be reading the request or thinking.
            # Only reset when the process is confirmed dead.
            if agent.pid is not None:
                try:
                    os.kill(agent.pid, 0)
                    continue  # Process alive → permission still pending
                except ProcessLookupError:
                    pass  # Process dead → safe to reset
                except PermissionError:
                    continue  # Process exists but can't signal → keep

            # Patch the JSON on disk: status → IDLE, clear stale fields.
            try:
                data = json.loads(path.read_text())
                data["status"] = "IDLE"
                data["tool_request_summary"] = None
                path.write_text(json.dumps(data))
                log.info(
                    "Reset stale WAITING_PERMISSION → IDLE for %s (age=%ds, pid=%s dead)",
                    path.name, int(file_age), agent.pid,
                )
            except OSError as exc:
                log.warning("Could not reset %s: %s", path, exc)
