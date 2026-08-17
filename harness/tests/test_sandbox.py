from pathlib import Path
from subprocess import TimeoutExpired
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from harness.sandbox import DockerSandbox, DockerUnavailableError, LocalSandbox


def test_run_success():
    r = LocalSandbox().run("echo hello", timeout=5)
    assert r.exit_code == 0 and "hello" in r.stdout


def test_run_failure_exit_code():
    r = LocalSandbox().run("exit 3", timeout=5)
    assert r.exit_code == 3


def test_timeout_kills(tmp_path):
    r = LocalSandbox().run("python -c \"import time; time.sleep(10)\"", timeout=1)
    assert r.exit_code != 0 and "timeout" in r.stderr.lower()


def test_output_truncation():
    sb = LocalSandbox(max_output_bytes=16)
    r = sb.run("python -c \"print('x'*100)\"", timeout=5)
    assert r.truncated and len(r.stdout) <= 16 + len("[...truncated]")


def test_docker_missing_cli_errors(tmp_path):
    sb = DockerSandbox(workspace=tmp_path)
    with patch("shutil.which", return_value=None):
        with pytest.raises(DockerUnavailableError):
            sb.run("echo hi", timeout=5)


def test_docker_command_build(tmp_path):
    sb = DockerSandbox(workspace=tmp_path, image="python:3.11-slim")
    with patch("harness.sandbox.subprocess.run") as m:
        m.return_value = SimpleNamespace(stdout="ok", stderr="", returncode=0)
        r = sb.run("echo hi", timeout=5)
    argv = m.call_args.args[0]
    assert "--network=none" in argv and f"{tmp_path}:/workspace" in " ".join(argv)
    assert r.exit_code == 0 and "ok" in r.stdout


def test_docker_cidfile_does_not_preexist(tmp_path):
    """docker 要求 --cidfile 指向不存在的文件（否则 exit 125 "container ID file found"）。"""
    sb = DockerSandbox(workspace=tmp_path)
    with patch("harness.sandbox.subprocess.run") as m:
        m.return_value = SimpleNamespace(stdout="ok", stderr="", returncode=0)
        sb.run("echo hi", timeout=5)
    argv = m.call_args.args[0]
    cidfile = Path(argv[argv.index("--cidfile") + 1])
    assert not cidfile.exists()


def test_docker_network_enabled_omits_flag(tmp_path):
    sb = DockerSandbox(workspace=tmp_path, network_enabled=True)
    with patch("harness.sandbox.subprocess.run") as m:
        m.return_value = SimpleNamespace(stdout="ok", stderr="", returncode=0)
        sb.run("echo hi", timeout=5)
    argv = m.call_args.args[0]
    assert "--network=none" not in argv


def test_docker_output_truncation(tmp_path):
    sb = DockerSandbox(workspace=tmp_path, max_output_bytes=16)
    with patch("harness.sandbox.subprocess.run") as m:
        m.return_value = SimpleNamespace(stdout="x" * 100, stderr="", returncode=0)
        r = sb.run("echo hi", timeout=5)
    assert r.truncated and len(r.stdout) <= 16 + len("[...truncated]")


def test_docker_timeout_stops_container(tmp_path):
    sb = DockerSandbox(workspace=tmp_path)
    with patch("harness.sandbox.subprocess.run") as m:
        def fake_run(argv, **kwargs):
            if argv[1] == "run":
                cidfile = Path(argv[argv.index("--cidfile") + 1])
                cidfile.write_text("fakecontainer", encoding="utf-8")
                raise TimeoutExpired(argv, timeout=kwargs.get("timeout", 1))
            return SimpleNamespace(stdout="", stderr="", returncode=0)
        m.side_effect = fake_run
        r = sb.run("echo hi", timeout=1)
    assert r.exit_code == -1 and "timeout" in r.stderr.lower()
    assert any(args.args[0][1] == "stop" for args in m.call_args_list)


def test_cancel_records_and_idempotent():
    for sb in (LocalSandbox(), DockerSandbox(workspace=Path("."))):
        sb.cancel("call-1")
        sb.cancel("call-1")
        assert "call-1" in sb.cancelled
