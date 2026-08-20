from __future__ import annotations

from harness.registry import Tool, ToolResult


def spec() -> Tool:
    def handler(args: dict, ctx) -> ToolResult:
        result = ctx.sandbox.run(args["command"], ctx.config.tool_timeout)
        if result.exit_code == -1 and "timeout" in (result.stderr or "").lower():
            status = "timeout"
        else:
            status = "success" if result.exit_code == 0 else "error"
        output = result.stdout
        if not ctx.sandbox.network_enabled:
            output = (f"{output}\n[network_enabled=False]").strip()
        return ToolResult(
            status=status,
            output=output,
            error=result.stderr or None,
            exit_code=result.exit_code,
            duration_ms=result.duration_ms,
            truncated=result.truncated,
        )

    tool = Tool(
        name="bash",
        description="执行任意 shell 命令：查询系统（which/where/ps/注册表）、运行程序、文件操作、构建 / 测试 / lint 等",
        parameters={
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
        requires_approval=True,
        needs_sandbox=True,
        uses_workspace=True,
    )
    tool.handler = handler
    return tool
