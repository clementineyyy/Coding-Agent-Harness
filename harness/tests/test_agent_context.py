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
