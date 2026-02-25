# Clorch

> **Status: alpha** — works daily on the author's machine, API may change.

Mission control for [Claude Code](https://docs.anthropic.com/en/docs/claude-code) sessions.

![Clorch TUI](docs/clorch-screenshot.png)

You run 10-20 sessions in Claude Code. One asks for permission, two are idle, and you can't remember which window has the one that's stuck. You cycle through panes, lose focus, and waste minutes just *finding* the right session.

Clorch fixes this. One dashboard shows every agent's status. Permission request pops up — press `y` right from the dashboard. Need to jump to a session — press `→`. That's it.

## Features

- **Real-time tracking** — hooks push events, no terminal scraping or polling
- **Approve / deny** permissions without leaving the dashboard (`y` / `n` / `Y` for all)
- **Jump** to any agent's tmux window in one keystroke
- **Action queue** — pending permissions are listed with hotkeys, newest first
- **tmux status-bar widget** — agent counts at a glance
- **macOS notifications** and terminal bell when an agent needs attention

## Quick Start

```bash
# Prerequisites (macOS)
brew install jq tmux

# Prerequisites (Linux)
# apt install jq tmux

# Install Clorch
pip install git+https://github.com/androsovm/clorch.git

# Install hooks into Claude Code settings
clorch init

# Launch the dashboard
clorch
```

`clorch init` adds hooks to `~/.claude/settings.json` (backup is created automatically). From this point, every Claude Code session reports its state to Clorch.

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

| Key | Action |
|-----|--------|
| `j` / `k` | Move selection up / down |
| `→` | Jump to selected agent's session |
| `a`–`z` | Focus an action item |
| `y` / `n` | Approve / deny focused permission |
| `Y` | Approve **all** pending permissions |
| `?` | Help overlay |

## How It Works

```
Claude Code hooks
  → event_handler.sh / notify_handler.sh
    → /tmp/clorch/state/<session_id>.json
      → Dashboard reads state every 500 ms
      → macOS notification + bell on attention events
```

Clorch hooks into [Claude Code's hook system](https://docs.anthropic.com/en/docs/claude-code/hooks). Each Claude Code session triggers shell scripts that write a JSON state file. The TUI reads those files on a timer. No terminal scraping, no ptrace, no API — just files on disk.

## Safety

Clorch does not read, modify, or access your project files. Here's what it touches:

- **`~/.claude/settings.json`** — `clorch init` adds hook entries (a timestamped backup is created before any changes)
- **`/tmp/clorch/state/`** — per-session JSON files with agent status, updated by hook scripts
- **No network** — all communication is local, through files on disk
- **`clorch uninstall`** — cleanly removes all hooks from settings

## Requirements

- Python 3.10+
- `jq` — used by hook scripts to parse JSON
- `tmux` — agent sessions run in tmux windows

## Platform Support

| Feature | macOS + iTerm2 | macOS + Terminal | Linux |
|---------|:-:|:-:|:-:|
| Dashboard & approve/deny | yes | yes | yes |
| Jump to agent (tmux) | yes | yes | yes |
| Jump to agent (iTerm tab) | yes | — | — |
| Native notifications | yes | yes | — |
| Terminal bell | yes | yes | yes |
| tmux status-bar widget | yes | yes | yes |

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `CLORCH_STATE_DIR` | `/tmp/clorch/state` | Directory for agent state files |
| `CLORCH_SESSION` | `claude` | tmux session name |

## Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[rich]'
pytest
```

## Contributing

Issues and PRs are welcome. Keep changes small, add tests for new logic, and keep the CLI output stable.

## License

[MIT](LICENSE)
