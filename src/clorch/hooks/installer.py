"""Hook installer that merges Clorch hooks into ~/.claude/settings.json."""

from __future__ import annotations

import json
import logging
import shutil
import stat
import time
from pathlib import Path

from clorch.config import CLAUDE_SETTINGS_PATH, HOOKS_DATA_DIR

log = logging.getLogger(__name__)

# Marker substring used to identify hooks that belong to clorch.
_ORCH_MARKER = "clorch/hooks/"

# All event types that Claude Code supports.
_HOOK_EVENTS = (
    "SessionStart",
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "Stop",
    "SessionEnd",
    "Notification",
    "PermissionRequest",
    "UserPromptSubmit",
    "SubagentStart",
    "SubagentStop",
    "PreCompact",
    "TeammateIdle",
    "TaskCompleted",
)


def _orch_hook_definitions() -> dict[str, list[dict]]:
    """Return the full hooks structure that clorch needs in settings.json."""
    hooks: dict[str, list[dict]] = {}
    for event in _HOOK_EVENTS:
        if event == "Notification":
            command = f"{HOOKS_DATA_DIR}/notify_handler.sh"
        else:
            command = (
                f"CLORCH_EVENT={event} {HOOKS_DATA_DIR}/event_handler.sh"
            )
        hooks[event] = [
            {
                "matcher": "",
                "hooks": [
                    {
                        "type": "command",
                        "command": command,
                        "async": True,
                    }
                ],
            }
        ]
    return hooks


# ------------------------------------------------------------------
# Hook script copying
# ------------------------------------------------------------------

def _hook_scripts_source_dir() -> Path:
    """Locate the directory containing the bundled hook shell scripts.

    They live alongside this module in the ``hooks`` package directory.
    """
    return Path(__file__).resolve().parent


