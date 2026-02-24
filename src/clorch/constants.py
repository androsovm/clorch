"""Colors, status definitions, and UI constants."""

from __future__ import annotations

from enum import Enum


class AgentStatus(str, Enum):
    """Possible states of a Claude Code agent."""

    WORKING = "WORKING"
    IDLE = "IDLE"
    WAITING_PERMISSION = "WAITING_PERMISSION"
    WAITING_ANSWER = "WAITING_ANSWER"
    ERROR = "ERROR"


# Display mapping: symbol, label, hex color
STATUS_DISPLAY: dict[AgentStatus, tuple[str, str, str]] = {
    AgentStatus.WORKING:            (">>>", "WORK", "#00FF88"),
    AgentStatus.IDLE:               ("---", "IDLE", "#555555"),
    AgentStatus.WAITING_PERMISSION: ("[!]", "PERM", "#FF0040"),
    AgentStatus.WAITING_ANSWER:     ("[?]", "ASK",  "#FFB800"),
    AgentStatus.ERROR:              ("[X]", "ERR",  "#FF0080"),
}

# Statuses that need user attention (used by "jump to next red")
ATTENTION_STATUSES = frozenset({
    AgentStatus.WAITING_PERMISSION,
    AgentStatus.WAITING_ANSWER,
    AgentStatus.ERROR,
})

# Cyberpunk theme palette
THEME = {
    "bg":      "#0A0E1A",
    "green":   "#00FF88",
    "cyan":    "#00BFFF",
    "pink":    "#FF0080",
    "red":     "#FF0040",
    "yellow":  "#FFB800",
    "grey":    "#555555",
    "fg":      "#C0C0C0",
    "bright":  "#FFFFFF",
}

# Convenience aliases — single source of truth for TUI and tmux colours.
GREEN  = THEME["green"]
CYAN   = THEME["cyan"]
PINK   = THEME["pink"]
RED    = THEME["red"]
YELLOW = THEME["yellow"]
GREY   = THEME["grey"]

# Activity history length (sparkline points)
ACTIVITY_HISTORY_LEN = 10

# Sparkline characters (8 levels)
SPARKLINE_CHARS = "▁▂▃▄▅▆▇█"
