import json
import re
from dataclasses import dataclass


@dataclass
class Rule:
    pattern: str
    action: str
    source: str


@dataclass
class Verdict:
    action: str
    matched_rule: Rule | None
    reason: str


def pattern_matches(pattern: str, tool_name: str, args: dict) -> bool:
    if ":" in pattern:
        tool, _, regex = pattern.partition(":")
        if tool != tool_name:
            return False
        return re.search(regex, json.dumps(args, ensure_ascii=False)) is not None
    return pattern == tool_name


def default_rules() -> list[Rule]:
    return [
        Rule(r"bash:rm -rf\s+[\\/]?(/|[A-Z]:[\\/]|[A-Z](\b|:)|etc\b|boot\b|bin\b)",
             "deny", "builtin"),
        Rule(r"bash:.*:\(\)\s*\{.*:.*\};", "deny", "builtin"),
        Rule(r"bash:format.*", "deny", "builtin"),
        Rule(r"bash:del /f.*", "deny", "builtin"),
    ]


def evaluate(rules: list[Rule], tool_name: str, args: dict) -> Verdict:
    matched = None
    for rule in rules:
        if pattern_matches(rule.pattern, tool_name, args):
            matched = rule
    if matched is None:
        return Verdict("allow", None, "no rule matched")
    return Verdict(matched.action, matched, f"matched {matched.pattern}")
