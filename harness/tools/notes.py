from __future__ import annotations

from pathlib import Path

from harness.registry import Context, Tool, ToolResult

NOTES_FILE = ".harness_notes.md"


def spec() -> list[Tool]:
    return [
        Tool(
            name="notes_append",
            description="追加一条便签（跨回合临时要点，不写入长期记忆）",
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
            handler=notes_append,
        ),
        Tool(
            name="notes_list",
            description="列出全部便签",
            parameters={"type": "object", "properties": {}, "required": []},
            handler=notes_list,
        ),
    ]


def _notes_path(ctx: Context) -> Path:
    return Path(ctx.workspace) / NOTES_FILE


def notes_append(args: dict, ctx: Context) -> ToolResult:
    text = args.get("text", "")
    try:
        _notes_path(ctx).parent.mkdir(parents=True, exist_ok=True)
        with _notes_path(ctx).open("a", encoding="utf-8", newline="") as f:
            f.write(text.rstrip("\n") + "\n")
    except OSError as exc:
        return ToolResult(status="error", error=f"cannot append note: {exc}")
    return ToolResult(status="success", output=f"note appended: {text}")


def notes_list(args: dict, ctx: Context) -> ToolResult:
    path = _notes_path(ctx)
    if not path.exists():
        return ToolResult(status="success", output="(no notes)")
    try:
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln]
    except OSError as exc:
        return ToolResult(status="error", error=f"cannot read notes: {exc}")
    if not lines:
        return ToolResult(status="success", output="(no notes)")
    return ToolResult(status="success", output="\n".join(lines))
