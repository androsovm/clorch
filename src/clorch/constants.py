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


class SubAgentStatus(str, Enum):
    """Possible states of a sub-agent."""

    RUNNING = "running"
    COMPLETED = "completed"


# Display mapping: symbol, label, hex color
STATUS_DISPLAY: dict[AgentStatus, tuple[str, str, str]] = {
    AgentStatus.WORKING:            (">>>", "WORK", "#A3BE8C"),
    AgentStatus.IDLE:               ("---", "IDLE", "#616E88"),
    AgentStatus.WAITING_PERMISSION: ("[!]", "PERM", "#BF616A"),
    AgentStatus.WAITING_ANSWER:     ("[?]", "WAIT", "#EBCB8B"),
    AgentStatus.ERROR:              ("[X]", "ERR",  "#B48EAD"),
}

# Statuses that need user attention (used by "jump to next red")
ATTENTION_STATUSES = frozenset({
    AgentStatus.WAITING_PERMISSION,
    AgentStatus.WAITING_ANSWER,
    AgentStatus.ERROR,
})

# Nord Aurora theme palette
THEME = {
    "bg":      "#2E3440",
    "green":   "#A3BE8C",
    "cyan":    "#88C0D0",
    "pink":    "#B48EAD",
    "red":     "#BF616A",
    "yellow":  "#EBCB8B",
    "grey":    "#616E88",
    "fg":      "#D8DEE9",
    "dim":     "#4C566A",
    "border":  "#3B4252",
    "accent":  "#434C5E",
    "bright":  "#ECEFF4",
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

# Extended sparkline width for telemetry panel
TELEMETRY_HISTORY_LEN = 30

# How many poll ticks (0.5s each) to accumulate before pushing a sparkline point
# 10 ticks × 0.5s = 5s per bucket → 30 slots × 5s = 2.5 min visible history
TELEMETRY_BUCKET_TICKS = 10

# Sparkline characters (8 levels)
SPARKLINE_CHARS = "▁▂▃▄▅▆▇█"

# Braille spinner frames for WORKING status animation
BRAILLE_SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

# Global animation tick interval (seconds)
ANIM_INTERVAL = 0.25

# Context window capacity (tokens) for Claude models.
# Default for unknown models; use model_context_capacity() for model-aware lookup.
CONTEXT_WINDOW_CAPACITY = 200_000

# Known model prefix → context window size (tokens).
_MODEL_CAPACITY: dict[str, int] = {
    "claude-opus-4": 1_000_000,
    "claude-sonnet-4": 200_000,
    "claude-haiku-4": 200_000,
    "claude-3-5-sonnet": 200_000,
    "claude-3-5-haiku": 200_000,
    "claude-3-opus": 200_000,
}


def model_context_capacity(model: str) -> int:
    """Return context window capacity for a model string.

    Matches against known prefixes, falling back to CONTEXT_WINDOW_CAPACITY.
    """
    if model:
        for prefix, capacity in _MODEL_CAPACITY.items():
            if model.startswith(prefix):
                return capacity
    return CONTEXT_WINDOW_CAPACITY


def context_pct_color(pct: float) -> str:
    """Return color hex for a context window percentage."""
    if pct >= 80:
        return RED
    if pct >= 60:
        return YELLOW
    return GREEN
