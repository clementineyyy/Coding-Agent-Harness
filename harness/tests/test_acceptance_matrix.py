"""§9 验收矩阵：逐条映射 SPEC.md §9 的客观验收标准（全部离线，FakeLLM）。

每条测试引用既有模块行为（T9/T10/T17/T18/T19/T20/T21/T22/T23 已实现），
本文件只做断言映射，不重复实现逻辑。
"""

import json
import shutil
import sys
from pathlib import Path

from harness.agent import Agent
from harness.config import Config
from harness.fake_llm import FakeLLM, FakeTurn
from harness.guardrails import Rule, default_rules, evaluate
from harness.hooks import HookBus
from harness.mcp import load_mcp_servers
from harness.memory import MemoryStore
from harness.policy import Policy
from harness.registry import (
    REGISTRY,
    Context,
    Tool,
    make_registry,
    validate_args,
)
from harness.sandbox import LocalSandbox
from harness.state import StateMachine
from harness.tools.bash import spec as bash_spec
from harness.tools.memory import specs as memory_specs
from harness.tools.skills import specs as skills_specs
from harness.tools.subagent import spec as subagent_spec

SKILL_FIXTURES = Path(__file__).parent / "fixtures" / "skills"
MCP_FAKE = Path(__file__).parent / "fixtures" / "fake_mcp_server.py"


def make_agent(
    tmp_path,
    turns,
    *,
    max_steps=50,
    failure_budget=3,
    policy=None,
    hooks=None,
    memory=None,
    registry=None,
    ask_callback=None,
):
    sb = LocalSandbox()
    cfg = Config(
        workspace=tmp_path,
        tool_timeout=5,
        max_steps=max_steps,
        failure_budget=failure_budget,
    )
    if registry is None:
        registry = make_registry([bash_spec()])
    return Agent(
        FakeLLM(turns),
        registry,
        sb,
        hooks or HookBus(),
        policy if policy is not None else Policy(),
        StateMachine(),
        memory,
        cfg,
        ask_callback=ask_callback,
    )


def tool_context(ws, policy=None, memory=None, registry=None, state=None, llm=None):
    return Context(
        workspace=ws,
        sandbox=LocalSandbox(),
        hooks=None,
        policy=policy if policy is not None else Policy(),
        state=state if state is not None else StateMachine(),
        memory=memory,
        config=Config(workspace=ws, max_steps=30),
        llm=llm,
        registry=registry,
    )


# ---- §3.1 纯 LLM -----------------------------------------------------------


def test_31_multi_tool_calls_same_turn_parsed(tmp_path):
    turns = [
        FakeTurn(
            tool_calls=[
                {"name": "bash", "arguments": {"command": "echo first"}},
                {"name": "bash", "arguments": {"command": "echo second"}},
            ]
        ),
        FakeTurn(text="完成"),
    ]
    a = make_agent(tmp_path, turns)
    r = a.run("t")
    assert r.steps_used == 2
    assert len(r.tool_results) == 2
    assert all(t.status == "success" for t in r.tool_results)
    tool_msgs = [m for m in r.messages if m["role"] == "tool"]
    assert len(tool_msgs) == 2
    assistant_tc = [m for m in r.messages if m.get("tool_calls")][0]["tool_calls"]
    assert [m["tool_call_id"] for m in tool_msgs] == [tc["id"] for tc in assistant_tc]
    assert "first" in tool_msgs[0]["content"] and "second" in tool_msgs[1]["content"]


def test_31_step_limit_clear_message(tmp_path):
    a = make_agent(
        tmp_path,
        [FakeTurn(tool_calls=[{"name": "bash", "arguments": {"command": "echo x"}}])],
        max_steps=3,
    )
    r = a.run("循环")
    assert r.steps_used == 3
    assert "步数上限" in r.text


# ---- §3.2 工具 -------------------------------------------------------------


def test_32_schema_rejects_missing_required():
    err = validate_args(REGISTRY["bash"].parameters, {})
    assert err is not None and "command" in err
    assert validate_args(REGISTRY["bash"].parameters, {"command": "echo hi"}) is None


def test_32_pipeline_rejects_bad_args_with_error_result(tmp_path):
    a = make_agent(
        tmp_path,
        [
            FakeTurn(tool_calls=[{"name": "bash", "arguments": {}}]),
            FakeTurn(text="完成"),
        ],
    )
    r = a.run("t")
    assert len(r.tool_results) == 1
    assert r.tool_results[0].status == "error"
    assert "参数错误" in (r.tool_results[0].error or "")
    assert r.text == "完成"


# ---- §3.3 上下文工程 -------------------------------------------------------


def test_33_task_start_injects_top2(tmp_path):
    mem = MemoryStore(tmp_path, top_k=2)
    mem.save("a", "x" * 60)
    mem.save("b", "x" * 60)
    mem.save("c", "y" * 60)
    mem.load()
    a = make_agent(tmp_path, [FakeTurn(text="done")], memory=mem)
    a.run("xxx")
    memory_msgs = [
        m
        for m in a.messages
        if m["role"] == "system" and m["content"].startswith("[memory]")
    ]
    assert len(memory_msgs) == 2


