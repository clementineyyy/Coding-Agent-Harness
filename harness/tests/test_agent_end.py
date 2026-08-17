import json

from harness.agent import Agent
from harness.config import Config
from harness.fake_llm import FakeLLM, FakeTurn
from harness.guardrails import Rule
from harness.hooks import HookBus
from harness.memory import MemoryStore
from harness.policy import Policy
from harness.registry import make_registry
from harness.sandbox import LocalSandbox
from harness.state import StateMachine
from harness.tools.bash import spec as bash_spec


def test_session_end_before_memory_consolidation(tmp_path):
    order = []
    mem = MemoryStore(tmp_path)
    sb = LocalSandbox()
    cfg = Config(workspace=tmp_path, tool_timeout=5)
    reg = make_registry([bash_spec()])
    llm = FakeLLM([FakeTurn(text="完成"), FakeTurn(text="会话总结：完成了任务")])
    bus = HookBus()
    original_end = bus.session_end

    def wrapped(messages):
        order.append("session_end")
        original_end(messages)

    bus.session_end = wrapped
    a = Agent(llm, reg, sb, bus, Policy(), StateMachine(), mem, cfg)
    a.run("t")
    assert order == ["session_end"]
    mem.load()
    assert any("会话总结" in h["chunk"] for h in mem.search("总结", k=5))


def test_transcript_written_with_policy_changes(tmp_path):
    td = tmp_path / "transcripts"
    td.mkdir()
    sb = LocalSandbox()
    cfg = Config(workspace=tmp_path, tool_timeout=5)
    reg = make_registry([bash_spec()])
    pol = Policy()
    pol.apply_answer(Rule("bash:echo.*", "ask", "user"), "always_allow")
    llm = FakeLLM([FakeTurn(text="done")])
    bus = HookBus(transcript_dir=td)
    a = Agent(llm, reg, sb, bus, pol, StateMachine(), None, cfg)
    a.run("t")
    files = list(td.glob("*.json"))
    assert files
    data = json.loads(files[0].read_text(encoding="utf-8"))
    assert data["messages"] and data["policy_changes"]
