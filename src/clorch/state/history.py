"""Resolve session display names from Claude Code history."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from clorch.config import CLAUDE_HISTORY_PATH

log = logging.getLogger(__name__)

_MAX_DISPLAY_LEN = 80


class HistoryResolver:
    """Look up session display names from ``~/.claude/history.jsonl``.

    Caches the mapping and only re-reads the file when its mtime changes.
    """

    def __init__(self, history_path: Path = CLAUDE_HISTORY_PATH) -> None:
        self._path = history_path
        self._cache: dict[str, str] = {}
        self._mtime: float = 0.0

    def _refresh(self) -> None:
        """Re-read the history file if it has changed on disk."""
        try:
            stat = self._path.stat()
        except OSError:
            return

        if stat.st_mtime == self._mtime:
            return

        self._mtime = stat.st_mtime
        cache: dict[str, str] = {}
        try:
            with self._path.open() as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue
                    sid = entry.get("sessionId")
                    display = entry.get("display")
                    if sid and display and sid not in cache:
                        cache[sid] = display[:_MAX_DISPLAY_LEN]
        except OSError as exc:
            log.warning("Could not read history file %s: %s", self._path, exc)
            return

        self._cache = cache

    def resolve(self, session_id: str) -> str:
        """Return the display name for *session_id*, or ``""``."""
        self._refresh()
        return self._cache.get(session_id, "")

    def resolve_many(self, session_ids: set[str]) -> dict[str, str]:
        """Return ``{session_id: display}`` for all known ids in *session_ids*."""
        self._refresh()
        return {sid: self._cache[sid] for sid in session_ids if sid in self._cache}
