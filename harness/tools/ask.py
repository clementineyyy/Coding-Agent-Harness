from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from harness.registry import Context

SCHEMA: dict = {"question": "string", "options": "array[string]"}


@dataclass
class ToolResult:
    status: str = "success"
    output: str = ""
    error: str | None = None


@dataclass
class ToolSpec:
    name: str
    description: str
    schema: dict
    handler: Callable[[dict, Any], ToolResult]


def spec() -> ToolSpec:
    return ToolSpec(
        name="ask_user",
        description="向用户提问，状态机转入 awaiting_user",
        schema=SCHEMA,
        handler=_handler,
    )


def _handler(args: dict, ctx: Context) -> ToolResult:
    ctx.state.fire("agent_question", "agent")
    try:
        if ctx.ask_callback is None:
            return ToolResult(status="error", error="no ask callback available")
        answer = ctx.ask_callback(args["question"], args.get("options", []))
    except Exception:
        return ToolResult(status="error", error="ask cancelled")
    finally:
        ctx.state.fire("user_answered", "user")
    return ToolResult(output=answer)
