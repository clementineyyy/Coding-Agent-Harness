"""机制演示 ③：HITL 状态机全轨迹（FakeLLM 确定性复现，全程离线）。

运行: python -m harness.tests.mechanism_demo.demo_3_hitl_trace
完整轨迹：idle --task_submitted--> running --approval_needed(guardrail)-->
awaiting_user --user_answered--> running --tool_requested--> executing
--tool_finished--> running --final_answer--> completed
断言: state.event_history 精确等于该事件序列（确定性全轨迹）。
"""

import sys
import tempfile
from pathlib import Path

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

EXPECTED_EVENTS = [
    "task_submitted",
    "approval_needed",
    "user_answered",
    "tool_requested",
    "tool_finished",
    "final_answer",
]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    with tempfile.TemporaryDirectory() as td:
        cfg = Config(workspace=Path(td), tool_timeout=5)
        reg = make_registry([bash_spec()])
        pol = Policy(user_rules=[Rule("bash:echo.*", "ask", "user")])
        st = StateMachine()
        answers = []
        llm = FakeLLM([
            FakeTurn(tool_calls=[{"name": "bash", "arguments": {"command": "echo hello"}}]),
            FakeTurn(text="完成"),
        ])
        agent = Agent(llm, reg, LocalSandbox(), HookBus(), pol, st, None, cfg,
                      ask_callback=lambda q, opts: (answers.append(q), "y")[1])

        print("→ 机制演示 ③ HITL 状态机全轨迹（FakeLLM 确定性复现，全程离线）")
        result = agent.run("输出问候语")
        print("? 询问用户（guardrail ask 规则命中），回答: y")
        trace = " → ".join(
            f"{e['from']} --{e['event']}({e['source']})--> {e['to']}"
            for e in st.event_history
        )
        print(f"→ {trace}")

        actual = [e["event"] for e in st.event_history]
        assert actual == EXPECTED_EVENTS, f"状态机全轨迹偏离预期: {actual}"
        assert answers and st.state == "completed"
        assert result.tool_results[0].status == "success" and result.text == "完成"
    print("TRACE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
