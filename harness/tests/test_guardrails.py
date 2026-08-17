from harness.guardrails import Rule, evaluate, pattern_matches, default_rules

def test_no_match_allows():
    r = evaluate([Rule("bash:ls.*", "ask", "user")], "bash", {"command": "echo hi"})
    assert r.action == "allow" and r.matched_rule is None

def test_last_match_wins():
    rules = [Rule("bash", "deny", "builtin"), Rule("bash:ls.*", "allow", "user")]
    r = evaluate(rules, "bash", {"command": "ls -la"})
    assert r.action == "allow" and r.matched_rule.source == "user"
    r2 = evaluate(rules, "bash", {"command": "rm x"})
    assert r2.action == "deny"

def test_arg_regex_pattern():
    assert pattern_matches("bash:rm -rf.*", "bash", {"command": "rm -rf ./node_modules"})
    assert not pattern_matches("bash:rm -rf.*", "bash", {"command": "ls"})
    assert pattern_matches("write_file", "write_file", {"path": "x"})

def test_builtin_deny_catches_system_rm_rf():
    rules = default_rules()
    for cmd in ["rm -rf C:\\Windows", "rm -rf /", "rm -rf C:/Program Files", ":(){ :|:& };:"]:
        v = evaluate(rules, "bash", {"command": cmd})
        assert v.action == "deny", cmd
        assert v.matched_rule.source == "builtin"
