import subprocess, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KEY_PATTERN = re.compile(r"sk-[A-Za-z0-9]{16,}")
EXCLUDE = {"test_security_scan.py"}  # 白名单：测试自身

def test_no_key_shaped_strings_in_source():
    hits = []
    for p in (ROOT / "harness").rglob("*.py"):
        if p.name in EXCLUDE: continue
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if KEY_PATTERN.search(line): hits.append(f"{p}:{i}")
    assert hits == []

def test_no_key_in_git_history():
    r = subprocess.run(["git", "-C", str(ROOT), "log", "-p"], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    assert r.stdout is not None
    assert not KEY_PATTERN.search(r.stdout)

def test_no_key_in_transcripts_or_fixtures():
    hits = []
    for d in [ROOT / "transcripts", ROOT / "harness" / "tests" / "fixtures"]:
        if d.exists():
            for p in d.rglob("*"):
                if p.is_file() and KEY_PATTERN.search(p.read_text(encoding="utf-8", errors="ignore")):
                    hits.append(str(p))
    assert hits == []
