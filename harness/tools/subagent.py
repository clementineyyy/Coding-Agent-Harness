from __future__ import annotations

import json

from harness.guardrails import evaluate
from harness.registry import Context, Tool, build_request_tools, validate_args

DEFAULT_SYSTEM_PROMPT = (
    "你是子智能体，独立执行子任务。可调用工具完成任务；"
    "任务完成后给出最终答案，不要输出多余内容。"
)


def spec() -> Tool:
    t = Tool(
        name="run_subagent",
        description="派生子智能体执行子任务（独立上下文、独立步数上限）",
        parameters={
            "type": "object",
            "properties": {
                "task": {"type": "string"},
                "system_prompt": {"type": "string"},
            },
            "required": ["task"],
        },
        requires_approval=True,
        needs_sandbox=False,
        uses_workspace=False,
    )
    t.handler = handler
    return t


def handler(args, ctx: Context) -> dict:
    try:
        return _run(args, ctx)
    except Exception as exc:
        return {"status": "error", "output": f"run_subagent 失败：{type(exc).__name__}: {exc}"}


def _run(args, ctx: Context) -> dict:
    if not isinstance(args, dict) or not isinstance(args.get("task"), str):
        return {"status": "error", "output": "run_subagent 需要 task 参数"}
    if ctx.llm is None or ctx.registry is None:
        return {"status": "error", "output": "run_subagent 不可用：未注入 llm/registry"}
    system_prompt = args.get("system_prompt") or DEFAULT_SYSTEM_PROMPT
    max_steps = getattr(ctx.config, "max_steps", 50) if ctx.config else 50
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": args["task"]},
    ]
    executed: list[dict] = []
    call_uid = 0
    for _step in range(max_steps):
        result = ctx.llm.complete(messages, build_request_tools(ctx.registry))
        if not result.tool_calls:
            return {"status": "success", "output": result.text, "tool_calls": executed}
        assistant_call = []
        for i, call in enumerate(result.tool_calls):
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
            "content": result.text,
            "tool_calls": assistant_call,
        })
        for i, call in enumerate(result.tool_calls):
            tool_id = f"call_{call_uid - len(result.tool_calls) + i}"
            name, call_args = call["name"], call["arguments"]
            verdict = evaluate(ctx.policy.rules, name, call_args)
            if verdict.action != "allow":
                executed.append({"name": name, "arguments": call_args, "blocked": verdict.action})
                content = json.dumps(
                    {"status": "blocked", "output": f"护栏拒绝（{verdict.action}）：{verdict.reason}"},
                    ensure_ascii=False,
                )
            else:
                tool_result = _run_tool(ctx, name, call_args)
                executed.append({"name": name, "arguments": call_args, "status": tool_result["status"]})
                content = json.dumps(tool_result, ensure_ascii=False)
            messages.append({
                "role": "tool",
                "tool_call_id": tool_id,
                "name": name,
                "content": content,
            })
    return {"status": "error", "output": f"run_subagent: 子任务在 {max_steps} 步内未完成", "tool_calls": executed}


def _run_tool(ctx: Context, name: str, call_args) -> dict:
    tool = ctx.registry.get(name)
    if tool is None:
        return {"status": "error", "output": f"未知工具: {name}"}
    err = validate_args(tool.parameters, call_args, ctx.workspace)
    if err is not None:
        return {"status": "error", "output": f"参数错误: {err}"}
    try:
        result = tool.handler(call_args, ctx)
    except Exception as exc:
        return {"status": "error", "output": f"工具 {name} 异常：{type(exc).__name__}: {exc}"}
    if not isinstance(result, dict):
        result = {"status": "success", "output": str(result)}
    return result