def _copy_hook_scripts() -> None:
    """Copy hook scripts to ~/.local/share/clorch/hooks/ and chmod +x."""
    HOOKS_DATA_DIR.mkdir(parents=True, exist_ok=True)

    source_dir = _hook_scripts_source_dir()
    for script_name in ("event_handler.sh", "notify_handler.sh"):
        src = source_dir / script_name
        dst = HOOKS_DATA_DIR / script_name
        if not src.is_file():
            log.warning("Source hook script not found: %s", src)
            continue
        shutil.copy2(src, dst)
        # Ensure the script is executable (owner rwx, group rx, other rx).
        dst.chmod(dst.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        log.info("Installed %s -> %s", src, dst)


def ensure_hooks_synced() -> None:
    """Silently sync hook scripts if they are outdated or missing.

    Called on TUI startup so that ``pip install --upgrade`` automatically
    picks up new hook scripts without requiring ``clorch init``.
    Only copies when the installed script differs from the bundled one.
    """
    source_dir = _hook_scripts_source_dir()
    for script_name in ("event_handler.sh", "notify_handler.sh"):
        src = source_dir / script_name
        dst = HOOKS_DATA_DIR / script_name
        if not src.is_file():
            continue
        if dst.is_file() and dst.stat().st_mtime >= src.stat().st_mtime:
            # Same or newer modification time — skip
            if dst.read_bytes() == src.read_bytes():
                continue
        HOOKS_DATA_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        dst.chmod(dst.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        log.info("Auto-synced %s -> %s", src, dst)


# ------------------------------------------------------------------
# Merge logic
# ------------------------------------------------------------------

def _is_orch_hook(hook_entry: dict) -> bool:
    """Check if a hook entry belongs to clorch (by checking command path)."""
    for h in hook_entry.get("hooks", []):
        cmd = h.get("command", "")
        if _ORCH_MARKER in cmd:
            return True
    return False


def _merge_hooks(existing: dict, orch_hooks: dict) -> dict:
    """Merge orch hooks into existing settings without destroying user hooks.

    For each event key in *orch_hooks*:
    - If the event key does not exist in the existing ``"hooks"`` dict, add it.
    - If it exists, scan the list of rule objects.  If one already contains a
      clorch hook, replace it in-place with the new definition.  Otherwise,
      append the new rule object to the list.

    Returns the full settings dict (mutated in place for convenience).
    """
    if "hooks" not in existing:
        existing["hooks"] = {}

    existing_hooks = existing["hooks"]

    for event, orch_rules in orch_hooks.items():
        if event not in existing_hooks:
            # Event type not present at all -- add the whole list.
            existing_hooks[event] = orch_rules
            continue

        event_list: list[dict] = existing_hooks[event]

        # Find index of existing orch rule, if any.
        orch_idx: int | None = None
        for idx, rule in enumerate(event_list):
            if _is_orch_hook(rule):
                orch_idx = idx
                break

        if orch_idx is not None:
            # Replace existing orch entry in-place.
            event_list[orch_idx] = orch_rules[0]
        else:
            # Append our rule to the existing list.
            event_list.append(orch_rules[0])

    return existing


# ------------------------------------------------------------------
# Install / uninstall
# ------------------------------------------------------------------

def install_hooks(dry_run: bool = False) -> None:
    """Install Clorch hooks into Claude Code settings.

    Steps:
    1. Read existing ``~/.claude/settings.json`` (or start with ``{}``).
    2. Back up the current file as ``settings.json.bak.<timestamp>``.
    3. Merge orch hooks into the ``"hooks"`` key, preserving user hooks.
    4. Write the updated settings back.
    5. Copy hook shell scripts to ``~/.local/share/clorch/hooks/``.

    If *dry_run* is ``True``, only print what would change without writing.
    """
    if not shutil.which("jq"):
        print("Error: 'jq' is required but not found on PATH.")
        print("Install it with: brew install jq")
        return
    # Load existing settings.
    settings_path = CLAUDE_SETTINGS_PATH
    if settings_path.is_file():
        existing = json.loads(settings_path.read_text(encoding="utf-8"))
    else:
        existing = {}

    orch_hooks = _orch_hook_definitions()
    merged = _merge_hooks(existing, orch_hooks)

    if dry_run:
        print("[dry-run] Would write to:", settings_path)
        print(json.dumps(merged, indent=2))
        print()
        print("[dry-run] Would copy hook scripts to:", HOOKS_DATA_DIR)
        return

    # Back up current settings.
    if settings_path.is_file():
        timestamp = int(time.time())
        backup_path = settings_path.with_name(f"settings.json.bak.{timestamp}")
        shutil.copy2(settings_path, backup_path)
        log.info("Backed up settings to %s", backup_path)
        print(f"Backup: {backup_path}")

    # Write merged settings.
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(merged, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Updated: {settings_path}")

    # Copy scripts.
    _copy_hook_scripts()
    print(f"Hook scripts installed to: {HOOKS_DATA_DIR}")
    print("Done.")


def uninstall_hooks() -> None:
    """Remove Clorch hooks from settings, restore backup if available.

    - Removes all hook rule objects identified as orch hooks from each event
      list in the ``"hooks"`` dict.
    - If an event list becomes empty after removal, deletes the event key.
    - If the entire ``"hooks"`` dict becomes empty, deletes it.
    """
    settings_path = CLAUDE_SETTINGS_PATH
    if not settings_path.is_file():
        print("No settings file found at", settings_path)
        return

    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    hooks = settings.get("hooks")
    if not hooks:
        print("No hooks found in settings.")
        return

    changed = False
    events_to_delete: list[str] = []

    for event, rule_list in hooks.items():
        original_len = len(rule_list)
        rule_list[:] = [r for r in rule_list if not _is_orch_hook(r)]
        if len(rule_list) != original_len:
            changed = True
        if not rule_list:
            events_to_delete.append(event)

    for event in events_to_delete:
        del hooks[event]

    if not hooks:
        del settings["hooks"]

    if changed:
        # Back up before modifying.
        timestamp = int(time.time())
        backup_path = settings_path.with_name(f"settings.json.bak.{timestamp}")
        shutil.copy2(settings_path, backup_path)
        print(f"Backup: {backup_path}")

        settings_path.write_text(
            json.dumps(settings, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Removed clorch hooks from {settings_path}")
    else:
        print("No clorch hooks found to remove.")

    # Optionally clean up installed scripts.
    if HOOKS_DATA_DIR.is_dir():
        for script in ("event_handler.sh", "notify_handler.sh"):
            script_path = HOOKS_DATA_DIR / script
            if script_path.is_file():
                script_path.unlink()
                log.info("Removed %s", script_path)
        # Remove the directory if empty.
        try:
            HOOKS_DATA_DIR.rmdir()
        except OSError:
            pass  # Directory not empty or other scripts present -- leave it.

    print("Done.")
