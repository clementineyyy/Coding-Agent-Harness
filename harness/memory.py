from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path

_INVALID_TITLE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_PART_SUFFIX = re.compile(r"-part\d+$", re.IGNORECASE)
_WORD = re.compile(r"[a-zA-Z0-9_]+")
_CJK = re.compile(r"[\u4e00-\u9fff]+")
_PART_LIMIT = 2000


def _ngrams(seq: str) -> list[str]:
    if len(seq) <= 1:
        return [seq]
    return [seq[i : i + 2] for i in range(len(seq) - 1)]


def _tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for word in _WORD.findall(text):
        tokens.extend(_ngrams(word))
    for run in _CJK.findall(text):
        tokens.extend(_ngrams(run))
    return tokens


def _chunk_paragraphs(text: str) -> list[str]:
    text = text.replace("\r\n", "\n")
    return [p.strip() for p in text.split("\n\n") if p.strip()]


def _split_parts(content: str, limit: int = _PART_LIMIT) -> list[str]:
    parts: list[str] = []
    current = ""
    for para in _chunk_paragraphs(content):
        while len(para) > limit:
            if current:
                parts.append(current)
                current = ""
            parts.append(para[:limit])
            para = para[limit:]
        if current and len(current) + 2 + len(para) > limit:
            parts.append(current)
            current = ""
        current = f"{current}\n\n{para}" if current else para
    if current:
        parts.append(current)
    return parts


class MemoryStore:
    def __init__(self, root: Path, top_k: int = 2):
        self.root = Path(root)
        self.top_k = top_k
        self.warnings: list[str] = []
        self._chunks: list[dict] = []
        self._df: Counter[str] = Counter()

    def load(self) -> None:
        self.warnings = []
        self._chunks = []
        self._df = Counter()
        files = sorted(self.root.glob("*.md"))
        for path in files:
            try:
                text = path.read_text(encoding="utf-8-sig")
            except (UnicodeDecodeError, OSError) as exc:
                self.warnings.append(f"skipped corrupted memory file {path}: {exc}")
                continue
            title = _PART_SUFFIX.sub("", path.stem)
            for chunk in _chunk_paragraphs(text):
                tokens = _tokenize(chunk)
                if not tokens:
                    continue
                counter = Counter(tokens)
                self._chunks.append({"title": title, "chunk": chunk, "tokens": counter})
                for token in counter:
                    self._df[token] += 1

    def save(self, title: str, content: str) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        safe = _INVALID_TITLE_CHARS.sub("_", title).strip(" .")
        if len(content) > _PART_LIMIT:
            parts = _split_parts(content)
            for i, part in enumerate(parts, start=1):
                (self.root / f"{safe}-part{i}.md").write_text(
                    part, encoding="utf-8", newline="\n"
                )
            return self.root / f"{safe}-part1.md"
        path = self.root / f"{safe}.md"
        path.write_text(content, encoding="utf-8", newline="\n")
        return path

    def search(self, query: str, k: int | None = None) -> list[dict]:
        try:
            if not query or not self._chunks:
                return []
            query_tokens = Counter(_tokenize(query))
            n = len(self._chunks)
            results = []
            for item in self._chunks:
                total = sum(item["tokens"].values())
                score = 0.0
                for token in query_tokens:
                    df = self._df.get(token, 0)
                    if df == 0:
                        continue
                    tf = item["tokens"].get(token, 0) / total
                    score += tf * math.log(1 + n / df)
                if score > 0:
                    results.append(
                        {"title": item["title"], "chunk": item["chunk"], "score": score}
                    )
            results.sort(key=lambda r: r["score"], reverse=True)
            if k is None:
                return results
            return results[:k]
        except Exception:
            return []

    def top_k_chunks(self, query: str) -> list[dict]:
        return self.search(query, self.top_k)
