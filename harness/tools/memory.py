from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

from harness.registry import Context

if TYPE_CHECKING:
    from harness.memory import MemoryStore


@dataclass
class ToolResult:
    status: str = "success"
    output: str = ""
    error: str | None = None


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict
    handler: Callable[[dict, Context], ToolResult]
    requires_approval: bool = False
    needs_sandbox: bool = False
    uses_workspace: bool = False


def specs(memory: MemoryStore) -> list[ToolSpec]:
    def save_handler(args: dict, ctx: Context) -> ToolResult:
        store = ctx.memory
        if store is None:
            return ToolResult(status="error", error="memory store not available")
        try:
            path = store.save(args["title"], args["content"])
            store.load()
            return _with_warnings(ToolResult(output=f"已保存: {path}"), store)
        except Exception as exc:
            return ToolResult(status="error", error=f"memory save failed: {exc}")

    def search_handler(args: dict, ctx: Context) -> ToolResult:
        store = ctx.memory
        if store is None:
            return ToolResult(status="error", error="memory store not available")
        try:
            results = store.search(args["query"], args.get("k", 3))
        except Exception as exc:
            return ToolResult(status="error", error=f"memory search failed: {exc}")
        if results:
            lines = [f"[{item['title']}] {item['chunk']}" for item in results]
            return _with_warnings(ToolResult(output="\n".join(lines)), store)
        return _with_warnings(ToolResult(output="无相关记忆"), store)

    def _with_warnings(result: ToolResult, store: MemoryStore) -> ToolResult:
        if store.warnings:
            result.output = "\n".join(
                [result.output] + [f"warning: {w}" for w in store.warnings]
            )
        return result

    return [
        ToolSpec(
            name="memory_save",
            description="长期记忆写入",
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["title", "content"],
            },
            handler=save_handler,
            requires_approval=True,
        ),
        ToolSpec(
            name="memory_search",
            description="长期记忆按需检索",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "k": {"type": "integer", "minimum": 1, "maximum": 10},
                },
                "required": ["query"],
            },
            handler=search_handler,
            requires_approval=True,
        ),
    ]
