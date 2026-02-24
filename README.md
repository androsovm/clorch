# Clorch

Orchestrator dashboard for multiple Claude Code sessions.

Clorch listens to [Claude Code hooks](https://docs.anthropic.com/en/docs/claude-code/hooks), keeps a live view of every active agent, and lets you approve permissions or jump to the right session — all from one place. It is event-driven (no terminal scraping) and pairs naturally with tmux.

## Why

When you run several Claude Code sessions at once, context switching kills productivity. Clorch gives you a single control plane: who is working, who needs attention, and where to jump next.

## Features

- **Real-time tracking** via Claude Code hooks (push model, no polling of terminals)
- **TUI dashboard** with action queue, agent table, sparklines, and detail panel
- **Approve / deny** permission requests directly from the dashboard (`y` / `n`)
- **Jump** to any agent's tmux window or iTerm2 tab in one keystroke
- **tmux status-bar widget** for at-a-glance agent counts
- **macOS notifications** and terminal bell on attention events
- **Batch approve** all pending permissions with `Y`

## Quick Start

```bash
# Install (editable, from source)
pip install -e .

# Install hooks into ~/.claude/settings.json (requires jq)
clorch init

# Launch the dashboard
clorch
```

## CLI

```
clorch              Launch TUI dashboard (default)
clorch init         Install hooks into ~/.claude/settings.json
clorch init --dry-run   Preview changes without writing
clorch uninstall    Remove hooks from settings
clorch status       One-line summary for scripts
clorch list         Table view in terminal
clorch tmux-widget  Output for tmux status-right
clorch --version    Print version
```

## TUI Keybindings

### Navigation

| Key | Action |
|-----|--------|
| `j` / `k` | Move selection up / down |
| `1`–`0` | Jump to agent by row number |
| `Enter` / `Right` | Jump to selected agent's session |
| `d` | Toggle detail panel |
| `r` | Refresh |
| `?` | Help overlay |
| `q` | Quit |

### Action Queue

| Key | Action |
|-----|--------|
| `a`–`z` | Focus an action item |
| `y` / `n` | Approve / deny focused permission |
| `Y` | Approve **all** pending permissions |
| `Esc` | Cancel selection |

### tmux Helpers

| Key | Action |
|-----|--------|
| `N` | Create a new tmux window (prompts for name) |
| `R` | Open iTerm tab attached to selected agent |
| `S` / `V` | Split selected agent's window (horizontal / vertical) |
| `X` | Kill selected agent's tmux window |

## tmux Status Bar

Add to `~/.tmux.conf`:

```bash
set -g status-right '#(clorch tmux-widget)'
set -g status-interval 2
```

Optionally bind `prefix + !` to jump to the next agent needing attention:

```bash
bind-key ! run-shell "python -m clorch.tmux.navigator"
```

## How It Works

```
Claude Code hooks
  → event_handler.sh / notify_handler.sh
    → /tmp/clorch/state/<session_id>.json
      → Dashboard polls every 500 ms
      → macOS notification + bell on attention events
```

Hooks are installed into `~/.claude/settings.json` and call shell scripts that update per-session JSON state files. The TUI reads those files on a timer. A backup of your settings is created automatically on `init`.

## Requirements

- Python 3.10+
- `jq` — used by hook scripts to parse JSON
- `tmux` (optional) — enables jump, split, and status-bar features
- macOS (optional) — native notifications via `osascript`; other features work on Linux

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `CLORCH_STATE_DIR` | `/tmp/clorch/state` | Directory for agent state files |
| `CLORCH_SESSION` | `claude` | tmux session name |

## Project Structure

```
src/clorch/
├── cli.py                 # CLI entry point
├── config.py              # Paths and defaults
├── constants.py           # Colors, statuses, theme
├── hooks/
│   ├── installer.py       # Hook install/uninstall logic
│   ├── event_handler.sh   # Main hook script
│   └── notify_handler.sh  # Notification hook script
├── notifications/
│   ├── bell.py            # Terminal bell
│   └── macos.py           # macOS osascript notifications
├── state/
│   ├── manager.py         # Scan and query state files
│   ├── models.py          # AgentState, StatusSummary, ActionItem
│   └── watcher.py         # Background polling thread
├── tmux/
│   ├── session.py         # TmuxSession class
│   ├── navigator.py       # Jump-to-agent logic
│   └── statusbar.py       # tmux status-right renderer
└── tui/
    ├── app.py             # Main Textual app
    ├── app.tcss            # Stylesheet
    └── widgets/           # StatusBar, AgentTable, ActionQueue, etc.
```

## Development

```bash
# Create venv and install in editable mode
python -m venv .venv
source .venv/bin/activate
pip install -e '.[rich]'

# Run tests
pytest
```

## Contributing

Issues and PRs are welcome. Keep changes small, add tests for new logic, and keep the CLI output stable.

## License

[MIT](LICENSE)
