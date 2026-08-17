"""性能冒烟（SPEC.md §9 4.x）：会话启动 < 1s（空记忆库）、检索 < 50ms（100 条目）。"""

import time

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


def test_session_start_under_1s(tmp_path):
    mem = MemoryStore(tmp_path)
    mem.load()
    llm = FakeLLM([FakeTurn(text="完成")])
    cfg = Config(workspace=tmp_path, tool_timeout=5)
    a = Agent(llm, make_registry([bash_spec()]), LocalSandbox(), HookBus(),
              Policy(), StateMachine(), mem, cfg)
    t0 = time.monotonic()
    r = a.run("简单任务")
    elapsed = time.monotonic() - t0
    assert r.text == "完成"
    assert elapsed < 1.0, f"会话启动耗时 {elapsed:.3f}s 超过 1s"


def test_retrieval_100_entries_under_50ms(tmp_path):
    m = MemoryStore(tmp_path)
    for i in range(100):
        m.save(f"note-{i}", f"内容 {i} " * 30)
    m.load()
    t0 = time.monotonic()
    hits = m.search("内容 50", k=5)
    elapsed = time.monotonic() - t0
    assert hits
    assert elapsed < 0.05, f"检索耗时 {elapsed * 1000:.1f}ms 超过 50ms"
