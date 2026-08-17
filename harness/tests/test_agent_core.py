from harness.agent import Agent
from harness.config import Config
from harness.fake_llm import FakeLLM, FakeTurn
from harness.guardrails import Rule
from harness.hooks import HookBus
from harness.policy import Policy
from harness.registry import make_registry
from harness.sandbox import LocalSandbox
from harness.state import StateMachine
from harness.tools.bash import spec as bash_spec


def make_agent(tmp_path, turns, max_steps=50):
    sb = LocalSandbox()
    cfg = Config(workspace=tmp_path, tool_timeout=5, max_steps=max_steps)
    reg = make_registry([bash_spec()])
    llm = FakeLLM(turns)
    return Agent(llm, reg, sb, HookBus(), Policy(), StateMachine(), None, cfg)


def test_simple_task_ends_with_final_answer(tmp_path):
    a = make_agent(tmp_path, [FakeTurn(tool_calls=[{"name": "bash", "arguments": {"command": "echo hi"}}]),
                              FakeTurn(text="完成")])
    r = a.run("做个事")
    assert "完成" in r.text and r.steps_used == 2


def test_step_limit_terminates_cleanly(tmp_path):
    a = make_agent(tmp_path, [FakeTurn(tool_calls=[{"name": "bash", "arguments": {"command": "echo x"}}])],
                   max_steps=3)
    r = a.run("循环")
    assert "步数上限" in r.text or "step" in r.text.lower()


def test_pipeline_order_guardrail_hooks_state(tmp_path):
    sb = LocalSandbox()
    cfg = Config(workspace=tmp_path, tool_timeout=5)
    reg = make_registry([bash_spec()])
    bus = HookBus()
    events = []
    bus.register("pre", lambda n, a: (events.append(("pre", n)), (a, True))[1])
    bus.register("post", lambda n, a, res: events.append(("post", n)))
    st = StateMachine()
    st.fire("task_submitted", "loop")
    a = Agent(FakeLLM([]), reg, sb, bus, Policy(), st, None, cfg)
    a.pipeline({"name": "bash", "arguments": {"command": "echo hi"}}, a.context_for_tool())
    assert ("pre", "bash") in events and ("post", "bash") in events
    assert st.event_history[-1]["event"] == "tool_finished"


def test_deny_stops_before_hooks_and_execution(tmp_path):
    sb = LocalSandbox()
    cfg = Config(workspace=tmp_path)
    reg = make_registry([bash_spec()])
    bus = HookBus()
    pre_called = []
    bus.register("pre", lambda n, a: (pre_called.append(n), (a, True))[1])
    pol = Policy(user_rules=[Rule("bash:rm -rf.*", "deny", "user")])
    llm = FakeLLM([FakeTurn(tool_calls=[{"name": "bash", "arguments": {"command": "rm -rf /"}}]),
                   FakeTurn(text="ok")])
    st = StateMachine()
    a = Agent(llm, reg, sb, bus, pol, st, None, cfg)
    r = a.run("t")
    assert pre_called == []  # 钩子没被触发
    assert any("denied" in str(t) for t in r.tool_results)


def test_ask_guardrail_callback_answer_allows_and_continues(tmp_path):
    sb = LocalSandbox()
    cfg = Config(workspace=tmp_path, tool_timeout=5)
    reg = make_registry([bash_spec()])
    pol = Policy(user_rules=[Rule("bash:echo.*", "ask", "user")])
    answers = []
    llm = FakeLLM([FakeTurn(tool_calls=[{"name": "bash", "arguments": {"command": "echo hi"}}]),
                   FakeTurn(text="done")])
    st = StateMachine()
    a = Agent(llm, reg, sb, HookBus(), pol, st, None, cfg,
              ask_callback=lambda question, options: (answers.append((question, options)), "y")[1])
    r = a.run("t")
    assert answers and "echo" in answers[0][0]
    assert any(t.status == "success" for t in r.tool_results)
    assert "done" in r.text
