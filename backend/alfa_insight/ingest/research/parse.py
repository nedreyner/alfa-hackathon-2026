"""Разбор PDF аналитики (docs/06-ingestion-search.md §11.2): текстовый слой pdfplumber или распознавание.

PDF кейса — сканы без текстового слоя (по одной картинке на страницу, проверено 24.10.2026). Такие страницы
рендерятся pypdfium2 в JPEG и распознаются моделью Qwen3-VL (задача `ocr`). Результат кешируется на диске
по sha256 документа, повторного распознавания нет.
"""

from __future__ import annotations

import base64
import hashlib
import io
import re
import statistics
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber
import pypdfium2 as pdfium

OCR_DPI = 150
OCR_JPEG_QUALITY = 85
MIN_TEXT_CHARS = 400
HEADING_RATIO = 1.2
HEADING_MAX_LEN = 120

OcrFn = Callable[[int, str], Awaitable[str]]  # (номер страницы, data-URL картинки) → markdown


@dataclass
class ParsedPage:
    page: int
    text: str
    tables: list[str] = field(default_factory=list)
    headings: list[str] = field(default_factory=list)
    heading: str | None = None  # текущий раздел документа к концу страницы
    ocr: bool = False
    n_chars: int = 0
    n_images: int = 0
    n_drawings: int = 0


@dataclass
class ParsedDoc:
    path: Path
    sha256: str
    pages: list[ParsedPage]
    title: str | None
    created: str | None


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def table_to_markdown(rows: list[list[str | None]]) -> str:
    clean = [[(c or "").replace("\n", " ").strip() for c in r] for r in rows if any(c for c in r)]
    if not clean:
        return ""
    width = max(len(r) for r in clean)
    clean = [r + [""] * (width - len(r)) for r in clean]
    lines = ["| " + " | ".join(clean[0]) + " |", "| " + " | ".join("---" for _ in range(width)) + " |"]
    lines += ["| " + " | ".join(r) + " |" for r in clean[1:]]
    return "\n".join(lines)


def render_page_jpeg(path: Path, page_no: int, dpi: int = OCR_DPI) -> str:
    pdf = pdfium.PdfDocument(str(path))
    try:
        image = pdf[page_no - 1].render(scale=dpi / 72).to_pil().convert("RGB")
    finally:
        pdf.close()
    buf = io.BytesIO()
    image.save(buf, "JPEG", quality=OCR_JPEG_QUALITY)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


_MD_TABLE_LINE = re.compile(r"^\s*\|.*\|\s*$")


def split_markdown(md: str) -> tuple[str, list[str], list[str]]:
    """Текст распознанной страницы → (текст без таблиц, таблицы, заголовки)."""
    text_lines: list[str] = []
    tables: list[str] = []
    headings: list[str] = []
    current: list[str] = []
    for line in md.splitlines():
        if _MD_TABLE_LINE.match(line):
            current.append(line.strip())
            continue
        if current:
            tables.append("\n".join(current))
            current = []
        stripped = line.strip()
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            if title:
                headings.append(title)
                text_lines.append(title)
            continue
        text_lines.append(line.rstrip())
    if current:
        tables.append("\n".join(current))
    return "\n".join(text_lines).strip(), tables, headings


async def parse_pdf(path: Path, *, ocr: OcrFn | None = None, ocr_cache_dir: Path | None = None) -> ParsedDoc:
    sha = sha256_file(path)
    pages: list[ParsedPage] = []
    heading: str | None = None
    with pdfplumber.open(str(path)) as pdf:
        meta = pdf.metadata or {}
        sizes = [c["size"] for p in pdf.pages for c in p.chars] or [0.0]
        median = statistics.median(sizes)
        for idx, page in enumerate(pdf.pages, 1):
            text = page.extract_text() or ""
            n_chars = len(page.chars)
            parsed = ParsedPage(
                page=idx,
                text=text,
                n_chars=n_chars,
                n_images=len(page.images),
                n_drawings=len(page.curves) + len(page.rects),
            )
            if n_chars >= MIN_TEXT_CHARS or ocr is None:
                parsed.tables = [md for md in (table_to_markdown(t) for t in page.extract_tables()) if md]
                for line in page.extract_text_lines() if n_chars else []:
                    chars = line.get("chars") or []
                    if chars and median and len(line["text"]) < HEADING_MAX_LEN:
                        avg = sum(c["size"] for c in chars) / len(chars)
                        if avg >= HEADING_RATIO * median:
                            parsed.headings.append(line["text"].strip())
            else:
                cache = ocr_cache_dir / sha / f"p{idx}.md" if ocr_cache_dir else None
                if cache is not None and cache.exists():
                    md = cache.read_text(encoding="utf-8")
                else:
                    md = await ocr(idx, render_page_jpeg(path, idx))
                    if cache is not None:
                        cache.parent.mkdir(parents=True, exist_ok=True)
                        cache.write_text(md, encoding="utf-8")
                parsed.text, parsed.tables, parsed.headings = split_markdown(md)
                parsed.ocr = True
            if parsed.headings:
                heading = parsed.headings[-1]
            parsed.heading = heading
            pages.append(parsed)
    return ParsedDoc(
        path=path,
        sha256=sha,
        pages=pages,
        title=(meta.get("Title") or None),
        created=(meta.get("CreationDate") or None),
    )
