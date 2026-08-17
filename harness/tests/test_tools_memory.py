from harness.config import Config
from harness.memory import MemoryStore
from harness.registry import Context, make_registry
from harness.sandbox import LocalSandbox
from harness.tools.memory import specs as memory_specs


def ctx(ws, memory):
    return Context(workspace=ws, sandbox=LocalSandbox(), hooks=None, policy=None,
                   state=None, memory=memory, config=Config(workspace=ws))


def test_save_then_search(tmp_path):
    m = MemoryStore(tmp_path)
    reg = make_registry(memory_specs(m))
    reg["memory_save"].handler({"title": "约定", "content": "禁止生产库写操作"}, ctx(tmp_path, m))
    r = reg["memory_search"].handler({"query": "生产库", "k": 1}, ctx(tmp_path, m))
    assert r.status == "success" and "禁止生产库写操作" in r.output


def test_search_defaults_k_to_three(tmp_path):
    m = MemoryStore(tmp_path)
    reg = make_registry(memory_specs(m))
    for i in range(5):
        reg["memory_save"].handler({"title": f"note-{i}", "content": f"生产库{i}"}, ctx(tmp_path, m))
    r = reg["memory_search"].handler({"query": "生产库"}, ctx(tmp_path, m))
    assert r.status == "success"
    assert r.output.count("[note-") == 3


def test_save_without_context_store_returns_error(tmp_path):
    reg = make_registry(memory_specs(MemoryStore(tmp_path)))
    r = reg["memory_save"].handler({"title": "t", "content": "c"}, ctx(tmp_path, None))
    assert r.status == "error" and "memory" in r.error


def test_search_without_context_store_returns_error(tmp_path):
    reg = make_registry(memory_specs(MemoryStore(tmp_path)))
    r = reg["memory_search"].handler({"query": "x"}, ctx(tmp_path, None))
    assert r.status == "error" and "memory" in r.error


def test_save_failure_returns_error_not_crash(tmp_path):
    blocked = tmp_path / "blocked"
    blocked.write_text("x", encoding="utf-8")
    m = MemoryStore(blocked)
    reg = make_registry(memory_specs(m))
    r = reg["memory_save"].handler({"title": "t", "content": "c"}, ctx(tmp_path, m))
    assert r.status == "error"


def test_search_surfaces_store_warnings(tmp_path):
    (tmp_path / "broken.md").write_bytes(b"\xff\xfe")
    m = MemoryStore(tmp_path)
    m.load()
    reg = make_registry(memory_specs(m))
    r = reg["memory_search"].handler({"query": "生产库"}, ctx(tmp_path, m))
    assert r.status == "success" and "broken.md" in r.output
