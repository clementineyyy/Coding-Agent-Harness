from __future__ import annotations

import os
from pathlib import Path

from harness.registry import Context, Tool, ToolResult

DEFAULT_MAX_OUTPUT_BYTES = 51200
TRUNCATED_MARKER = "[...truncated]"


def spec() -> list[Tool]:
    return [
        Tool(
            name="read_file",
            description="读取工作区内文件（UTF-8，大小受限）",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            handler=read_file,
        ),
        Tool(
            name="write_file",
            description="写入工作区内文件（UTF-8，越界拒绝）",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
            handler=write_file,
        ),
        Tool(
            name="list",
            description="列出工作区内目录内容",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": [],
            },
            handler=list_dir,
        ),
    ]


def _within_workspace(resolved: Path, base: Path) -> bool:
    try:
        if resolved.is_relative_to(base):
            return True
    except (AttributeError, ValueError):
        pass
    resolved_s = str(resolved).lower()
    base_s = str(base).lower()
    return resolved_s == base_s or resolved_s.startswith(base_s + os.sep)


def _resolve_workspace_path(workspace: Path, rel: object) -> Path | None:
    if not isinstance(rel, str) or not rel:
        return None
    try:
        base = Path(workspace).resolve()
        resolved = (Path(workspace) / rel).resolve()
    except (OSError, ValueError, RuntimeError):
        return None
    if _within_workspace(resolved, base):
        return resolved
    return None


def _max_output_bytes(ctx: Context) -> int:
    return int(getattr(ctx.config, "max_output_bytes", DEFAULT_MAX_OUTPUT_BYTES))


def read_file(args: dict, ctx: Context) -> ToolResult:
    path = _resolve_workspace_path(ctx.workspace, args.get("path"))
    if path is None:
        return ToolResult(status="error", error="path outside workspace")
    try:
        data = path.read_bytes()
    except OSError as exc:
        return ToolResult(status="error", error=f"cannot read file: {exc}")
    if len(data) > _max_output_bytes(ctx):
        text = data[:_max_output_bytes(ctx)].decode("utf-8", errors="replace")
        return ToolResult(
            status="success", output=text + TRUNCATED_MARKER, truncated=True
        )
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return ToolResult(status="error", error="file is not valid UTF-8")
    return ToolResult(status="success", output=text)


def write_file(args: dict, ctx: Context) -> ToolResult:
    if args.get("path") is None:
        return ToolResult(status="error", error="path outside workspace")
    path = _resolve_workspace_path(ctx.workspace, args.get("path"))
    if path is None:
        return ToolResult(status="error", error="path outside workspace")
    content = args.get("content") or ""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
    except OSError as exc:
        return ToolResult(status="error", error=f"cannot write file: {exc}")
    return ToolResult(status="success", output=f"wrote {args['path']}")


def list_dir(args: dict, ctx: Context) -> ToolResult:
    path = _resolve_workspace_path(ctx.workspace, args.get("path") or ".")
    if path is None:
        return ToolResult(status="error", error="path outside workspace")
    try:
        entries = sorted(
            str(p.relative_to(path)) for p in path.iterdir()
        )
    except OSError as exc:
        return ToolResult(status="error", error=f"cannot list directory: {exc}")
    if not entries:
        return ToolResult(status="success", output="(empty)")
    return ToolResult(status="success", output="\n".join(entries))
