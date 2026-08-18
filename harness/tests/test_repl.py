import io
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from harness.config import Config
from harness.main import ask_menu, run_repl


def make_fake_store(monkeypatch, key=None):
    state = {"key": key}
    store = SimpleNamespace(
        get=lambda: state["key"],
        set=lambda k: state.update(key=k),
        clear=lambda: state.update(key=None),
        status=lambda: {
            "configured": state["key"] is not None,
            "source": "keyring" if state["key"] is not None else None,
            "verified_at": None,
        },
    )
    monkeypatch.setattr("harness.main.CredentialStore", lambda *a, **k: store)
    return store


def build_agent(tmp_path, turns=None, policy=None, hooks=None, llm=None):
    from harness.agent import Agent
    from harness.fake_llm import FakeLLM, FakeTurn
    from harness.hooks import HookBus
    from harness.policy import Policy
    from harness.registry import make_registry
    from harness.sandbox import LocalSandbox
    from harness.state import StateMachine
    from harness.tools.bash import spec as bash_spec

    cfg = Config(workspace=tmp_path, tool_timeout=5)
    if llm is None:
        llm = FakeLLM(turns if turns is not None else [FakeTurn(text="ok")])
    return Agent(
        llm,
        make_registry([bash_spec()]),
        LocalSandbox(),
        hooks or HookBus(),
        policy or Policy(),
        StateMachine(),
        None,
        cfg,
    )


def feed_inputs(monkeypatch, values):
    iterator = iter(values)
    monkeypatch.setattr("builtins.input", lambda *a: next(iterator))


def raise_keyboard_interrupt(*a):
    raise KeyboardInterrupt()


def test_ask_menu_numbered(tmp_path):
    out = io.StringIO()
    options = ["重试", "换方案"]
    with patch("builtins.input", side_effect=["2"]), patch("sys.stdout", out):
        assert ask_menu("怎么办", options) == "换方案"
    rendered = out.getvalue()
    assert "1. 重试" in rendered and "2. 换方案" in rendered


def test_ask_menu_retries_on_invalid_number(tmp_path):
    out = io.StringIO()
    options = ["重试", "换方案"]
    with patch("builtins.input", side_effect=["abc", "1"]), patch("sys.stdout", out):
        assert ask_menu("怎么办", options) == "重试"
    assert "无效选择" in out.getvalue()


def test_ask_menu_eof_raises_keyboard_interrupt(tmp_path):
    out = io.StringIO()
    options = ["重试", "换方案"]
    with patch("builtins.input", side_effect=EOFError), patch("sys.stdout", out):
        with pytest.raises(KeyboardInterrupt):
            ask_menu("怎么办", options)


def test_run_repl_with_fake_llm(tmp_path, monkeypatch, capsys):
    from harness.fake_llm import FakeLLM, FakeTurn

    turns = [
        FakeTurn(tool_calls=[{"name": "bash", "arguments": {"command": "echo hi"}}]),
        FakeTurn(text="搞定了"),
    ]
    agent = build_agent(tmp_path, turns=turns)
    cfg = Config(workspace=tmp_path, tool_timeout=5)
    monkeypatch.setattr("harness.main.make_agent", lambda cfg: agent)
    monkeypatch.setattr("builtins.input", lambda *a: "/exit")
    assert run_repl(cfg) == 0
    out = capsys.readouterr().out
    assert "搞定了" in out or "echo hi" in out


def test_make_agent_builds_dependency_graph(tmp_path, monkeypatch):
    from harness.main import make_agent

    make_fake_store(monkeypatch, key="DUMMY-KEY")
    agent = make_agent(Config(workspace=tmp_path, tool_timeout=5))
    expected = {
        "bash", "read_file", "write_file", "list", "glob", "grep",
        "fetch_url", "notes_append", "notes_list", "memory_save",
        "memory_search", "ask_user", "list_skills", "load_skill",
        "run_subagent",
    }
    assert expected <= set(agent.registry)
    assert agent.ask_callback is ask_menu
    assert agent.on_text is not None


def test_agent_on_text_streams_each_text_segment(tmp_path):
    from harness.fake_llm import FakeLLM, FakeTurn

    seen = []
    turns = [
        FakeTurn(text="先查一下", tool_calls=[{"name": "bash", "arguments": {"command": "echo hi"}}]),
        FakeTurn(text="搞定"),
    ]
    agent = build_agent(tmp_path, turns=turns)
    agent.on_text = seen.append
    agent.run("t")
    assert seen == ["先查一下", "搞定"]


def test_run_repl_without_credentials_fails_gracefully(tmp_path, monkeypatch, capsys):
    make_fake_store(monkeypatch, key=None)

    def boom(cfg):
        raise RuntimeError("未配置 DeepSeek API Key")

    monkeypatch.setattr("harness.main.make_agent", boom)
    monkeypatch.setattr("builtins.input", lambda *a: "/exit")
    assert run_repl(Config(workspace=tmp_path, tool_timeout=5)) == 0
    out = capsys.readouterr().out
    assert "未配置" in out


