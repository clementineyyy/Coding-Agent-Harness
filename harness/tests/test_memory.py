import time
from pathlib import Path
from harness.memory import MemoryStore

def test_save_and_search_roundtrip(tmp_path):
    m = MemoryStore(tmp_path)
    m.save("agent-rules", "项目约定：禁止在生产库执行写操作。\n\n所有修改先走 review。")
    m.load()
    res = m.search("生产库写操作", k=1)
    assert res and res[0]["title"] == "agent-rules" and "生产库" in res[0]["chunk"]

def test_top_k_injection(tmp_path):
    m = MemoryStore(tmp_path, top_k=2)
    m.save("a", "x" * 60); m.save("b", "x" * 60); m.save("c", "y" * 60)
    m.load()
    hits = m.top_k_chunks("xxx")
    assert len(hits) == 2 and all(h["score"] > 0 for h in hits)

def test_corrupted_file_skipped(tmp_path):
    (tmp_path / "broken.md").write_bytes(b"\xff\xfe\x00\x01")
    (tmp_path / "good.md").write_text("hello world\n", encoding="utf-8")
    m = MemoryStore(tmp_path); m.load()
    assert len(m.warnings) == 1
    assert m.search("hello", k=1)[0]["title"] == "good"

def test_retrieval_perf_smoke(tmp_path):
    m = MemoryStore(tmp_path)
    for i in range(100):
        m.save(f"note-{i}", f"内容 {i} " * 30)
    m.load()
    t0 = time.monotonic()
    m.search("内容 50", k=5)
    assert time.monotonic() - t0 < 0.05

def test_save_splits_long_content_into_parts(tmp_path):
    m = MemoryStore(tmp_path)
    long_content = "段落甲。" + "x" * 1500 + "\n\n段落乙。" + "y" * 1500
    m.save("big", long_content)
    m.load()
    parts = sorted(p.name for p in tmp_path.glob("big-part*.md"))
    assert parts == ["big-part1.md", "big-part2.md"]
    hits = m.search("段落乙", k=1)
    assert hits and hits[0]["title"] == "big"

def test_save_sanitizes_invalid_title_chars(tmp_path):
    m = MemoryStore(tmp_path)
    path = m.save("bad:title?/x", "content here")
    assert path.name == "bad_title__x.md"
    assert (tmp_path / "bad_title__x.md").exists()
