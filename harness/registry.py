from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from harness.hooks import HookBus
    from harness.llm import LLM
    from harness.memory import MemoryStore
    from harness.policy import Policy
    from harness.sandbox import Sandbox
    from harness.state import StateMachine

_TYPE_MAP: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
    "null": type(None),
}


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    requires_approval: bool = False
    needs_sandbox: bool = False
    uses_workspace: bool = False
    handler: Callable | None = None


@dataclass
class ToolResult:
    status: str
    output: str = ""
    error: str | None = None
    exit_code: int | None = None
    duration_ms: int = 0
    truncated: bool = False


@dataclass
class Context:
    workspace: Path
    sandbox: Sandbox
    hooks: HookBus
    policy: Policy
    state: StateMachine
    memory: MemoryStore
    config: Any
    ask_callback: Callable | None = None
    agent_factory: Callable | None = None
    llm: LLM | None = None


def make_registry(specs: list[Tool]) -> dict[str, Tool]:
    registry: dict[str, Tool] = {}
    for spec in specs:
        subs = spec if isinstance(spec, (list, tuple)) else (spec,)
        for s in subs:
            if s.name in registry:
                raise ValueError(f"duplicate tool name: {s.name}")
            registry[s.name] = s
    return registry


REGISTRY: dict[str, Tool] = make_registry(
    [
        Tool(
            name="bash",
            description="执行 shell 命令：运行构建 / 测试 / lint / 类型检查",
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "timeout": {"type": "integer", "minimum": 1},
                },
                "required": ["command"],
            },
            requires_approval=True,
            needs_sandbox=True,
            uses_workspace=True,
        ),
        Tool(
            name="files",
            description="读写 / 列出工作区文件",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "x-workspace-path": True},
                    "content": {"type": "string"},
                },
                "required": ["path"],
            },
            requires_approval=True,
            needs_sandbox=False,
            uses_workspace=True,
        ),
        Tool(
            name="search",
            description="在工作区内按文件名 / 内容搜索",
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "path": {"type": "string", "x-workspace-path": True},
                },
                "required": ["pattern"],
            },
            requires_approval=True,
            needs_sandbox=False,
            uses_workspace=True,
        ),
        Tool(
            name="web",
            description="抓取 URL 内容（fetch_url）",
            parameters={
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
            requires_approval=True,
            needs_sandbox=False,
            uses_workspace=False,
        ),
        Tool(
            name="notes",
            description="便签追加 / 列出（跨回合临时要点，不写入长期记忆）",
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
            requires_approval=True,
            needs_sandbox=False,
            uses_workspace=False,
        ),
        Tool(
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
            requires_approval=True,
            needs_sandbox=False,
            uses_workspace=False,
        ),
        Tool(
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
            requires_approval=True,
            needs_sandbox=False,
            uses_workspace=False,
        ),
        Tool(
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
        ),
        Tool(
            name="ask_user",
            description="向用户提问，状态机转入 awaiting_user",
            parameters={
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "options": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["question"],
            },
            requires_approval=False,
            needs_sandbox=False,
            uses_workspace=False,
        ),
        Tool(
            name="list_skills",
            description="列出可用技能",
            parameters={"type": "object", "properties": {}, "required": []},
            requires_approval=False,
            needs_sandbox=False,
            uses_workspace=False,
        ),
        Tool(
            name="load_skill",
            description="加载技能（声明的规则仅收紧）",
            parameters={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
            requires_approval=False,
            needs_sandbox=False,
            uses_workspace=False,
        ),
    ]
)


def validate_args(
    schema: dict, args: dict, workspace: Path | None = None
) -> str | None:
    if not isinstance(args, dict):
        return "arguments must be a JSON object"
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    for name in args:
        if name not in properties:
            return f"unknown parameter: {name}"
    for name in required:
        if name not in args:
            return f"missing required parameter: {name}"
    for name, value in args.items():
        prop = properties[name]
        err = _check_type(name, value, prop)
        if err is not None:
            return err
        err = _check_limit(name, value, prop)
        if err is not None:
            return err
        err = _check_path(name, value, prop, workspace)
        if err is not None:
            return err
    return None


def _check_type(name: str, value: Any, prop: dict) -> str | None:
    expected = prop.get("type")
    if not expected:
        return None
    expected_types = expected if isinstance(expected, list) else [expected]
    for t in expected_types:
        allowed = _TYPE_MAP.get(t)
        if allowed is None:
            continue
        if isinstance(value, bool) and t in ("integer", "number"):
            continue
        if isinstance(value, allowed):
            return None
    return f"parameter {name} must be of type {expected}"


def _check_limit(name: str, value: Any, prop: dict) -> str | None:
    if isinstance(value, str):
        max_length = prop.get("maxLength")
        if max_length is not None and len(value) > max_length:
            return f"parameter {name} exceeds limit: max length {max_length}"
    elif isinstance(value, int) and not isinstance(value, bool):
        minimum = prop.get("minimum")
        if minimum is not None and value < minimum:
            return f"parameter {name} exceeds limit: minimum {minimum}"
        maximum = prop.get("maximum")
        if maximum is not None and value > maximum:
            return f"parameter {name} exceeds limit: maximum {maximum}"
    elif isinstance(value, list):
        max_items = prop.get("maxItems")
        if max_items is not None and len(value) > max_items:
            return f"parameter {name} exceeds limit: max items {max_items}"
    return None


def _check_path(
    name: str, value: Any, prop: dict, workspace: Path | None
) -> str | None:
    if not prop.get("x-workspace-path") or workspace is None:
        return None
    if not isinstance(value, str):
        return None
    base = Path(workspace).resolve()
    resolved = (Path(workspace) / value).resolve()
    if not _within_workspace(resolved, base):
        return f"parameter {name}: path outside workspace"
    return None


def _within_workspace(resolved: Path, base: Path) -> bool:
    resolved_s = str(resolved).lower()
    base_s = str(base).lower()
    return resolved_s == base_s or resolved_s.startswith(base_s + os.sep)


def build_request_tools(registry: dict[str, Tool]) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters,
            },
        }
        for spec in registry.values()
    ]
