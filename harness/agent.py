from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from harness.guardrails import evaluate
from harness.registry import (
    Context,
    ToolResult,
    build_request_tools,
    validate_args,
)

if TYPE_CHECKING:
    from harness.config import Config
    from harness.fake_llm import FakeLLM
    from harness.hooks import HookBus
    from harness.llm import LLM
    from harness.memory import MemoryStore
    from harness.policy import Policy
    from harness.sandbox import Sandbox
    from harness.state import StateMachine

SYSTEM_PROMPT = (
    "你是编码代理助手。可调用工具完成任务："
    "先规划，再执行，最后给出最终答案。"
)

_ASK_OPTIONS = ["y", "n", "always_allow", "never_allow"]


@dataclass
class AgentResult:
    text: str = ""
    steps_used: int = 0
    tool_results: list[dict] = field(default_factory=list)
    policy_changes: list[dict] = field(default_factory=list)
    messages: list[dict] = field(default_factory=list)
    failed_sequence: int = 0


class Agent:
    def __init__(
        self,
        llm: LLM,
        registry: dict[str, Any],
        sandbox: Sandbox,
        hooks: HookBus,
        policy: Policy,
        state: StateMachine,
        memory: MemoryStore | None,
        config: Config,
        ask_callback: Callable | None = None,
    ):
        self.llm = llm
        self.registry = registry
        self.sandbox = sandbox
        self.hooks = hooks
        self.policy = policy
        self.state = state
        self.memory = memory
        self.config = config
        self.ask_callback = ask_callback

    def context_for_tool(self) -> Context:
        return Context(
            workspace=self.config.workspace,
            sandbox=self.sandbox,
            hooks=self.hooks,
            policy=self.policy,
            state=self.state,
            memory=self.memory,
            config=self.config,
            ask_callback=self.ask_callback,
            llm=self.llm,
            registry=self.registry,
        )

    def pipeline(self, call: dict, ctx: Context) -> ToolResult:
        name = call["name"]
        args = call["arguments"]
        verdict = evaluate(self.policy.rules, name, args)
        if verdict.action == "deny":
            return ToolResult(status="error", error=f"guardrail denied: {verdict.reason}")
        if verdict.action == "ask":
            self.state.fire("approval_needed", "guardrail")
            answer = self._ask(verdict.matched_rule, verdict.reason)
            self.policy.apply_answer(verdict.matched_rule, answer)
            if self.state.state == "awaiting_user":
                self.state.fire("user_answered", "user")
            if answer in ("n", "never_allow"):
                return ToolResult(status="error", error=f"guardrail denied: {verdict.reason}")
        if self.state.state == "awaiting_user":
            self.state.fire("user_answered", "user")
        args, ok = self.hooks.pre_tool_use(name, args)
        if not ok:
            return ToolResult(status="error", error=f"pre_tool_use hook rejected {name}")
        self.state.fire("tool_requested", "loop")
        tool = self.registry.get(name)
        if tool is None:
            result = ToolResult(status="error", error=f"unknown tool: {name}")
        else:
            err = validate_args(tool.parameters, args, self.config.workspace)
            if err is not None:
                result = ToolResult(status="error", error=f"参数错误: {err}")
            else:
                try:
                    result = tool.handler(args, ctx)
                except Exception as exc:
                    result = ToolResult(
                        status="error",
                        error=f"工具 {name} 异常：{type(exc).__name__}: {exc}",
                    )
        self.state.fire("tool_finished", "loop")
        self.hooks.post_tool_use(name, args, result)
        return result

    def _ask(self, rule, reason: str) -> str:
        question = f"是否允许执行该操作？\n规则: {rule.pattern}\n原因: {reason}"
        if self.ask_callback is None:
            return "n"
        try:
            answer = self.ask_callback(question, list(_ASK_OPTIONS))
        except Exception:
            return "n"
        if answer not in _ASK_OPTIONS:
            return "n"
        return answer

    def run(self, task: str) -> AgentResult:
        result = AgentResult()
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": task},
        ]
        call_uid = 0
        fail_seq = 0
        fail_tool: str | None = None
        max_fail_seq = 0
        self.state.fire("task_submitted", "loop")
        while result.steps_used < self.config.max_steps:
            response = self.llm.complete(messages, build_request_tools(self.registry))
            result.steps_used += 1
            if not response.tool_calls:
                final = response.text or "任务完成"
                messages.append({"role": "assistant", "content": final})
                result.text = final
                result.messages = messages
                result.failed_sequence = max_fail_seq
                self.state.fire("final_answer", "loop")
                return result
            assistant_call = []
            for i, call in enumerate(response.tool_calls):
                assistant_call.append({
                    "id": f"call_{call_uid}",
                    "type": "function",
                    "function": {
                        "name": call["name"],
                        "arguments": json.dumps(call["arguments"], ensure_ascii=False),
                    },
                })
                call_uid += 1
            messages.append({
                "role": "assistant",
                "content": response.text,
                "tool_calls": assistant_call,
            })
            for i, call in enumerate(response.tool_calls):
                tool_id = f"call_{call_uid - len(response.tool_calls) + i}"
                tool_result = self.pipeline(call, self.context_for_tool())
                result.tool_results.append(tool_result)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_id,
                    "name": call["name"],
                    "content": json.dumps(
                        self._result_to_dict(tool_result), ensure_ascii=False
                    ),
                })
                norm = self._result_to_dict(tool_result)
                failed = norm.get("status") != "success" or bool(norm.get("error"))
                if failed:
                    if call["name"] == fail_tool:
                        fail_seq += 1
                    else:
                        fail_seq = 1
                        fail_tool = call["name"]
                    max_fail_seq = max(max_fail_seq, fail_seq)
                    if fail_seq >= self.config.failure_budget:
                        final = (
                            f"连续失败 {fail_seq} 次（工具 {fail_tool}），"
                            f"超过失败预算 {self.config.failure_budget}，停止重试。"
                        )
                        messages.append({"role": "assistant", "content": final})
                        result.text = final
                        result.messages = messages
                        result.failed_sequence = max_fail_seq
                        self.state.fire("final_answer", "loop")
                        return result
                else:
                    fail_seq = 0
                    fail_tool = None
        final = f"达到步数上限 {self.config.max_steps}，任务终止，未挂死。"
        messages.append({"role": "assistant", "content": final})
        result.text = final
        result.messages = messages
        result.failed_sequence = max_fail_seq
        self.state.fire("final_answer", "loop")
        return result

    @staticmethod
    def _result_to_dict(tool_result) -> dict:
        if isinstance(tool_result, ToolResult):
            return {
                "status": tool_result.status,
                "output": tool_result.output,
                "error": tool_result.error,
                "exit_code": tool_result.exit_code,
            }
        if isinstance(tool_result, dict):
            return tool_result
        return {"status": "success", "output": str(tool_result)}
