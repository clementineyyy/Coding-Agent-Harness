from harness.registry import Context, make_registry
from harness.tools.notes import spec as notes_spec
from harness.config import Config
from harness.sandbox import LocalSandbox


def ctx(ws):
    return Context(workspace=ws, sandbox=LocalSandbox(), hooks=None, policy=None,
                   state=None, memory=None, config=Config(workspace=ws))


def test_notes_append_and_list(tmp_path):
    reg = make_registry([notes_spec()])
    assert reg["notes_append"].handler({"text": "第一条"}, ctx(tmp_path)).status == "success"
    reg["notes_append"].handler({"text": "第二条"}, ctx(tmp_path))
    r = reg["notes_list"].handler({}, ctx(tmp_path))
    assert "第一条" in r.output and "第二条" in r.output


def test_notes_append_unwritable_returns_error(tmp_path):
    blocker = tmp_path / "block"
    blocker.write_text("x")
    reg = make_registry([notes_spec()])
    r = reg["notes_append"].handler({"text": "x"}, ctx(blocker))
    assert r.status == "error"
