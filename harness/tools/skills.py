from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Callable

from harness.guardrails import Rule
from harness.registry import Context


@dataclass
class ToolResult:
    status: str = "success"
    output: str = ""
    error: str | None = None
    exit_code: int | None = None
    duration_ms: int = 0
    truncated: bool = False

    def to_message(self) -> dict:
        content = self.output if self.status == "success" else (self.error or self.output)
        return {"role": "tool", "content": content}


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict
    handler: Callable[[dict, Context], ToolResult]


def specs(skills_root: Path) -> list[ToolSpec]:
    root = Path(skills_root)
    return [
        ToolSpec(
            name="list_skills",
            description="列出可用技能",
            parameters={"type": "object", "properties": {}, "required": []},
            handler=partial(_list_skills, root),
        ),
        ToolSpec(
            name="load_skill",
            description="加载技能（声明的规则仅收紧）",
            parameters={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
            handler=partial(_load_skill, root),
        ),
    ]


def _list_skills(root: Path, args: dict, ctx: Context) -> ToolResult:
    names = []
    if root.is_dir():
        for entry in sorted(root.iterdir()):
            if entry.is_dir() and (entry / "SKILL.md").is_file():
                names.append(entry.name)
    output = "\n".join(names) if names else "（无技能）"
    return ToolResult(status="success", output=output)


def _load_skill(root: Path, args: dict, ctx: Context) -> ToolResult:
    name = args.get("name", "")
    if not isinstance(name, str) or not name or name in (".", "..") or "/" in name or "\\" in name or ".." in name:
        return ToolResult(
            status="error",
            error=f"invalid skill name: {name}",
            output=f"跳过技能: 无效技能名 {name}",
        )
    md = root / name / "SKILL.md"
    if not md.is_file():
        return ToolResult(
            status="error",
            error=f"skill not found: {name}",
            output=f"跳过技能: 未找到 {name}",
        )
    try:
        text = md.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return ToolResult(
            status="error",
            error=f"skill parse failed: {name}: {exc}",
            output=f"跳过技能 {name}: 解析失败",
        )
    body, rules = _parse_skill(name, text)
    warnings = []
    if ctx.policy is not None and rules:
        rejected = ctx.policy.add_skill_rules(rules)
        for item in rejected:
            warnings.append(f"警告: allow 声明被拒绝并忽略: {item}")
    output = f"[skill:{name}] {body}"
    if warnings:
        output += "\n" + "\n".join(warnings)
    return ToolResult(status="success", output=output)


def _parse_skill(name: str, text: str) -> tuple[str, list[Rule]]:
    body: list[str] = []
    rules: list[Rule] = []
    in_guardrails = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("##"):
            in_guardrails = stripped.lower().startswith("## guardrails")
            continue
        if in_guardrails:
            rule = _parse_rule_line(name, stripped)
            if rule is not None:
                rules.append(rule)
        else:
            body.append(line)
    return "\n".join(body).strip(), rules


def _parse_rule_line(name: str, line: str) -> Rule | None:
    line = line.split("#", 1)[0].strip()
    if not line:
        return None
    for arrow in ("→", "->"):
        if arrow in line:
            pattern, _, action = line.partition(arrow)
            break
    else:
        return None
    pattern = pattern.strip()
    action = action.strip()
    if not pattern or action not in ("ask", "deny", "allow"):
        return None
    return Rule(pattern, action, f"skill:{name}")
