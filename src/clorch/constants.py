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
    AgentStatus.WORKING:            (">>>", "WORK", "#5AE0A0"),
    AgentStatus.IDLE:               ("---", "IDLE", "#666666"),
    AgentStatus.WAITING_PERMISSION: ("[!]", "PERM", "#E05070"),
    AgentStatus.WAITING_ANSWER:     ("[?]", "WAIT", "#D4A850"),
    AgentStatus.ERROR:              ("[X]", "ERR",  "#D060A0"),
}

# Statuses that need user attention (used by "jump to next red")
ATTENTION_STATUSES = frozenset({
    AgentStatus.WAITING_PERMISSION,
    AgentStatus.WAITING_ANSWER,
    AgentStatus.ERROR,
})

# Muted cyberpunk theme palette
THEME = {
    "bg":      "#0C1018",
    "green":   "#5AE0A0",
    "cyan":    "#5EAFD0",
    "pink":    "#D060A0",
    "red":     "#E05070",
    "yellow":  "#D4A850",
    "grey":    "#666666",
    "fg":      "#C8CCD0",
    "dim":     "#4A5060",
    "border":  "#2A3040",
    "accent":  "#3A4A60",
    "bright":  "#FFFFFF",
}

# Convenience aliases — single source of truth for TUI and tmux colours.
GREEN  = THEME["green"]
CYAN   = THEME["cyan"]
PINK   = THEME["pink"]
RED    = THEME["red"]
YELLOW = THEME["yellow"]
GREY   = THEME["grey"]
DIM    = THEME["dim"]
BORDER = THEME["border"]
ACCENT = THEME["accent"]

# Activity history length (sparkline points)
ACTIVITY_HISTORY_LEN = 10

# Sparkline characters (8 levels)
SPARKLINE_CHARS = "▁▂▃▄▅▆▇█"

# Braille spinner frames for WORKING status animation
BRAILLE_SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

# Global animation tick interval (seconds)
ANIM_INTERVAL = 0.25
