from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import requests

from harness.registry import Tool

MAX_BYTES = 51200
TRUNCATED_MARKER = "[...truncated]"


@dataclass
class ToolResult:
    status: str
    output: str = ""
    error: str = ""
    truncated: bool = False


def spec(requests_get: Callable | None = None) -> Tool:
    def handler(args: dict, ctx) -> ToolResult:
        if not ctx.sandbox.network_enabled:
            return ToolResult(status="error", error="network disabled")
        get = requests_get if requests_get is not None else requests.get
        url = args["url"]
        max_bytes = min(args.get("max_bytes") or MAX_BYTES, MAX_BYTES)
        try:
            resp = get(url, timeout=10)
        except Exception as exc:
            return ToolResult(status="error", error=str(exc))
        if resp.status_code != 200:
            return ToolResult(status="error", error=f"HTTP {resp.status_code}")
        text = resp.text
        if len(text) > max_bytes:
            return ToolResult(status="success", output=text[:max_bytes] + TRUNCATED_MARKER, truncated=True)
        return ToolResult(status="success", output=text)

    tool = Tool(
        name="fetch_url",
        description="抓取 URL 内容（fetch_url）",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "max_bytes": {"type": "integer"},
            },
            "required": ["url"],
        },
        requires_approval=True,
        needs_sandbox=False,
        uses_workspace=False,
    )
    tool.handler = handler
    return tool
