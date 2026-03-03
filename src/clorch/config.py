"""Paths and default configuration."""

from __future__ import annotations

import os
from pathlib import Path

# State directory — ephemeral, lives in /tmp
STATE_DIR = Path(os.environ.get("CLORCH_STATE_DIR", "/tmp/clorch/state"))

# Hook installation target
HOOKS_DATA_DIR = Path.home() / ".local" / "share" / "clorch" / "hooks"

# Claude Code settings
CLAUDE_SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
CLAUDE_HISTORY_PATH = Path.home() / ".claude" / "history.jsonl"

# tmux
TMUX_SESSION_NAME = os.environ.get("CLORCH_SESSION", "claude")
TMUX_ORCH_WINDOW = "orch"

# Auto-approve rules
RULES_PATH = Path.home() / ".config" / "clorch" / "rules.yaml"

# Polling
STATE_POLL_INTERVAL_MS = 500
USAGE_POLL_INTERVAL = 10.0
