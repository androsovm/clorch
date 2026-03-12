"""Terminal backend protocol for multi-terminal support."""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class TerminalBackend(Protocol):
    """Interface for terminal-specific operations.

    Each backend implements tab discovery, activation, and control
    appropriate for its terminal emulator.
    """

    def get_tty_map(self) -> dict[str, str]:
        """Return ``{tty: tab_ref}`` for every terminal tab/session.

        The *tab_ref* format is backend-specific and opaque to callers —
        it is only passed back to ``activate_tab``.
        """
        ...

    def activate_tab(self, tab_ref: str) -> bool:
        """Activate the tab identified by *tab_ref* (from ``get_tty_map``).

        Returns ``True`` on success.
        """
        ...

    def activate_by_name(self, name: str) -> bool:
        """Find and activate a tab whose title contains *name*.

        Returns ``True`` on success.
        """
        ...

    def bring_to_front(self) -> None:
        """Activate the terminal application and bring it to the foreground."""
        ...

    def open_tab(self, command: str, *, title: str | None = None) -> bool:
        """Open a new tab and run *command* in it.

        If *title* is given, set the tab/session name.
        Returns ``True`` on success, ``False`` if the backend does not
        support programmatic tab creation.
        """
        ...

    def can_resolve_tabs(self) -> bool:
        """Return ``True`` if the backend can map PIDs to terminal tabs.

        Backends that return an empty ``get_tty_map()`` always should
        return ``False`` here — only tmux agents are reachable from
        such terminals.
        """
        ...

    def supports_control_mode(self) -> bool:
        """Return ``True`` if the terminal supports tmux CC (control) mode."""
        ...
