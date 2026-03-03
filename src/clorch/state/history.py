"""Resolve session display names from Claude Code history."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from clorch.config import CLAUDE_HISTORY_PATH

log = logging.getLogger(__name__)

_MAX_DISPLAY_LEN = 80
_PROJECTS_DIR = Path.home() / ".claude" / "projects"


class HistoryResolver:
    """Look up session display names from Claude Code data.

    Sources (highest priority first):
    1. ``custom-title`` entries in session transcripts
       (``~/.claude/projects/<hash>/<session_id>.jsonl``) — set by ``/rename``.
    2. First ``display`` entry per session in ``~/.claude/history.jsonl``
       — the initial user prompt.

    Caches the mapping and only re-reads files when mtimes change.
    """

    def __init__(
        self,
        history_path: Path = CLAUDE_HISTORY_PATH,
        projects_dir: Path = _PROJECTS_DIR,
    ) -> None:
        self._path = history_path
        self._projects_dir = projects_dir
        self._cache: dict[str, str] = {}
        self._mtime: float = 0.0
        # Per-session transcript mtime tracking for custom titles
        self._title_cache: dict[str, str] = {}
        self._title_mtimes: dict[str, float] = {}  # session_id -> mtime

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

    def _resolve_custom_title(self, session_id: str) -> str | None:
        """Check session transcript for a ``/rename`` custom title.

        Scans ``~/.claude/projects/*/<session_id>.jsonl`` for
        ``{"type": "custom-title", "customTitle": "..."}`` entries.
        Uses mtime caching per session to avoid re-reading unchanged files.
        """
        if not self._projects_dir.is_dir():
            return None

        # Find the transcript file across all project directories
        matches = list(self._projects_dir.glob(f"*/{session_id}.jsonl"))
        if not matches:
            return None

        path = matches[0]
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return None

        # Return cached value if file hasn't changed
        if session_id in self._title_mtimes and self._title_mtimes[session_id] == mtime:
            return self._title_cache.get(session_id)

        self._title_mtimes[session_id] = mtime
        title = None
        try:
            with path.open() as fh:
                for line in fh:
                    line = line.strip()
                    if not line or "custom-title" not in line:
                        continue
                    try:
                        entry = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue
                    if entry.get("type") == "custom-title":
                        ct = entry.get("customTitle", "")
                        if ct:
                            title = ct[:_MAX_DISPLAY_LEN]
        except OSError:
            pass

        if title:
            self._title_cache[session_id] = title
        else:
            self._title_cache.pop(session_id, None)
        return title

    def resolve(self, session_id: str) -> str:
        """Return the display name for *session_id*, or ``""``."""
        # Custom title (from /rename) takes priority
        title = self._resolve_custom_title(session_id)
        if title:
            return title
        self._refresh()
        return self._cache.get(session_id, "")

    def resolve_many(self, session_ids: set[str]) -> dict[str, str]:
        """Return ``{session_id: display}`` for all known ids in *session_ids*."""
        self._refresh()
        result: dict[str, str] = {}
        for sid in session_ids:
            title = self._resolve_custom_title(sid)
            if title:
                result[sid] = title
            elif sid in self._cache:
                result[sid] = self._cache[sid]
        return result