def test_run_repl_top_level_ctrl_c_exits_cleanly_with_session_end(tmp_path, monkeypatch, capsys):
    from harness.hooks import HookBus

    make_fake_store(monkeypatch, key="DUMMY-KEY")
    bus = HookBus()
    ended = []
    bus.register("session_end", lambda msgs: ended.append(msgs))
    agent = build_agent(tmp_path, hooks=bus)
    monkeypatch.setattr("harness.main.make_agent", lambda cfg: agent)
    monkeypatch.setattr("builtins.input", raise_keyboard_interrupt)
    assert run_repl(Config(workspace=tmp_path, tool_timeout=5)) == 0
    assert ended == [[]]


def test_run_repl_slash_commands(tmp_path, monkeypatch, capsys):
    make_fake_store(monkeypatch, key="DUMMY-KEY")
    skills = tmp_path / "skills" / "demo"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text("# demo\n", encoding="utf-8")
    memdir = tmp_path / "memory"
    memdir.mkdir()
    (memdir / "notes.md").write_text("笔记\n", encoding="utf-8")
    agent = build_agent(tmp_path)
    monkeypatch.setattr("harness.main.make_agent", lambda cfg: agent)
    feed_inputs(monkeypatch, ["t1", "/skills", "/memory", "/rules", "/exit"])
    assert run_repl(Config(workspace=tmp_path, tool_timeout=5)) == 0
    out = capsys.readouterr().out
    assert "demo" in out and "notes" in out and "deny" in out


def test_run_repl_rules_drop_skill(tmp_path, monkeypatch, capsys):
    from harness.guardrails import Rule
    from harness.policy import Policy

    make_fake_store(monkeypatch, key="DUMMY-KEY")
    pol = Policy()
    pol.add_skill_rules([Rule("bash:echo.*", "ask", "skill:demo")])
    agent = build_agent(tmp_path, policy=pol)
    monkeypatch.setattr("harness.main.make_agent", lambda cfg: agent)
    feed_inputs(monkeypatch, ["t1", "/rules drop skill:demo", "/exit"])
    assert run_repl(Config(workspace=tmp_path, tool_timeout=5)) == 0
    out = capsys.readouterr().out
    assert "已移除" in out
    assert not any(r.source == "skill:demo" for r in pol.rules)


def test_run_repl_key_commands(tmp_path, monkeypatch, capsys):
    store = make_fake_store(monkeypatch, key=None)
    monkeypatch.setattr("harness.main.wizard_enter_key", lambda: "DUMMY-KEY")
    agent = build_agent(tmp_path)
    monkeypatch.setattr("harness.main.make_agent", lambda cfg: agent)
    feed_inputs(monkeypatch, ["y", "n", "t1", "/key status", "/key clear", "/key status", "/exit"])
    assert run_repl(Config(workspace=tmp_path, tool_timeout=5)) == 0
    out = capsys.readouterr().out
    assert "已保存" in out and "配置: 是" in out and "已从 keyring 清除" in out and "配置: 否" in out
    assert store.get() is None


def test_run_repl_task_shows_tool_activity_and_stats(tmp_path, monkeypatch, capsys):
    from harness.fake_llm import FakeLLM, FakeTurn

    make_fake_store(monkeypatch, key="DUMMY-KEY")
    agent = build_agent(
        tmp_path,
        turns=[
            FakeTurn(tool_calls=[{"name": "bash", "arguments": {"command": "echo hi"}}]),
            FakeTurn(text="搞定了"),
        ],
    )
    monkeypatch.setattr("harness.main.make_agent", lambda cfg: agent)
    feed_inputs(monkeypatch, ["task1", "/exit"])
    assert run_repl(Config(workspace=tmp_path, tool_timeout=5)) == 0
    out = capsys.readouterr().out
    assert "→ bash" in out and "搞定了" in out
    assert "[step 2/50 | ~20 tok]" in out


def test_run_repl_interrupt_menu_abort(tmp_path, monkeypatch, capsys):
    make_fake_store(monkeypatch, key="DUMMY-KEY")
    agent = build_agent(tmp_path)
    real_run = agent.run
    calls = {"n": 0}

    def flaky(task):
        calls["n"] += 1
        if calls["n"] == 1:
            raise KeyboardInterrupt()
        return real_run(task)

    agent.run = flaky
    monkeypatch.setattr("harness.main.make_agent", lambda cfg: agent)
    feed_inputs(monkeypatch, ["t1", "2", "/exit"])
    assert run_repl(Config(workspace=tmp_path, tool_timeout=5)) == 0
    out = capsys.readouterr().out
    assert "已中止" in out


