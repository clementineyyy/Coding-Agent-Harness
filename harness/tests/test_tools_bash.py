from harness.config import Config
from harness.registry import Context, make_registry
from harness.sandbox import LocalSandbox
from harness.tools.bash import spec as bash_spec


def make_ctx(tmp_path, tool_timeout=5, network_enabled=False):
    sb = LocalSandbox(network_enabled=network_enabled)
    return Context(
        workspace=tmp_path,
        sandbox=sb,
        hooks=None,
        policy=None,
        state=None,
        memory=None,
        config=Config(workspace=tmp_path, tool_timeout=tool_timeout),
    )


def run_bash(tmp_path, command, tool_timeout=5, network_enabled=False):
    reg = make_registry([bash_spec()])
    return reg["bash"].handler({"command": command}, make_ctx(tmp_path, tool_timeout, network_enabled))


def test_bash_tool_runs(tmp_path):
    r = run_bash(tmp_path, "echo tool-ok")
    assert r.status == "success" and "tool-ok" in r.output


def test_bash_tool_timeout(tmp_path):
    r = run_bash(tmp_path, "python -c \"import time; time.sleep(10)\"", tool_timeout=1)
    assert r.status == "timeout"


def test_bash_tool_error_exit_code(tmp_path):
    r = run_bash(tmp_path, "exit 3")
    assert r.status == "error" and r.exit_code == 3


def test_bash_tool_network_note_when_disabled(tmp_path):
    r = run_bash(tmp_path, "echo net-check")
    assert r.status == "success"
    assert "network_enabled=False" in r.output


def test_bash_tool_no_network_note_when_enabled(tmp_path):
    r = run_bash(tmp_path, "echo net-check", network_enabled=True)
    assert r.status == "success"
    assert "network_enabled" not in r.output
