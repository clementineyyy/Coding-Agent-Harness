from dataclasses import is_dataclass
from pathlib import Path

import pytest

from harness.config import Config
from harness.registry import (
    REGISTRY,
    Context,
    Tool,
    build_request_tools,
    make_registry,
    validate_args,
)

TOOL_NAMES = {
    "bash",
    "files",
    "search",
    "web",
    "notes",
    "memory_save",
    "memory_search",
    "run_subagent",
    "ask_user",
    "list_skills",
    "load_skill",
}


def test_registry_covers_all_9_tool_families():
    assert set(REGISTRY) == TOOL_NAMES


def test_tool_is_dataclass_with_spec_fields():
    tool = Tool(
        name="bash",
        description="exec",
        parameters={"type": "object", "properties": {}},
    )
    assert is_dataclass(tool)
    assert tool.name == "bash"
    assert tool.description == "exec"
    assert tool.parameters == {"type": "object", "properties": {}}
    assert tool.requires_approval is False
    assert tool.needs_sandbox is False
    assert tool.uses_workspace is False


def test_bash_declared_with_command_and_timeout():
    tool = REGISTRY["bash"]
    props = tool.parameters["properties"]
    assert tool.requires_approval is True
    assert tool.needs_sandbox is True
    assert props["command"]["type"] == "string"
    assert "command" in tool.parameters["required"]
    assert props["timeout"]["type"] == "integer"


def test_files_and_search_bound_to_workspace():
    files = REGISTRY["files"]
    search = REGISTRY["search"]
    assert files.uses_workspace is True
    assert search.uses_workspace is True
    assert files.needs_sandbox is False
    assert "path" in files.parameters["required"]
    assert "pattern" in search.parameters["required"]


def test_ask_user_and_skills_need_no_approval():
    assert REGISTRY["ask_user"].requires_approval is False
    assert REGISTRY["list_skills"].requires_approval is False
    assert REGISTRY["load_skill"].requires_approval is False


def test_make_registry_duplicate_name_raises():
    spec = Tool(
        name="dup",
        description="x",
        parameters={"type": "object", "properties": {}},
    )
    with pytest.raises(ValueError, match="dup"):
        make_registry([spec, spec])


def test_make_registry_builds_name_lookup():
    spec = Tool(
        name="alpha",
        description="x",
        parameters={"type": "object", "properties": {}},
    )
    reg = make_registry([spec])
    assert set(reg) == {"alpha"}
    assert reg["alpha"] is spec


def test_validate_missing_required():
    err = validate_args(REGISTRY["bash"].parameters, {})
    assert err is not None and "command" in err


def test_validate_wrong_type():
    err = validate_args(REGISTRY["bash"].parameters, {"command": 42})
    assert err is not None and "command" in err


def test_validate_unknown_parameter():
    err = validate_args(REGISTRY["bash"].parameters, {"command": "ls", "evil": 1})
    assert err is not None and "evil" in err


def test_validate_over_limit():
    err = validate_args(REGISTRY["memory_search"].parameters, {"query": "x", "k": 100})
    assert err is not None and "k" in err
    assert validate_args(REGISTRY["memory_search"].parameters, {"query": "x", "k": 5}) is None


def test_validate_path_inside_workspace(tmp_path):
    err = validate_args(
        REGISTRY["files"].parameters,
        {"path": "sub/dir/a.txt"},
        workspace=tmp_path,
    )
    assert err is None


def test_validate_path_dotdot_escape_rejected(tmp_path):
    err = validate_args(
        REGISTRY["files"].parameters,
        {"path": "../outside.txt"},
        workspace=tmp_path,
    )
    assert err is not None and "workspace" in err


def test_validate_absolute_path_outside_workspace_rejected(tmp_path):
    outside = tmp_path.parent / "outside.txt"
    err = validate_args(
        REGISTRY["files"].parameters,
        {"path": str(outside)},
        workspace=tmp_path,
    )
    assert err is not None and "workspace" in err


def test_validate_valid_args_returns_none():
    assert validate_args(REGISTRY["bash"].parameters, {"command": "echo hi"}) is None


def test_build_request_tools_openai_format():
    tools = build_request_tools(REGISTRY)
    assert len(tools) == len(REGISTRY)
    by_name = {t["function"]["name"]: t for t in tools}
    for name in TOOL_NAMES:
        entry = by_name[name]
        assert entry["type"] == "function"
        assert entry["function"]["description"] == REGISTRY[name].description
        assert entry["function"]["parameters"] == REGISTRY[name].parameters


def test_context_constructible(tmp_path):
    ctx = Context(
        workspace=tmp_path,
        sandbox=object(),
        hooks=None,
        policy=None,
        state=None,
        memory=None,
        config=Config(workspace=tmp_path, tool_timeout=1),
    )
    assert ctx.workspace == tmp_path
    assert ctx.config.tool_timeout == 1
