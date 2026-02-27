"""YOLO mode & auto-approve rules engine.

Loads rules from ``~/.config/clorch/rules.yaml`` and evaluates
tool requests against them.  First matching rule wins.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Rule:
    """A single matching rule."""

    tools: list[str]
    action: str  # "approve" | "deny" | "ask"
    pattern: str | None = None

    _compiled: re.Pattern | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.pattern:
            self._compiled = re.compile(self.pattern)

    def matches(self, tool_name: str, tool_summary: str) -> bool:
        """Return True if this rule matches the given tool request."""
        if tool_name not in self.tools:
            return False
        if self._compiled is not None:
            return bool(self._compiled.search(tool_summary or ""))
        return True


@dataclass
class RulesConfig:
    """Top-level rules configuration."""

    yolo: bool = False
    rules: list[Rule] = field(default_factory=list)
    default: str = "ask"  # "ask" | "approve" | "deny"


def load_rules(path: Path | None = None) -> RulesConfig:
    """Load rules from a YAML file.

    Returns a default (all-ask) config if the file doesn't exist or
    is invalid.
    """
    if path is None:
        path = Path("~/.config/clorch/rules.yaml").expanduser()
    else:
        path = Path(path).expanduser()

    if not path.exists():
        return RulesConfig()

    try:
        data = yaml.safe_load(path.read_text()) or {}
    except Exception:
        return RulesConfig()

    yolo = bool(data.get("yolo", False))
    default = str(data.get("default", "ask"))
    if default not in ("ask", "approve", "deny"):
        default = "ask"

    rules: list[Rule] = []
    for entry in data.get("rules", []):
        tools = entry.get("tools", [])
        action = entry.get("action", "ask")
        pattern = entry.get("pattern")
        if tools and action in ("approve", "deny", "ask"):
            rules.append(Rule(tools=tools, action=action, pattern=pattern))

    return RulesConfig(yolo=yolo, rules=rules, default=default)


def evaluate(config: RulesConfig, tool_name: str, tool_summary: str) -> str:
    """Evaluate rules and return ``"approve"``, ``"deny"``, or ``"ask"``.

    Without YOLO — always ``"ask"`` (everything manual).
    With YOLO — auto-approves everything except deny rules,
    which force manual review (``"ask"``).
    """
    if not config.yolo:
        return "ask"

    for rule in config.rules:
        if rule.matches(tool_name, tool_summary):
            if rule.action == "deny":
                return "ask"
            return "approve"

    return "approve"
