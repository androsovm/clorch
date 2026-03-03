"""CLI argument parser and command dispatch for clorch."""

from __future__ import annotations

import argparse
import sys


# ------------------------------------------------------------------
# Command handlers
# ------------------------------------------------------------------

def _cmd_dash(args: argparse.Namespace) -> None:
    """Launch the Textual TUI dashboard."""
    from clorch.hooks.installer import ensure_hooks_synced
    from clorch.tui.app import run_dashboard

    ensure_hooks_synced()
    run_dashboard()


def _cmd_status(args: argparse.Namespace) -> None:
    """Print a one-line status summary to stdout."""
    from clorch.state.manager import StateManager
    from clorch.state.models import StatusSummary

    manager = StateManager()
    agents = manager.scan()
    summary = StatusSummary.from_agents(agents)

    try:
        from rich.console import Console

        console = Console(highlight=False)
        line = summary.status_line()
        total = summary.total
        console.print(f"{line}  | total:{total}")
    except ImportError:
        line = summary.status_line()
        print(f"{line}  | total:{summary.total}")


def _cmd_list(args: argparse.Namespace) -> None:
    """List agents with status in a compact table."""
    from clorch.constants import STATUS_DISPLAY
    from clorch.state.manager import StateManager

    manager = StateManager()
    agents = manager.scan()

    if not agents:
        print("No active agents.")
        return

    try:
        from rich.console import Console
        from rich.table import Table

        console = Console(highlight=False)
        table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
        table.add_column("#", justify="right", style="dim", width=3)
        table.add_column("PROJECT", min_width=12)
        table.add_column("SESSION", min_width=16, style="dim italic")
        table.add_column("STATUS", min_width=12)
        table.add_column("TOOL", min_width=6)
        table.add_column("UPTIME", justify="right", min_width=8)

        for idx, agent in enumerate(agents, start=1):
            symbol, label, color = STATUS_DISPLAY.get(
                agent.status,
                ("?", "???", "#888888"),
            )
            status_str = f"[{color}]{symbol} {label}[/{color}]"
            tool_str = agent.last_tool or "-"
            session = (agent.session_name or "")[:40]
            table.add_row(
                str(idx),
                agent.project_name or agent.session_id[:12],
                session,
                status_str,
                tool_str,
                agent.uptime,
            )

        console.print(table)

    except ImportError:
        header = (
            f" {'#':>3}  {'PROJECT':<14} {'SESSION':<18}"
            f" {'STATUS':<12} {'TOOL':<8} {'UPTIME':>8}"
        )
        print(header)
        for idx, agent in enumerate(agents, start=1):
            symbol, label, _color = STATUS_DISPLAY.get(
                agent.status,
                ("?", "???", "#888888"),
            )
            status_str = f"{symbol} {label}"
            tool_str = agent.last_tool or "-"
            name = agent.project_name or agent.session_id[:12]
            session = (agent.session_name or "")[:18]
            print(
                f" {idx:>3}  {name:<14} {session:<18}"
                f" {status_str:<12} {tool_str:<8} {agent.uptime:>8}"
            )


def _cmd_init(args: argparse.Namespace) -> None:
    """Install Clorch hooks into Claude Code settings."""
    from clorch.hooks.installer import install_hooks

    install_hooks(dry_run=args.dry_run)


def _cmd_uninstall(args: argparse.Namespace) -> None:
    """Remove Clorch hooks from settings."""
    from clorch.hooks.installer import uninstall_hooks

    uninstall_hooks()


def _cmd_tmux_widget(args: argparse.Namespace) -> None:
    """Output tmux status-right formatted string."""
    from clorch.tmux.statusbar import render_status_widget

    print(render_status_widget())


# ------------------------------------------------------------------
# Main entry point
# ------------------------------------------------------------------

def main() -> None:
    from clorch import __version__

    parser = argparse.ArgumentParser(
        prog="clorch",
        description="Orchestrator dashboard for multiple Claude Code sessions",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    # init
    p_init = subparsers.add_parser("init", help="Install hooks into Claude Code settings")
    p_init.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Print what would change without writing",
    )
    p_init.set_defaults(func=_cmd_init)

    # uninstall
    p_uninstall = subparsers.add_parser("uninstall", help="Remove hooks from settings")
    p_uninstall.set_defaults(func=_cmd_uninstall)

    # status (quick one-liner for scripts/tmux)
    p_status = subparsers.add_parser("status", help="Print one-line status summary")
    p_status.set_defaults(func=_cmd_status)

    # list (table for terminal)
    p_list = subparsers.add_parser("list", help="List agents with status table")
    p_list.set_defaults(func=_cmd_list)

    # tmux-widget (for tmux status-right)
    p_widget = subparsers.add_parser(
        "tmux-widget",
        help="Output for tmux status-right (called by tmux)",
    )
    p_widget.set_defaults(func=_cmd_tmux_widget)

    args = parser.parse_args()

    # Default: no subcommand → launch dashboard
    if args.command is None:
        _cmd_dash(args)
    else:
        args.func(args)
