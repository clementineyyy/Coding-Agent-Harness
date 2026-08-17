import json

from harness.agent import Agent
from harness.config import Config
from harness.fake_llm import FakeLLM, FakeTurn
from harness.hooks import HookBus
from harness.policy import Policy
from harness.registry import make_registry
from harness.sandbox import LocalSandbox
from harness.state import StateMachine
from harness.tools.bash import spec as bash_spec


def make_agent(tmp_path, turns, failure_budget=3):
    sb = LocalSandbox()
    cfg = Config(workspace=tmp_path, tool_timeout=5, failure_budget=failure_budget)
    reg = make_registry([bash_spec()])
    return Agent(FakeLLM(turns), reg, sb, HookBus(), Policy(), StateMachine(), None, cfg)


def _first_tool_command(result):
    assistant_calls = [t for t in result.messages if t.get("tool_calls")]
    arguments = json.loads(assistant_calls[0]["tool_calls"][0]["function"]["arguments"])
    return arguments["command"]


def _failing_tool_message(result):
    return next(
        t for t in result.messages
        if t.get("role") == "tool" and '"status": "error"' in t["content"]
    )


def test_failure_changes_next_action(tmp_path):
    turns = [
        FakeTurn(tool_calls=[{"name": "bash", "arguments": {"command": "python -c \"raise SystemExit(1)\""}}]),
        FakeTurn(text="反思：命令失败，换用文件方式"),
        FakeTurn(tool_calls=[{"name": "bash", "arguments": {"command": "echo fallback"}}]),
        FakeTurn(text="完成"),
    ]
    a = make_agent(tmp_path, turns)
    r = a.run("t")
    first = _first_tool_command(r)
    after = [t for t in r.messages if t.get("role") == "assistant" and t.get("content", "").startswith("反思")]
    assert after, "应存在反思消息"
    assert first != "echo fallback"  # 下一条动作确实改变
    assert r.failed_sequence == 1
    feedback = json.loads(_failing_tool_message(r)["content"])
    assert feedback["status"] == "error" and feedback["exit_code"] == 1  # 客观反馈信号回灌


def test_failure_budget_stops_retrying(tmp_path):
    turns = [FakeTurn(tool_calls=[{"name": "bash", "arguments": {"command": "python -c \"raise SystemExit(1)\""}}]),
             FakeTurn(tool_calls=[{"name": "bash", "arguments": {"command": "python -c \"raise SystemExit(1)\""}}]),
             FakeTurn(tool_calls=[{"name": "bash", "arguments": {"command": "python -c \"raise SystemExit(1)\""}}]),
             FakeTurn(tool_calls=[{"name": "bash", "arguments": {"command": "python -c \"raise SystemExit(1)\""}}])]
    a = make_agent(tmp_path, turns, failure_budget=3)
    r = a.run("t")
    assert "连续失败" in r.text or "不再重试" in r.text
