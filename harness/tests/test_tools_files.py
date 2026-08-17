from pathlib import Path

from harness.registry import Context, make_registry
from harness.tools.files import spec as files_spec
from harness.tools.search import spec as search_spec
from harness.config import Config
from harness.sandbox import LocalSandbox


def ctx(ws):
    return Context(workspace=ws, sandbox=LocalSandbox(), hooks=None, policy=None,
                   state=None, memory=None, config=Config(workspace=ws))


def test_write_and_read(tmp_path):
    reg = make_registry([files_spec()])
    r = reg["write_file"].handler({"path": "a.txt", "content": "hi"}, ctx(tmp_path))
    assert r.status == "success"
    r2 = reg["read_file"].handler({"path": "a.txt"}, ctx(tmp_path))
    assert "hi" in r2.output


def test_dotdot_escape_denied(tmp_path):
    reg = make_registry([files_spec()])
    r = reg["write_file"].handler({"path": "../evil.txt", "content": "x"}, ctx(tmp_path))
    assert r.status == "error" and "outside workspace" in r.error


def test_symlink_escape_denied(tmp_path):
    outside = tmp_path.parent / "secret.txt"; outside.write_text("secret", encoding="utf-8")
    link = tmp_path / "link"
    try:
        link.symlink_to(outside)
    except OSError:
        return  # Windows 无权限时跳过
    reg = make_registry([files_spec()])
    r = reg["read_file"].handler({"path": "link"}, ctx(tmp_path))
    assert r.status == "error"


def test_list_within_workspace(tmp_path):
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    reg = make_registry([files_spec()])
    r = reg["list"].handler({}, ctx(tmp_path))
    assert r.status == "success" and "a.txt" in r.output


def test_grep_within_workspace(tmp_path):
    (tmp_path / "x.py").write_text("def foo():\n    pass\n", encoding="utf-8")
    reg = make_registry([search_spec()])
    r = reg["grep"].handler({"pattern": "def foo", "path": "."}, ctx(tmp_path))
    assert r.status == "success" and "x.py" in r.output
