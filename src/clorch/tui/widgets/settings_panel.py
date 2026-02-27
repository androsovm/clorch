"""Settings panel — toggle controls for TUI preferences."""
from __future__ import annotations

from textual.widgets import Static
from rich.text import Text

from clorch.constants import CYAN, GREEN, GREY, RED, DIM


class SettingsPanel(Static):
    """Compact settings panel with toggle controls."""

    DEFAULT_CSS = """
    SettingsPanel {
        height: auto;
        max-height: 6;
        padding: 0 1;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__("", **kwargs)
        self._sound_enabled = False
        self._yolo_enabled = False
        self._rules_count = 0

    @property
    def sound_enabled(self) -> bool:
        return self._sound_enabled

    @property
    def yolo_enabled(self) -> bool:
        return self._yolo_enabled

    def set_yolo(self, enabled: bool) -> None:
        """Set YOLO state and re-render."""
        self._yolo_enabled = enabled
        self._refresh_content()

    def set_rules_count(self, count: int) -> None:
        """Set the number of loaded rules and re-render."""
        self._rules_count = count
        self._refresh_content()

    def toggle_sound(self) -> bool:
        """Toggle sound and re-render. Returns new state."""
        self._sound_enabled = not self._sound_enabled
        self._refresh_content()
        return self._sound_enabled

    def on_mount(self) -> None:
        self._refresh_content()

    def _refresh_content(self) -> None:
        text = Text()

        # Line 1: Sound
        text.append("[s]", style=f"bold {CYAN}")
        text.append(" Sound ", style="white")
        if self._sound_enabled:
            text.append("ON", style=f"bold {GREEN}")
        else:
            text.append("OFF", style=f"dim {GREY}")

        # Line 2: YOLO — always red background (danger zone)
        text.append("\n")
        if self._yolo_enabled:
            text.append("[!] \u26a0 YOLO ARMED \u26a0 ", style=f"bold white on {RED}")
            if self._rules_count > 0:
                text.append(f" ({self._rules_count} deny rules)", style=f"dim {GREY}")
        else:
            text.append("[!] YOLO OFF ", style=f"bold {GREY} on {DIM}")
            if self._rules_count > 0:
                text.append(f" ({self._rules_count} rules)", style=f"dim {GREY}")

        self.update(text)
