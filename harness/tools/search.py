from __future__ import annotations

import os
import re
from pathlib import Path

from harness.registry import Context, Tool, ToolResult

MAX_GREP_RESULTS = 200
MAX_LINE_LENGTH = 1000
DEFAULT_MAX_OUTPUT_BYTES = 51200
TRUNCATED_MARKER = "[...truncated]"


def spec() -> list[Tool]:
    return [
        Tool(
            name="glob",
            description="按文件名模式在工作区内匹配文件",
            parameters={
                "type": "object",
                "properties": {"pattern": {"type": "string"}},
                "required": ["pattern"],
            },
            handler=glob_files,
        ),
        Tool(
            name="grep",
            description="在工作区内按正则搜索文件内容",
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "path": {"type": "string"},
                },
                "required": ["pattern"],
            },
            handler=grep,
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


def glob_files(args: dict, ctx: Context) -> ToolResult:
    pattern = args.get("pattern")
    if not isinstance(pattern, str) or not pattern:
        return ToolResult(status="error", error="pattern is required")
    try:
        if Path(pattern).is_absolute():
            return ToolResult(status="error", error="path outside workspace")
        base = Path(ctx.workspace).resolve()
        matches = []
        for p in sorted(base.glob(pattern)):
            if not _within_workspace(p.resolve(), base):
                continue
            matches.append(str(p.relative_to(base)))
    except (OSError, ValueError, RuntimeError) as exc:
        return ToolResult(status="error", error=f"cannot glob: {exc}")
    if not matches:
        return ToolResult(status="success", output="(no matches)")
    return ToolResult(status="success", output="\n".join(matches))


def grep(args: dict, ctx: Context) -> ToolResult:
    pattern = args.get("pattern")
    if not isinstance(pattern, str) or not pattern:
        return ToolResult(status="error", error="pattern is required")
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        return ToolResult(status="error", error=f"invalid regex: {exc}")
    base = Path(ctx.workspace).resolve()
    start = _resolve_workspace_path(ctx.workspace, args.get("path") or ".")
    if start is None:
        return ToolResult(status="error", error="path outside workspace")
    results: list[str] = []
    try:
        if not start.is_dir():
            return ToolResult(status="error", error="path is not a directory")
        for p in start.rglob("*"):
            if not _within_workspace(p.resolve(), base):
                continue
            if not p.is_file():
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                if regex.search(line):
                    shown = line[:MAX_LINE_LENGTH]
                    results.append(f"{p.relative_to(base)}:{lineno}:{shown}")
                    if len(results) >= MAX_GREP_RESULTS:
                        break
            if len(results) >= MAX_GREP_RESULTS:
                break
    except OSError as exc:
        return ToolResult(status="error", error=f"cannot search: {exc}")
    if not results:
        return ToolResult(status="success", output="(no matches)")
    output = "\n".join(results)
    truncated = False
    if len(output) > DEFAULT_MAX_OUTPUT_BYTES:
        output = output[:DEFAULT_MAX_OUTPUT_BYTES] + TRUNCATED_MARKER
        truncated = True
    return ToolResult(
        status="success",
        output=output,
        truncated=truncated or len(results) >= MAX_GREP_RESULTS,
    )
