"""Tests for the hook installer."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from clorch.hooks.installer import (
    _HOOK_EVENTS,
    _is_orch_hook,
    _merge_hooks,
    _orch_hook_definitions,
    install_hooks,
    uninstall_hooks,
)


# ------------------------------------------------------------------
# _merge_hooks()
# ------------------------------------------------------------------


class TestMergeHooks:
    """Tests for the _merge_hooks helper."""

    def test_merge_hooks_empty_settings(self):
        """Merging into empty settings creates the hooks section."""
        existing: dict = {}
        orch_hooks = _orch_hook_definitions()

        result = _merge_hooks(existing, orch_hooks)

        assert "hooks" in result
        # Every orch event type should be present.
        for event in orch_hooks:
            assert event in result["hooks"]
            rules = result["hooks"][event]
            assert len(rules) == 1
            # The command should contain the orch marker.
            assert any(
                "clorch/hooks/" in h.get("command", "")
                for h in rules[0]["hooks"]
            )

    def test_merge_hooks_existing_hooks(self):
        """Existing user hooks are preserved after merging orch hooks."""
        user_hook_rule = {
            "matcher": "*.py",
            "hooks": [
                {
                    "type": "command",
                    "command": "my-custom-linter --check",
                    "async": False,
                }
            ],
        }
        existing = {
            "hooks": {
                "PreToolUse": [user_hook_rule],
            },
        }
        orch_hooks = _orch_hook_definitions()

        result = _merge_hooks(existing, orch_hooks)

        # The user hook should still be in PreToolUse.
        pre_tool_rules = result["hooks"]["PreToolUse"]
        assert len(pre_tool_rules) == 2  # user + orch
        # First entry is the user hook (order preserved).
        assert pre_tool_rules[0] == user_hook_rule
        # Second entry is the orch hook.
        assert any(
            "clorch/hooks/" in h.get("command", "")
            for h in pre_tool_rules[1]["hooks"]
        )

    def test_merge_hooks_update_existing_orch(self):
        """Existing orch hooks are replaced in-place, not duplicated."""
        # Simulate an already-installed orch hook with an old command.
        old_orch_rule = {
            "matcher": "",
            "hooks": [
                {
                    "type": "command",
                    "command": "OLD_VERSION clorch/hooks/event_handler.sh",
                    "async": True,
                }
            ],
        }
        existing = {
            "hooks": {
                "PostToolUse": [old_orch_rule],
            },
        }
        orch_hooks = _orch_hook_definitions()

        result = _merge_hooks(existing, orch_hooks)

        # PostToolUse should have exactly 1 rule (the updated orch one),
        # not 2 (old + new).
        post_rules = result["hooks"]["PostToolUse"]
        assert len(post_rules) == 1
        # The command should be the new one, not the old one.
        cmd = post_rules[0]["hooks"][0]["command"]
        assert "OLD_VERSION" not in cmd
        assert "clorch/hooks/" in cmd


# ------------------------------------------------------------------
# _is_orch_hook()
# ------------------------------------------------------------------


class TestIsOrchHook:
    """Tests for the _is_orch_hook helper."""

    def test_is_orch_hook_true(self):
        """A hook entry with 'clorch/hooks/' in command is detected."""
        rule = {
            "matcher": "",
            "hooks": [
                {
                    "type": "command",
                    "command": "CLORCH_EVENT=Stop /home/user/.local/share/clorch/hooks/event_handler.sh",
                    "async": True,
                }
            ],
        }
        assert _is_orch_hook(rule) is True

    def test_is_orch_hook_false(self):
        """A hook entry without the orch marker is not detected."""
        rule = {
            "matcher": "*.py",
            "hooks": [
                {
                    "type": "command",
                    "command": "black --check .",
                    "async": False,
                }
            ],
        }
        assert _is_orch_hook(rule) is False

    def test_is_orch_hook_empty(self):
        """An empty hooks list is not detected as orch."""
        rule = {"matcher": "", "hooks": []}
        assert _is_orch_hook(rule) is False


# ------------------------------------------------------------------
# install_hooks()
# ------------------------------------------------------------------


class TestInstallHooks:
    """Tests for install_hooks()."""

    def test_install_hooks_creates_backup(self, tmp_path, monkeypatch):
        """A backup file is created when settings already exist."""
        settings_path = tmp_path / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True)
        original_settings = {"some_key": "some_value"}
        settings_path.write_text(json.dumps(original_settings))

        hooks_data_dir = tmp_path / "hooks-data"

        monkeypatch.setattr(
            "clorch.hooks.installer.CLAUDE_SETTINGS_PATH", settings_path
        )
        monkeypatch.setattr(
            "clorch.hooks.installer.HOOKS_DATA_DIR", hooks_data_dir
        )
        # Prevent _copy_hook_scripts from failing on missing source scripts.
        monkeypatch.setattr(
            "clorch.hooks.installer._copy_hook_scripts", lambda: None
        )

        install_hooks(dry_run=False)

        # A backup file should have been created.
        backups = list(settings_path.parent.glob("settings.json.bak.*"))
        assert len(backups) == 1

        # The backup should contain the original content.
        backup_content = json.loads(backups[0].read_text())
        assert backup_content == original_settings

        # The settings file should now contain orch hooks.
        updated = json.loads(settings_path.read_text())
        assert "hooks" in updated
        # Original key is preserved.
        assert updated["some_key"] == "some_value"


# ------------------------------------------------------------------
# uninstall_hooks()
# ------------------------------------------------------------------


class TestUninstallHooks:
    """Tests for uninstall_hooks()."""

    def test_uninstall_hooks_removes_orch(self, tmp_path, monkeypatch):
        """Only orch hooks are removed; user hooks and other keys are preserved."""
        settings_path = tmp_path / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True)
        hooks_data_dir = tmp_path / "hooks-data"
        hooks_data_dir.mkdir(parents=True)

        user_hook_rule = {
            "matcher": "*.py",
            "hooks": [
                {
                    "type": "command",
                    "command": "my-custom-linter --check",
                    "async": False,
                }
            ],
        }
        orch_hook_rule = {
            "matcher": "",
            "hooks": [
                {
                    "type": "command",
                    "command": "CLORCH_EVENT=PostToolUse /home/user/.local/share/clorch/hooks/event_handler.sh",
                    "async": True,
                }
            ],
        }
        settings = {
            "other_key": True,
            "hooks": {
                "PostToolUse": [user_hook_rule, orch_hook_rule],
                # SessionStart only has the orch hook — should be removed entirely.
                "SessionStart": [
                    {
                        "matcher": "",
                        "hooks": [
                            {
                                "type": "command",
                                "command": "CLORCH_EVENT=SessionStart /home/user/.local/share/clorch/hooks/event_handler.sh",
                                "async": True,
                            }
                        ],
                    }
                ],
            },
        }
        settings_path.write_text(json.dumps(settings))

        monkeypatch.setattr(
            "clorch.hooks.installer.CLAUDE_SETTINGS_PATH", settings_path
        )
        monkeypatch.setattr(
            "clorch.hooks.installer.HOOKS_DATA_DIR", hooks_data_dir
        )

        uninstall_hooks()

        updated = json.loads(settings_path.read_text())

        # The other_key should remain.
        assert updated["other_key"] is True

        # PostToolUse should only have the user hook left.
        assert "hooks" in updated
        assert "PostToolUse" in updated["hooks"]
        post_rules = updated["hooks"]["PostToolUse"]
        assert len(post_rules) == 1
        assert post_rules[0] == user_hook_rule

        # SessionStart was only orch hooks, so the event key should be gone.
        assert "SessionStart" not in updated["hooks"]


# ------------------------------------------------------------------
# _HOOK_EVENTS and routing
# ------------------------------------------------------------------


class TestHookEvents:
    """Tests for the complete set of hook events and their routing."""

    def test_all_14_events_present(self):
        """All 14 hook events are registered."""
        assert len(_HOOK_EVENTS) == 14
        expected = {
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
        }
        assert set(_HOOK_EVENTS) == expected

    def test_notification_routes_to_notify_handler(self):
        """Notification event uses notify_handler.sh, not event_handler.sh."""
        hooks = _orch_hook_definitions()
        cmd = hooks["Notification"][0]["hooks"][0]["command"]
        assert "notify_handler.sh" in cmd
        assert "event_handler.sh" not in cmd

    def test_non_notification_events_route_to_event_handler(self):
        """All non-Notification events route through event_handler.sh with CLORCH_EVENT."""
        hooks = _orch_hook_definitions()
        for event in _HOOK_EVENTS:
            if event == "Notification":
                continue
            cmd = hooks[event][0]["hooks"][0]["command"]
            assert "event_handler.sh" in cmd, f"{event} should use event_handler.sh"
            assert f"CLORCH_EVENT={event}" in cmd, f"{event} should set CLORCH_EVENT"

    def test_all_hooks_are_async(self):
        """Every orch hook is configured as async."""
        hooks = _orch_hook_definitions()
        for event, rules in hooks.items():
            assert rules[0]["hooks"][0]["async"] is True, f"{event} hook should be async"

    def test_orch_hook_definitions_returns_all_events(self):
        """_orch_hook_definitions() produces a key for every event."""
        hooks = _orch_hook_definitions()
        assert set(hooks.keys()) == set(_HOOK_EVENTS)