def test_run_repl_interrupt_menu_resume_reruns_task(tmp_path, monkeypatch, capsys):
    from harness.fake_llm import FakeLLM, FakeTurn

    make_fake_store(monkeypatch, key="DUMMY-KEY")
    agent = build_agent(
        tmp_path,
        turns=[
            FakeTurn(tool_calls=[{"name": "bash", "arguments": {"command": "echo hi"}}]),
            FakeTurn(text="搞定了"),
        ],
    )
    real_run = agent.run
    calls = {"n": 0}

    def flaky(task):
        calls["n"] += 1
        if calls["n"] == 1:
            raise KeyboardInterrupt()
        return real_run(task)

    agent.run = flaky
    monkeypatch.setattr("harness.main.make_agent", lambda cfg: agent)
    feed_inputs(monkeypatch, ["t1", "1", "/exit"])
    assert run_repl(Config(workspace=tmp_path, tool_timeout=5)) == 0
    out = capsys.readouterr().out
    assert "搞定了" in out and calls["n"] == 2


def test_run_repl_survives_llm_errors(tmp_path, monkeypatch, capsys):
    from harness.llm import LLMAuthError

    make_fake_store(monkeypatch, key="DUMMY-KEY")

    class BoomLLM:
        def __init__(self):
            self.calls = 0

        def complete(self, messages, tools):
            self.calls += 1
            raise LLMAuthError("invalid api key")

    boom = BoomLLM()
    agent = build_agent(tmp_path, llm=boom)
    monkeypatch.setattr("harness.main.make_agent", lambda cfg: agent)
    feed_inputs(monkeypatch, ["task1", "task2", "/exit"])
    assert run_repl(Config(workspace=tmp_path, tool_timeout=5)) == 0
    out = capsys.readouterr().out
    assert "API 调用失败" in out and "invalid api key" in out
    assert boom.calls == 2 and "任务: task2" in out


def test_run_repl_interrupt_in_running_state_resume(tmp_path, monkeypatch, capsys):
    from harness.fake_llm import FakeLLM, FakeTurn

    make_fake_store(monkeypatch, key="DUMMY-KEY")
    agent = build_agent(
        tmp_path,
        turns=[
            FakeTurn(tool_calls=[{"name": "bash", "arguments": {"command": "echo hi"}}]),
            FakeTurn(text="搞定了"),
        ],
    )
    real_run = agent.run
    calls = {"n": 0}

    def flaky(task):
        calls["n"] += 1
        if calls["n"] == 1:
            agent.state.fire("task_submitted", "loop")
            raise KeyboardInterrupt()
        return real_run(task)

    agent.run = flaky
    monkeypatch.setattr("harness.main.make_agent", lambda cfg: agent)
    feed_inputs(monkeypatch, ["t1", "1", "/exit"])
    assert run_repl(Config(workspace=tmp_path, tool_timeout=5)) == 0
    out = capsys.readouterr().out
    assert "搞定了" in out and calls["n"] == 2
    assert agent.state.state == "completed"


def test_key_set_verify_failure_does_not_store(tmp_path, monkeypatch, capsys):
    store = make_fake_store(monkeypatch, key="DUMMY-KEY")
    agent = build_agent(tmp_path)
    monkeypatch.setattr("harness.main.make_agent", lambda cfg: agent)
    monkeypatch.setattr("harness.main.wizard_enter_key", lambda: "sk-bad")
    monkeypatch.setattr("harness.main.verify_api_key", lambda base, key: False)
    feed_inputs(monkeypatch, ["t1", "/key set", "y", "y", "y", "/exit"])
    assert run_repl(Config(workspace=tmp_path, tool_timeout=5)) == 0
    out = capsys.readouterr().out
    assert "验证失败" in out and store.get() == "DUMMY-KEY"


def test_key_set_verify_success_stores_and_marks(tmp_path, monkeypatch, capsys):
    store = make_fake_store(monkeypatch, key="DUMMY-KEY")
    marks = []
    store.mark_verified = lambda: marks.append(1)
    agent = build_agent(tmp_path)
    monkeypatch.setattr("harness.main.make_agent", lambda cfg: agent)
    monkeypatch.setattr("harness.main.wizard_enter_key", lambda: "sk-good")
    monkeypatch.setattr("harness.main.verify_api_key", lambda base, key: True)
    feed_inputs(monkeypatch, ["t1", "/key set", "y", "/exit"])
    assert run_repl(Config(workspace=tmp_path, tool_timeout=5)) == 0
    assert store.get() == "sk-good" and marks == [1]


def test_key_clear_env_source_hints_manual_removal(tmp_path, monkeypatch, capsys):
    state = {"key": "sk-env"}
    store = SimpleNamespace(
        get=lambda: state["key"],
        set=lambda k: state.update(key=k),
        clear=lambda: state.update(key=None),
        status=lambda: {
            "configured": True,
            "source": "env",
            "verified_at": None,
        },
    )
    monkeypatch.setattr("harness.main.CredentialStore", lambda *a, **k: store)
    agent = build_agent(tmp_path)
    monkeypatch.setattr("harness.main.make_agent", lambda cfg: agent)
    feed_inputs(monkeypatch, ["t1", "/key clear", "/exit"])
    assert run_repl(Config(workspace=tmp_path, tool_timeout=5)) == 0
    out = capsys.readouterr().out
    assert "手动从 .env 中删除" in out
    assert state["key"] == "sk-env"
