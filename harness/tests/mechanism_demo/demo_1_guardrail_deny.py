"""机制演示 ①：护栏拦截危险动作（FakeLLM 确定性复现，全程离线）。

运行: python -m harness.tests.mechanism_demo.demo_1_guardrail_deny
断言: pipeline 返回 deny 结果；钩子零触发；沙箱零执行；输出 ⊘ denied。
"""

import sys
import tempfile
from pathlib import Path

from harness.agent import Agent
from harness.config import Config
from harness.fake_llm import FakeLLM, FakeTurn
from harness.hooks import HookBus
from harness.policy import Policy
from harness.registry import make_registry
from harness.sandbox import LocalSandbox
from harness.state import StateMachine
from harness.tools.bash import spec as bash_spec


class SpySandbox(LocalSandbox):
    """记录每次执行调用的 LocalSandbox 包装（spy）。"""

    def __init__(self):
        super().__init__()
        self.calls = []

    def run(self, command, timeout):
        self.calls.append(command)
        return super().run(command, timeout)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    spy = SpySandbox()
    bus = HookBus()
    pre_calls, post_calls = [], []
    bus.register("pre", lambda n, a: (pre_calls.append(n), (a, True))[1])
    bus.register("post", lambda n, a, res: post_calls.append(n))

    with tempfile.TemporaryDirectory() as td:
        cfg = Config(workspace=Path(td), tool_timeout=5)
        reg = make_registry([bash_spec()])
        llm = FakeLLM([
            FakeTurn(tool_calls=[{"name": "bash", "arguments": {"command": "rm -rf C:\\Windows"}}]),
            FakeTurn(text="完成"),
        ])
        agent = Agent(llm, reg, spy, bus, Policy(), StateMachine(), None, cfg)

        print("→ 机制演示 ① 护栏拦截危险动作（FakeLLM 确定性复现，全程离线）")
        result = agent.run("删除系统目录")
        res = result.tool_results[0]
        print(f"⊘ denied: {res.error}")

        assert res.status == "error" and "denied" in (res.error or "")
        assert pre_calls == [] and post_calls == [], "钩子必须零触发"
        assert spy.calls == [], "沙箱必须零执行"
        print("→ 钩子零触发、沙箱零执行：危险命令被护栏拦截，从未到达执行层")
    print("OK: demo ① 护栏拦截")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
