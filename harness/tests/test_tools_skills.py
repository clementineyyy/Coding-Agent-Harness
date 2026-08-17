import shutil
from pathlib import Path

from harness.config import Config
from harness.policy import Policy
from harness.registry import Context, make_registry
from harness.sandbox import LocalSandbox
from harness.state import StateMachine
from harness.tools.skills import specs as skills_specs

FIXTURES = Path(__file__).parent / "fixtures" / "skills"


def ctx(ws, policy):
    return Context(workspace=ws, sandbox=LocalSandbox(), hooks=None, policy=policy,
                   state=StateMachine(), memory=None, config=Config(workspace=ws))


def copied_root(tmp_path):
    skills_root = tmp_path / "skills"
    shutil.copytree(FIXTURES, skills_root)
    return skills_root


def test_load_skill_tightens_rules(tmp_path):
    p = Policy()
    reg = make_registry(skills_specs(copied_root(tmp_path)))
    r = reg["load_skill"].handler({"name": "reviewer"}, ctx(tmp_path, p))
    assert r.status == "success"
    assert "[skill:reviewer]" in r.output
    assert "allow 声明被拒绝" in r.output  # 警告
    skill_actions = {rule.action for rule in p.rules if rule.source == "skill:reviewer"}
    assert skill_actions == {"ask"}


def test_load_broken_skill_warns(tmp_path):
    reg = make_registry(skills_specs(copied_root(tmp_path)))
    r = reg["load_skill"].handler({"name": "broken"}, ctx(tmp_path, Policy()))
    assert r.status == "error" or "跳过" in r.output


def test_list_skills_lists_names(tmp_path):
    reg = make_registry(skills_specs(copied_root(tmp_path)))
    r = reg["list_skills"].handler({}, ctx(tmp_path, Policy()))
    assert r.status == "success"
    assert "reviewer" in r.output
    assert "broken" in r.output


def test_load_missing_skill_returns_error(tmp_path):
    reg = make_registry(skills_specs(copied_root(tmp_path)))
    r = reg["load_skill"].handler({"name": "nope"}, ctx(tmp_path, Policy()))
    assert r.status == "error"


def test_load_skill_rejects_path_traversal(tmp_path):
    reg = make_registry(skills_specs(copied_root(tmp_path)))
    r = reg["load_skill"].handler({"name": "../secret"}, ctx(tmp_path, Policy()))
    assert r.status == "error"
