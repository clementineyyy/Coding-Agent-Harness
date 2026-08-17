from harness.agent import Agent
from harness.config import Config
from harness.fake_llm import FakeLLM, FakeTurn
from harness.hooks import HookBus
from harness.memory import MemoryStore
from harness.policy import Policy
from harness.registry import make_registry
from harness.sandbox import LocalSandbox
from harness.state import StateMachine
from harness.tools.bash import spec as bash_spec


def test_memory_injected_at_start(tmp_path):
    mem = MemoryStore(tmp_path)
    mem.save("约定", "禁止在生产库执行写操作。")
    mem.load()
    sb = LocalSandbox()
    cfg = Config(workspace=tmp_path, tool_timeout=5)
    reg = make_registry([bash_spec()])
    llm = FakeLLM([FakeTurn(text="done")])
    a = Agent(llm, reg, sb, HookBus(), Policy(), StateMachine(), mem, cfg)
    a.run("处理生产库任务")
    system_msgs = [m for m in a.messages if m["role"] == "system"]
    assert any("[memory]" in m["content"] and "禁止在生产库" in m["content"] for m in system_msgs)


def test_budget_compression_drops_oldest_when_llm_fails(tmp_path):
    cfg = Config(workspace=tmp_path, max_budget_tokens=400, compression_keep_turns=2, tool_timeout=5)
    sb = LocalSandbox()
    reg = make_registry([bash_spec()])

    class Boom:
        def complete(self, messages, tools):
            raise RuntimeError("compress fail")

    a = Agent(Boom(), reg, sb, HookBus(), Policy(), StateMachine(), None, cfg)
    a.messages = [{"role": "user", "content": "x" * 400}] + [{"role": "assistant", "content": "y" * 400}] * 4
    out = a._compress(a.messages)
    assert len(out) <= 3 and out[0]["role"] == "user"  # 保留了最近（降级丢弃最旧）


class RecordingLLM(FakeLLM):
    def __init__(self, turns):
        super().__init__(turns)
        self.seen = []

    def complete(self, messages, tools):
        self.seen.append((messages, list(tools)))
        return super().complete(messages, tools)


class CountingLLM(FakeLLM):
    def __init__(self, turns):
        super().__init__(turns)
        self.summary_calls = 0

    def complete(self, messages, tools):
        if not tools:
            self.summary_calls += 1
        return super().complete(messages, tools)


def test_compress_success_summary_and_tail_retention(tmp_path):
    cfg = Config(workspace=tmp_path, compression_keep_turns=2, tool_timeout=5)
    llm = RecordingLLM([FakeTurn(text="关键事实摘要")])
    a = Agent(llm, make_registry([bash_spec()]), LocalSandbox(), HookBus(), Policy(), StateMachine(), None, cfg)
    msgs = [{"role": "user", "content": "x" * 40}] + [{"role": "assistant", "content": f"y{i}"} for i in range(4)]
    out = a._compress(msgs)
    assert out[0]["role"] == "system" and out[0]["content"] == "[summary] 关键事实摘要"
    assert out[1:] == msgs[-2:]  # 保留最近 keep_turns 回合完整
    payload = llm.seen[-1][0][1]["content"]  # json.dumps 载荷只含被丢弃的最旧回合
    assert "y0" in payload and "y1" in payload and "y2" not in payload
    assert llm.seen[-1][1] == []  # 摘要调用不带工具


def test_compress_rounds_cap_degrades_in_run(tmp_path):
    cfg = Config(workspace=tmp_path, max_budget_tokens=100, compression_keep_turns=2,
                 compression_max_rounds=2, tool_timeout=5, max_steps=10)
    tool_turn = FakeTurn(text="y" * 400, tool_calls=[{"name": "bash", "arguments": {"command": "echo hi"}}])
    llm = CountingLLM([tool_turn] * 6 + [FakeTurn(text="done")])
    a = Agent(llm, make_registry([bash_spec()]), LocalSandbox(), HookBus(), Policy(), StateMachine(), None, cfg)
    r = a.run("x" * 400)
    assert r.text == "done"
    assert llm.summary_calls == 2  # 步数上限：2 轮后不再调 LLM 摘要，降级丢弃最旧


def test_budget_boundary_exact_is_not_over(tmp_path):
    cfg = Config(workspace=tmp_path, max_budget_tokens=100, tool_timeout=5)
    a = Agent(FakeLLM([]), make_registry([bash_spec()]), LocalSandbox(), HookBus(), Policy(), StateMachine(), None, cfg)
    assert a._check_budget([{"role": "user", "content": "x" * 400}]) is False  # 400/4 == 100 未超
    assert a._check_budget([{"role": "user", "content": "x" * 401}]) is True   # 100.25 > 100 超


def test_drop_oldest_keeps_window_when_already_anchored(tmp_path):
    cfg = Config(workspace=tmp_path, compression_keep_turns=2, tool_timeout=5)
    a = Agent(FakeLLM([]), make_registry([bash_spec()]), LocalSandbox(), HookBus(), Policy(), StateMachine(), None, cfg)
    msgs = [{"role": "user", "content": "t1"}, {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "t2"}, {"role": "assistant", "content": "a2"}]
    out = a._drop_oldest(msgs, 2)
    assert out == msgs[-2:]  # 窗口已以 user 开头，原样保留（无需回锚）

