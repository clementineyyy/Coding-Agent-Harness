from harness.guardrails import Rule
from harness.policy import Policy

def test_always_allow_downgrades():
    p = Policy(user_rules=[Rule("bash:rm -rf.*", "ask", "user")])
    p.apply_answer(Rule("bash:rm -rf.*", "ask", "user"), "always_allow")
    assert any(r.pattern == "bash:rm -rf.*" and r.action == "allow" for r in p.rules)

def test_double_deny_upgrades_to_deny():
    p = Policy(user_rules=[Rule("bash:chmod.*", "ask", "user")])
    p.apply_answer(Rule("bash:chmod.*", "ask", "user"), "n")
    p.apply_answer(Rule("bash:chmod.*", "ask", "user"), "n")
    assert any(r.pattern == "bash:chmod.*" and r.action == "deny" for r in p.rules)

def test_skill_rules_tighten_only():
    p = Policy()
    rejected = p.add_skill_rules([
        Rule("bash:rm -rf.*", "allow", "skill:demo"),
        Rule("write_file:.*secrets.*", "ask", "skill:demo"),
    ])
    assert len(rejected) == 1 and "allow" in rejected[0]
    actions = {r.action for r in p.rules if r.source == "skill:demo"}
    assert actions == {"ask"}

def test_user_rules_beat_skill_rules():
    p = Policy(
        user_rules=[Rule("bash:git push.*", "ask", "user")],
        skill_rules=[Rule("bash:git push.*", "deny", "skill:demo")],
    )
    first = next(r for r in p.rules if r.pattern == "bash:git push.*" and r.source == "user")
    assert first.action == "ask"

def test_changes_recorded():
    p = Policy(user_rules=[Rule("bash:x", "ask", "user")])
    p.apply_answer(Rule("bash:x", "ask", "user"), "always_allow")
    assert p.changes()[-1]["new_action"] == "allow"
