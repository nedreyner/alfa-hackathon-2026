"""Чанки страниц аналитики (docs/06-ingestion-search.md §11.3)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from alfa_insight.ingest.research.parse import ParsedPage

MIN_CHUNK = 600
MAX_CHUNK = 1200
_SENTENCE = re.compile(r"(?<=[.!?…])\s+(?=[А-ЯЁA-Z0-9«\"(])")


@dataclass
class Chunk:
    source_id: str
    page: int
    chunk_no: int
    kind: str  # text | table | chart
    heading: str | None
    text: str


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE.split(text) if s.strip()]


def chunk_text(text: str) -> list[str]:
    """Абзацы → чанки 600–1200 символов без разрыва предложений; перекрытие — последнее предложение."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n|\n", text) if p.strip()]
    units: list[str] = []
    for p in paragraphs:
        units.extend([p] if len(p) <= MAX_CHUNK else sentences(p))
    chunks: list[str] = []
    cur: list[str] = []
    fresh = 0  # длина нового (не перекрывающего) текста в текущем чанке

    def flush() -> None:
        nonlocal cur, fresh
        chunks.append("\n".join(cur))
        tail = sentences(cur[-1])[-1] if cur and sentences(cur[-1]) else ""
        cur = [tail] if tail and len(tail) < MIN_CHUNK // 2 else []
        fresh = 0

    for u in units:
        if cur and fresh and len("\n".join([*cur, u])) > MAX_CHUNK:
            flush()
        cur.append(u)
        fresh += len(u)
        if len("\n".join(cur)) >= MIN_CHUNK:
            flush()
    if fresh:
        rest = "\n".join(cur)
        if chunks and len(chunks[-1]) + len(rest) <= MAX_CHUNK and len(rest) < MIN_CHUNK // 2:
            chunks[-1] = chunks[-1] + "\n" + "\n".join(cur[1:] if len(cur) > 1 else cur)
        else:
            chunks.append(rest)
    return chunks


def chunk_page(slug: str, page: ParsedPage) -> list[Chunk]:
    out: list[Chunk] = []
    n = 0
    for text in chunk_text(page.text):
        n += 1
        out.append(Chunk(f"alfa:{slug}:p{page.page}:c{n}", page.page, n, "text", page.heading, text))
    for table in page.tables:
        n += 1
        out.append(Chunk(f"alfa:{slug}:p{page.page}:c{n}", page.page, n, "table", page.heading, table))
    return out
