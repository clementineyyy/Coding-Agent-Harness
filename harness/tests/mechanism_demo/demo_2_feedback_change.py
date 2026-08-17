"""机制演示 ②：反馈闭环（FakeLLM 确定性复现，全程离线）。

运行: python -m harness.tests.mechanism_demo.demo_2_feedback_change
三回合脚本：失败 → 反思+换动作 → 完成。
断言：失败后实际执行的最后一条命令 ≠ 失败命令；错误反馈已回灌给 LLM
（复用 T20 断言逻辑）。
"""

import json
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


def first_tool_command(result) -> str:
    assistant_calls = [t for t in result.messages if t.get("tool_calls")]
    arguments = json.loads(assistant_calls[0]["tool_calls"][0]["function"]["arguments"])
    return arguments["command"]


def last_tool_command(result) -> str:
    assistant_calls = [t for t in result.messages if t.get("tool_calls")]
    arguments = json.loads(assistant_calls[-1]["tool_calls"][0]["function"]["arguments"])
    return arguments["command"]


def failing_tool_message(result) -> dict:
    raw = next(
        t for t in result.messages
        if t.get("role") == "tool" and '"status": "error"' in t["content"]
    )
    return json.loads(raw["content"])


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    with tempfile.TemporaryDirectory() as td:
        cfg = Config(workspace=Path(td), tool_timeout=5)
        reg = make_registry([bash_spec()])
        llm = FakeLLM([
            FakeTurn(tool_calls=[{"name": "bash", "arguments": {"command": 'python -c "raise SystemExit(1)"'}}]),
            FakeTurn(text="反思：命令失败，换用文件方式",
                     tool_calls=[{"name": "bash", "arguments": {"command": "echo fallback"}}]),
            FakeTurn(text="完成"),
        ])
        agent = Agent(llm, reg, LocalSandbox(), HookBus(), Policy(), StateMachine(), None, cfg)

        print("→ 机制演示 ② 反馈闭环（FakeLLM 确定性复现，全程离线）")
        result = agent.run("处理数据")
        first = first_tool_command(result)
        last = last_tool_command(result)
        reflection = [t for t in result.messages
                      if t.get("role") == "assistant" and t.get("content", "").startswith("反思")]
        feedback = failing_tool_message(result)
        error_desc = feedback["error"] or "(no stderr)"
        print(f"⊘ failed: {error_desc} (status={feedback['status']}, exit_code={feedback['exit_code']})")
        print(f"→ 失败后实际执行的最后一条命令已改变（changed）：{last!r} ≠ {first!r}")
        print(f"→ 错误反馈已回灌给 LLM（tool 消息含 status=error, exit_code={feedback['exit_code']}）")

        fallback_msg = [t for t in result.messages if t.get("tool_calls")][-1]
        fail_msg = next(t for t in result.messages
                        if t.get("role") == "tool" and '"status": "error"' in t["content"])
        assert reflection, "应存在反思消息"
        assert first != last, "失败后下一条动作必须改变"
        assert last == "echo fallback", "最后执行的命令必须是换动作后的 fallback"
        assert result.messages.index(fail_msg) < result.messages.index(fallback_msg), \
            "错误反馈必须先于换动作回合进入消息历史"
        assert result.failed_sequence == 1
        assert feedback["status"] == "error" and feedback["exit_code"] == 1
    print("OK: demo ② 反馈闭环")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
