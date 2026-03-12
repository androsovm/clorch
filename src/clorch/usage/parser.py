"""JSONL session log parser with incremental tailing."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from clorch.usage.models import SessionUsage, TokenUsage

CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"


def parse_session_usage(
    path: Path,
    since: datetime | None = None,
    byte_offset: int = 0,
) -> tuple[SessionUsage | None, int]:
    """Parse a JSONL session file and extract token usage from assistant messages.

    Returns (SessionUsage or None if no data, new byte offset for next call).
    Starts reading from *byte_offset* for incremental polling.
    """
    try:
        file_size = path.stat().st_size
    except OSError:
        return None, byte_offset

    if file_size <= byte_offset:
        return None, byte_offset

    tokens = TokenUsage()
    model = ""
    message_count = 0
    session_id = path.stem

    try:
        with open(path, "r", errors="replace") as f:
            if byte_offset > 0:
                f.seek(byte_offset)
            for line in f:
                # Fast pre-filter: skip lines without assistant marker
                if '"assistant"' not in line:
                    continue
                try:
                    entry = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue

                # Navigate to message
                msg = entry.get("message")
                if not isinstance(msg, dict):
                    continue
                if msg.get("role") != "assistant":
                    continue

                # Timestamp filter
                if since is not None:
                    ts_str = entry.get("timestamp")
                    if ts_str:
                        try:
                            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                            if ts < since:
                                continue
                        except (ValueError, TypeError):
                            pass

                # Extract usage
                usage = msg.get("usage")
                if not isinstance(usage, dict):
                    continue

                msg_input = usage.get("input_tokens", 0)
                msg_cache_create = usage.get("cache_creation_input_tokens", 0)
                msg_cache_read = usage.get("cache_read_input_tokens", 0)
                tokens.input_tokens += msg_input
                tokens.output_tokens += usage.get("output_tokens", 0)
                tokens.cache_creation_input_tokens += msg_cache_create
                tokens.cache_read_input_tokens += msg_cache_read
                tokens.last_input = msg_input + msg_cache_create + msg_cache_read
                message_count += 1

                # Track model (use latest)
                msg_model = msg.get("model", "")
                if msg_model:
                    model = msg_model

            new_offset = f.tell()
    except OSError:
        return None, byte_offset

    if message_count == 0:
        return None, new_offset

    return SessionUsage(
        session_id=session_id,
        model=model,
        tokens=tokens,
        message_count=message_count,
    ), new_offset


def iter_today_jsonl_files() -> list[Path]:
    """Find all JSONL files modified today under ~/.claude/projects/."""
    if not CLAUDE_PROJECTS_DIR.is_dir():
        return []

    today_local = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_ts = today_local.timestamp()

    results: list[Path] = []
    try:
        for project_dir in CLAUDE_PROJECTS_DIR.iterdir():
            if not project_dir.is_dir():
                continue
            for jsonl_file in project_dir.glob("*.jsonl"):
                try:
                    if jsonl_file.stat().st_mtime >= today_ts:
                        results.append(jsonl_file)
                except OSError:
                    continue
    except OSError:
        pass

    return results
