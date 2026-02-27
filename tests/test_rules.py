"""Tests for YOLO mode & auto-approve rules engine."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from clorch.rules import Rule, RulesConfig, load_rules, evaluate


# ------------------------------------------------------------------
# load_rules
# ------------------------------------------------------------------


class TestLoadRules:
    """Loading rules from YAML files."""

    def test_missing_file_returns_defaults(self, tmp_path: Path) -> None:
        config = load_rules(tmp_path / "nonexistent.yaml")
        assert config.yolo is False
        assert config.rules == []
        assert config.default == "ask"

    def test_empty_file_returns_defaults(self, tmp_path: Path) -> None:
        p = tmp_path / "rules.yaml"
        p.write_text("")
        config = load_rules(p)
        assert config.yolo is False
        assert config.rules == []
        assert config.default == "ask"

    def test_invalid_yaml_returns_defaults(self, tmp_path: Path) -> None:
        p = tmp_path / "rules.yaml"
        p.write_text(": : : bad yaml [[[")
        config = load_rules(p)
        assert config.yolo is False

    def test_valid_config(self, tmp_path: Path) -> None:
        p = tmp_path / "rules.yaml"
        p.write_text(textwrap.dedent("""\
            yolo: true
            rules:
              - tools: [Read, Glob]
                action: approve
              - tools: [Bash]
                pattern: "^pytest"
                action: approve
              - tools: [Bash]
                pattern: "rm -rf"
                action: deny
            default: approve
        """))
        config = load_rules(p)
        assert config.yolo is True
        assert len(config.rules) == 3
        assert config.default == "approve"
        assert config.rules[0].tools == ["Read", "Glob"]
        assert config.rules[0].action == "approve"
        assert config.rules[1].pattern == "^pytest"
        assert config.rules[2].action == "deny"

    def test_invalid_default_falls_back_to_ask(self, tmp_path: Path) -> None:
        p = tmp_path / "rules.yaml"
        p.write_text("default: banana")
        config = load_rules(p)
        assert config.default == "ask"

    def test_invalid_action_skipped(self, tmp_path: Path) -> None:
        p = tmp_path / "rules.yaml"
        p.write_text(textwrap.dedent("""\
            rules:
              - tools: [Read]
                action: explode
              - tools: [Glob]
                action: approve
        """))
        config = load_rules(p)
        assert len(config.rules) == 1
        assert config.rules[0].tools == ["Glob"]


# ------------------------------------------------------------------
# Rule.matches
# ------------------------------------------------------------------


class TestRuleMatches:

    def test_tool_match_no_pattern(self) -> None:
        rule = Rule(tools=["Read", "Glob"], action="approve")
        assert rule.matches("Read", "") is True
        assert rule.matches("Glob", "some summary") is True
        assert rule.matches("Bash", "") is False

    def test_tool_match_with_pattern(self) -> None:
        rule = Rule(tools=["Bash"], action="approve", pattern=r"^pytest")
        assert rule.matches("Bash", "pytest tests/") is True
        assert rule.matches("Bash", "running pytest") is False
        assert rule.matches("Bash", "rm -rf /") is False

    def test_pattern_not_checked_for_wrong_tool(self) -> None:
        rule = Rule(tools=["Bash"], action="deny", pattern="rm -rf")
        assert rule.matches("Read", "rm -rf /") is False

    def test_pattern_with_none_summary(self) -> None:
        rule = Rule(tools=["Bash"], action="approve", pattern=r"pytest")
        assert rule.matches("Bash", "") is False


# ------------------------------------------------------------------
# evaluate
# ------------------------------------------------------------------


class TestEvaluate:

    def test_no_yolo_always_ask(self) -> None:
        """Without YOLO, everything is manual regardless of rules."""
        config = RulesConfig(
            yolo=False,
            rules=[Rule(tools=["Read", "Glob"], action="approve")],
        )
        assert evaluate(config, "Read", "") == "ask"
        assert evaluate(config, "Glob", "something") == "ask"
        assert evaluate(config, "Bash", "ls") == "ask"

    def test_no_yolo_ignores_deny_rules(self) -> None:
        config = RulesConfig(
            yolo=False,
            rules=[Rule(tools=["Bash"], action="deny", pattern=r"rm -rf")],
        )
        assert evaluate(config, "Bash", "rm -rf /") == "ask"

    def test_yolo_approves_by_default(self) -> None:
        config = RulesConfig(yolo=True)
        assert evaluate(config, "Read", "") == "approve"
        assert evaluate(config, "Bash", "ls -la") == "approve"
        assert evaluate(config, "Unknown", "") == "approve"

    def test_yolo_approve_rule(self) -> None:
        config = RulesConfig(
            yolo=True,
            rules=[Rule(tools=["Read"], action="approve")],
        )
        assert evaluate(config, "Read", "") == "approve"

    def test_yolo_deny_forces_manual_review(self) -> None:
        config = RulesConfig(
            yolo=True,
            rules=[Rule(tools=["Bash"], action="deny", pattern=r"rm -rf")],
        )
        assert evaluate(config, "Bash", "rm -rf /") == "ask"
        # Non-matching → still approved
        assert evaluate(config, "Bash", "pytest tests/") == "approve"

    def test_yolo_first_match_wins(self) -> None:
        config = RulesConfig(
            yolo=True,
            rules=[
                Rule(tools=["Bash"], action="deny", pattern=r"rm -rf"),
                Rule(tools=["Bash"], action="approve"),
            ],
        )
        assert evaluate(config, "Bash", "rm -rf /") == "ask"
        assert evaluate(config, "Bash", "ls -la") == "approve"

    def test_yolo_pattern_match(self) -> None:
        config = RulesConfig(
            yolo=True,
            rules=[Rule(tools=["Bash"], action="approve", pattern=r"pytest")],
        )
        assert evaluate(config, "Bash", "pytest tests/") == "approve"
        assert evaluate(config, "Bash", "rm -rf /") == "approve"  # no deny rule → approve