def test_33_memory_search_top1_most_relevant(tmp_path):
    m = MemoryStore(tmp_path)
    reg = make_registry(memory_specs(m))
    ctx = tool_context(tmp_path, memory=m)
    reg["memory_save"].handler(
        {"title": "约定", "content": "禁止在生产库执行写操作。"}, ctx
    )
    reg["memory_save"].handler({"title": "无关", "content": "今天天气很好。"}, ctx)
    r = reg["memory_search"].handler({"query": "生产库", "k": 1}, ctx)
    assert r.status == "success"
    assert "[约定]" in r.output and "[无关]" not in r.output


# ---- §3.4 钩子与护栏 -------------------------------------------------------


def test_34_dangerous_bash_patterns_denied():
    for cmd in ["rm -rf C:\\Windows", "rm -rf /", ":(){ :|:& };:"]:
        v = evaluate(default_rules(), "bash", {"command": cmd})
        assert v.action == "deny", cmd


def test_34_ask_without_callback_never_auto_approves(tmp_path):
    pol = Policy(user_rules=[Rule("bash:echo.*", "ask", "user")])
    a = make_agent(
        tmp_path,
        [
            FakeTurn(tool_calls=[{"name": "bash", "arguments": {"command": "echo hi"}}]),
            FakeTurn(text="完成"),
        ],
        policy=pol,
    )
    r = a.run("t")
    assert len(r.tool_results) == 1
    assert r.tool_results[0].status == "error"
    assert "guardrail denied" in (r.tool_results[0].error or "")


def test_34_always_allow_downgrades_double_deny_upgrades():
    p = Policy(user_rules=[Rule("bash:rm -rf.*", "ask", "user")])
    p.apply_answer(Rule("bash:rm -rf.*", "ask", "user"), "always_allow")
    assert next(
        r for r in p.rules if r.pattern == "bash:rm -rf.*" and r.source == "user"
    ).action == "allow"
    p2 = Policy(user_rules=[Rule("bash:chmod.*", "ask", "user")])
    p2.apply_answer(Rule("bash:chmod.*", "ask", "user"), "n")
    p2.apply_answer(Rule("bash:chmod.*", "ask", "user"), "n")
    assert next(
        r for r in p2.rules if r.pattern == "bash:chmod.*" and r.source == "user"
    ).action == "deny"


def test_34_hook_order_guardrail_pre_tool_post(tmp_path):
    events = []
    bus = HookBus()

    def pre(name, args):
        events.append(("pre", name))
        return args, True

    def post(name, args, result):
        events.append(("post", name))

    bus.register("pre", pre)
    bus.register("post", post)
    a = make_agent(tmp_path, [], hooks=bus)
    a.state.fire("task_submitted", "loop")
    res = a.pipeline(
        {"name": "bash", "arguments": {"command": "echo hi"}}, a.context_for_tool()
    )
    assert res.status == "success"
    assert events == [("pre", "bash"), ("post", "bash")]
    assert [h["event"] for h in a.state.event_history] == [
        "task_submitted",
        "tool_requested",
        "tool_finished",
    ]


def test_34_deny_runs_no_hooks(tmp_path):
    bus = HookBus()
    seen = []
    bus.register("pre", lambda n, a: (seen.append(n), (a, True))[1])
    pol = Policy(user_rules=[Rule("bash:rm -rf.*", "deny", "user")])
    a = make_agent(tmp_path, [], policy=pol, hooks=bus)
    res = a.pipeline(
        {"name": "bash", "arguments": {"command": "rm -rf /"}}, a.context_for_tool()
    )
    assert res.status == "error"
    assert seen == []


# ---- §3.5 子智能体与技能 ---------------------------------------------------


def test_35_subagent_isolation_and_guardrail_inheritance(tmp_path):
    def echo_tool():
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

    class RecordingFakeLLM(FakeLLM):
        def __init__(self, turns):
            super().__init__(turns)
            self.messages = []

        def complete(self, messages, tools):
            self.messages.append([dict(m) for m in messages])
            return super().complete(messages, tools)

    p = Policy(skill_rules=[Rule("echo:.*secret.*", "deny", "skill:demo")])
    reg = make_registry([echo_tool(), subagent_spec()])
    llm = RecordingFakeLLM(
        [
            FakeTurn(tool_calls=[{"name": "echo", "arguments": {"text": "my secret"}}]),
            FakeTurn(text="完成"),
        ]
    )
    st = StateMachine()
    ctx = tool_context(tmp_path, policy=p, registry=reg, state=st, llm=llm)
    r = reg["run_subagent"].handler({"task": "子任务"}, ctx)
    assert r["status"] == "success"
    assert r["tool_calls"][0]["blocked"] == "deny"
    assert st.state == "idle"
    assert len(llm.messages[0]) == 2
    assert llm.messages[0][0]["role"] == "system"


