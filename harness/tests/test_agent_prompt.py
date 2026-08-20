import sys

from harness.agent import build_system_prompt
from harness.config import Config
from harness.tools.bash import spec as bash_spec


def test_system_prompt_includes_environment(tmp_path):
    prompt = build_system_prompt(Config(workspace=tmp_path))
    assert sys.platform in prompt
    assert "workspace" in prompt.lower() and str(tmp_path) in prompt
    assert f"python {sys.version_info.major}.{sys.version_info.minor}" in prompt.lower()


def test_system_prompt_orders_execution_before_advice(tmp_path):
    prompt = build_system_prompt(Config(workspace=tmp_path))
    assert "工具" in prompt and "执行" in prompt
    assert "建议" not in prompt or prompt.index("执行") < prompt.index("建议")


def test_bash_tool_description_mentions_arbitrary_commands():
    spec = bash_spec()
    assert "任意" in spec.description or "shell" in spec.description
    assert "查询" in spec.description or "系统" in spec.description