from harness.config import Config
from harness.fake_llm import FakeLLM, FakeTurn
from harness.guardrails import Rule
from harness.llm import LLM, LLMError
from harness.policy import Policy
from harness.registry import Context, Tool, make_registry
from harness.sandbox import LocalSandbox
from harness.state import StateMachine
from harness.tools.subagent import spec as subagent_spec


def echo_tool() -> Tool:
    t = Tool(
        name="echo",
        description="回显文本",
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    )

    def handler(args, ctx):
        return {"status": "success", "output": f"echoed:{args['text']}"}

    t.handler = handler
    return t


def boom_tool() -> Tool:
    t = Tool(
        name="boom",
        description="总是抛异常",
        parameters={"type": "object", "properties": {}, "required": []},
    )

    def handler(args, ctx):
        raise RuntimeError("tool boom")

    t.handler = handler
    return t


class RecordingFakeLLM(FakeLLM):
    def __init__(self, turns):
        super().__init__(turns)
        self.messages: list[list[dict]] = []

    def complete(self, messages, tools):
        self.messages.append([dict(m) for m in messages])
        return super().complete(messages, tools)


class BoomLLM(LLM):
    def complete(self, messages, tools):
        raise LLMError("llm boom")


def make_ctx(workspace, llm=None, registry=None, policy=None, config=None, state=None):
    return Context(
        workspace=workspace,
        sandbox=LocalSandbox(),
        hooks=None,
        policy=policy if policy is not None else Policy(),
        state=state if state is not None else StateMachine(),
        memory=None,
        config=config if config is not None else Config(workspace=workspace),
        llm=llm,
        registry=registry,
    )


def test_subagent_runs_tools_and_returns_final_answer(tmp_path):
    sub = subagent_spec()
    reg = make_registry([echo_tool(), sub])
    llm = RecordingFakeLLM([
        FakeTurn(tool_calls=[{"name": "echo", "arguments": {"text": "sub-ok"}}]),
        FakeTurn(text="子完成"),
    ])
    state = StateMachine()
    ctx = make_ctx(tmp_path, llm=llm, registry=reg, state=state,
                   config=Config(workspace=tmp_path, max_steps=30))
    r = reg["run_subagent"].handler({"task": "子任务", "system_prompt": "你是测试子代理"}, ctx)
    assert r["status"] == "success"
    assert r["output"] == "子完成"
    assert r["tool_calls"] == [{"name": "echo", "arguments": {"text": "sub-ok"}, "status": "success"}]
    assert state.state == "idle"  # 父状态机未被触碰
    first = llm.messages[0]
    assert first[0]["role"] == "system"
    assert first[0]["content"] == "你是测试子代理"
    assert first[1] == {"role": "user", "content": "子任务"}


def test_subagent_llm_failure_is_isolated(tmp_path):
    sub = subagent_spec()
    reg = make_registry([sub])
    ctx = make_ctx(tmp_path, llm=BoomLLM(), registry=reg)
    r = reg["run_subagent"].handler({"task": "子任务"}, ctx)
    assert r["status"] == "error"
    assert "llm boom" in r["output"]


def test_subagent_tool_error_is_fed_back(tmp_path):
    reg = make_registry([boom_tool(), subagent_spec()])
    llm = FakeLLM([
        FakeTurn(tool_calls=[{"name": "boom", "arguments": {}}]),
        FakeTurn(text="仍然完成"),
    ])
    ctx = make_ctx(tmp_path, llm=llm, registry=reg)
    r = reg["run_subagent"].handler({"task": "子任务"}, ctx)
    assert r["status"] == "success"
    assert r["output"] == "仍然完成"
    assert r["tool_calls"][0]["status"] == "error"


def test_subagent_step_limit(tmp_path):
    reg = make_registry([echo_tool(), subagent_spec()])
    llm = FakeLLM([FakeTurn(tool_calls=[{"name": "echo", "arguments": {"text": "x"}}])])
    ctx = make_ctx(tmp_path, llm=llm, registry=reg,
                   config=Config(workspace=tmp_path, max_steps=3))
    r = reg["run_subagent"].handler({"task": "子任务"}, ctx)
    assert r["status"] == "error"
    assert "3 步" in r["output"]
    assert len(r["tool_calls"]) == 3


def test_subagent_inherits_guardrails(tmp_path):
    p = Policy(skill_rules=[Rule("echo:.*secret.*", "deny", "skill:demo")])
    reg = make_registry([echo_tool(), subagent_spec()])
    llm = RecordingFakeLLM([
        FakeTurn(tool_calls=[{"name": "echo", "arguments": {"text": "my secret"}}]),
        FakeTurn(text="完成"),
    ])
    ctx = make_ctx(tmp_path, llm=llm, registry=reg, policy=p)
    r = reg["run_subagent"].handler({"task": "子任务"}, ctx)
    assert r["status"] == "success"
    assert r["tool_calls"][0]["blocked"] == "deny"
    assert "拒绝" in llm.messages[1][-1]["content"]


def test_subagent_without_dependencies_returns_error(tmp_path):
    sub = subagent_spec()
    reg = make_registry([sub])
    ctx = make_ctx(tmp_path)
    r = reg["run_subagent"].handler({"task": "子任务"}, ctx)
    assert r["status"] == "error"
