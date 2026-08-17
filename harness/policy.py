from datetime import datetime

from harness.guardrails import Rule, default_rules


class Policy:
    def __init__(self, user_rules: list[Rule] | None = None,
                 skill_rules: list[Rule] | None = None):
        self._user_rules = [Rule(r.pattern, r.action, r.source) for r in (user_rules or [])]
        self._skill_rules = [Rule(r.pattern, r.action, r.source) for r in (skill_rules or [])]
        self._counts: dict[str, int] = {}
        self._changes: list[dict] = []

    @property
    def rules(self) -> list[Rule]:
        return default_rules() + self._skill_rules + self._user_rules

    def apply_answer(self, rule: Rule, answer: str) -> None:
        stored = next((r for r in self._user_rules
                       if r.pattern == rule.pattern and r.source == rule.source), None)
        if answer == "always_allow":
            if stored is None:
                self._user_rules.append(Rule(rule.pattern, "allow", rule.source))
                self._changes.append({
                    "rule_pattern": rule.pattern,
                    "old_action": None,
                    "new_action": "allow",
                    "answer": answer,
                    "at": datetime.now().isoformat(),
                })
            elif stored.action != "allow":
                old = stored.action
                stored.action = "allow"
                self._changes.append({
                    "rule_pattern": rule.pattern,
                    "old_action": old,
                    "new_action": "allow",
                    "answer": answer,
                    "at": datetime.now().isoformat(),
                })
            return
        if answer == "never_allow":
            if stored is None:
                self._user_rules.append(Rule(rule.pattern, "deny", rule.source))
                self._changes.append({
                    "rule_pattern": rule.pattern,
                    "old_action": None,
                    "new_action": "deny",
                    "answer": answer,
                    "at": datetime.now().isoformat(),
                })
            elif stored.action != "deny":
                old = stored.action
                stored.action = "deny"
                self._changes.append({
                    "rule_pattern": rule.pattern,
                    "old_action": old,
                    "new_action": "deny",
                    "answer": answer,
                    "at": datetime.now().isoformat(),
                })
            return
        if stored is None:
            return
        count = self._counts.get(rule.pattern, 0) + 1
        self._counts[rule.pattern] = count
        if answer == "n" and count >= 2 and stored.action != "deny":
            old = stored.action
            stored.action = "deny"
            self._changes.append({
                "rule_pattern": rule.pattern,
                "old_action": old,
                "new_action": "deny",
                "answer": answer,
                "at": datetime.now().isoformat(),
            })
        elif answer == "y" and count >= 3 and stored.action != "allow":
            old = stored.action
            stored.action = "allow"
            self._changes.append({
                "rule_pattern": rule.pattern,
                "old_action": old,
                "new_action": "allow",
                "answer": answer,
                "at": datetime.now().isoformat(),
            })

    def add_skill_rules(self, skill_rules: list[Rule]) -> list[str]:
        rejected = []
        for rule in skill_rules:
            if rule.action not in ("ask", "deny"):
                rejected.append(f"{rule.pattern} -> {rule.action}")
                continue
            self._skill_rules.append(Rule(rule.pattern, rule.action, rule.source))
        return rejected

    def changes(self) -> list[dict]:
        return list(self._changes)