def test_35_skill_allow_declaration_rejected_with_warning(tmp_path):
    root = tmp_path / "skills"
    shutil.copytree(SKILL_FIXTURES, root)
    p = Policy()
    reg = make_registry(skills_specs(root))
    r = reg["load_skill"].handler({"name": "reviewer"}, tool_context(tmp_path, policy=p))
    assert r.status == "success"
    assert "allow 声明被拒绝" in r.output
    actions = {rule.action for rule in p.rules if rule.source == "skill:reviewer"}
    assert actions == {"ask"}


def test_35_mcp_fake_server_registers_and_forwards(tmp_path):
    cfg = Config(
        workspace=tmp_path,
        mcp_servers=[
            {
                "name": "demo",
                "type": "stdio",
                "command": sys.executable,
                "args": [str(MCP_FAKE)],
            }
        ],
    )
    reg = make_registry([])
    active = load_mcp_servers(cfg.mcp_servers, reg, LocalSandbox(), cfg)
    assert active == ["demo"]
    tool = reg["echo_tool"]
    assert tool.parameters["properties"]["text"]["type"] == "string"
    r = tool.handler({"text": "mcp-ok"}, None)
    assert r.status == "success" and "mcp-ok" in r.output


def test_35_mcp_connection_failure_disables_only_that_server(tmp_path):
    reg = make_registry([])
    cfg = Config(
        workspace=tmp_path,
        mcp_servers=[{"name": "dead", "type": "stdio", "command": "does-not-exist-xyz"}],
    )
    assert load_mcp_servers(cfg.mcp_servers, reg, LocalSandbox(), cfg) == []


# ---- §3.6 反馈循环 ---------------------------------------------------------


def test_36_failure_injection_changes_next_action(tmp_path):
    turns = [
        FakeTurn(
            tool_calls=[
                {
                    "name": "bash",
                    "arguments": {"command": "python -c \"raise SystemExit(1)\""},
                }
            ]
        ),
        FakeTurn(
            text="反思：命令失败，换用文件方式",
            tool_calls=[{"name": "bash", "arguments": {"command": "echo fallback"}}],
        ),
        FakeTurn(text="完成"),
    ]
    a = make_agent(tmp_path, turns)
    r = a.run("t")
    assistant_calls = [m for m in r.messages if m.get("tool_calls")]
    first = json.loads(assistant_calls[0]["tool_calls"][0]["function"]["arguments"])[
        "command"
    ]
    after = json.loads(assistant_calls[1]["tool_calls"][0]["function"]["arguments"])[
        "command"
    ]
    assert first != after
    assert any(
        m.get("role") == "assistant" and m.get("content", "").startswith("反思")
        for m in r.messages
    )
    assert r.failed_sequence == 1


def test_36_failure_budget_stops_retrying(tmp_path):
    fail = FakeTurn(
        tool_calls=[
            {
                "name": "bash",
                "arguments": {"command": "python -c \"raise SystemExit(1)\""},
            }
        ]
    )
    a = make_agent(tmp_path, [fail] * 4, failure_budget=3)
    r = a.run("t")
    assert "连续失败" in r.text or "不再重试" in r.text
    assert r.failed_sequence == 3


# ---- §4.x 非功能 -----------------------------------------------------------


def test_4x_transcript_fields_complete(tmp_path):
    td = tmp_path / "transcripts"
    td.mkdir()
    pol = Policy()
    pol.apply_answer(Rule("bash:echo.*", "ask", "user"), "always_allow")
    bus = HookBus(transcript_dir=td)
    a = make_agent(
        tmp_path,
        [
            FakeTurn(tool_calls=[{"name": "bash", "arguments": {"command": "echo hi"}}]),
            FakeTurn(text="done"),
        ],
        policy=pol,
        hooks=bus,
    )
    r = a.run("t")
    assert r.transcript_path is not None
    files = list(td.glob("*.json"))
    assert files
    data = json.loads(files[0].read_text(encoding="utf-8"))
    assert {"messages", "tool_calls", "policy_changes", "written_at"} <= set(data)
    assert data["messages"] and data["tool_calls"] and data["policy_changes"]


def test_4x_rules_reflect_policy():
    p = Policy()
    assert any(rule.action == "deny" for rule in p.rules)
    p.apply_answer(Rule("bash:echo.*", "ask", "user"), "always_allow")
    rendered = {rule.pattern: rule.action for rule in p.rules}
    assert rendered["bash:echo.*"] == "allow"
    p.apply_answer(Rule("bash:echo.*", "ask", "user"), "n")
    p.apply_answer(Rule("bash:echo.*", "ask", "user"), "n")
    rendered = {rule.pattern: rule.action for rule in p.rules}
    assert rendered["bash:echo.*"] == "deny"
