"""`alfa research ingest`: PDF → страницы (текст или распознавание) → чанки → элементы (docs/06 §11)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from alfa_insight.appctx import AppContext
from alfa_insight.errors import BudgetExceeded, LLMError
from alfa_insight.ingest.research.chunk import Chunk, chunk_page
from alfa_insight.ingest.research.extract import (
    MIN_PAGE_CHARS,
    ResearchExtraction,
    VisionFigure,
    VisionOutput,
    postprocess_items,
)
from alfa_insight.ingest.research.parse import ParsedDoc, ParsedPage, parse_pdf, render_page_jpeg, sha256_file
from alfa_insight.ingest.tagging import taxonomy_ctx
from alfa_insight.llm.fake import fake_handler
from alfa_insight.llm.types import ImagePart, LLMRequest, Message, TextPart
from alfa_insight.log import get_logger
from alfa_insight.store.research import ResearchStore
from alfa_insight.text.lemmatizer import lemmas_str

log = get_logger("ingest.research")
MONTHS = {
    "январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5, "июн": 6,
    "июл": 7, "август": 8, "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12,
}  # fmt: skip
_TRANSLIT = str.maketrans(
    "абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
    "abvgdeejziiklmnoprstufhccss_y_eua",
)


@dataclass
class ResearchStats:
    docs_total: int = 0
    docs_processed: int = 0
    docs_skipped: int = 0
    pages_ocr: int = 0
    pages_vision: int = 0
    charts: int = 0
    chunks: int = 0
    items: int = 0
    cost_rub: float = 0.0
    errors: list[str] = field(default_factory=list)


def slugify(name: str) -> str:
    stem = Path(name).stem.lower().translate(_TRANSLIT)
    return re.sub(r"[^a-z0-9]+", "-", stem).strip("-")


def load_meta(*paths: Path) -> dict[str, dict[str, Any]]:
    meta: dict[str, dict[str, Any]] = {}
    for p in paths:
        if p.exists():
            meta.update(yaml.safe_load(p.read_text(encoding="utf-8")) or {})
    return meta


def date_from_text(text: str) -> str | None:
    m = re.search(r"\b(\d{1,2})\s+([а-яё]+)\s+(20\d{2})\s*г?", text.lower())
    if m:
        for stem, month in MONTHS.items():
            if m.group(2).startswith(stem) and (stem != "ма" or m.group(2).startswith(("мая", "май"))):
                try:
                    return date(int(m.group(3)), month, int(m.group(1))).isoformat()
                except ValueError:
                    return None
    return None


def date_from_name(name: str) -> str | None:
    m = re.search(r"(\d{2})(\d{2})(20\d{2})", name)  # 14092026
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
        except ValueError:
            pass
    m = re.search(r"(20\d{2})[-_.](\d{2})(?:[-_.](\d{2}))?", name)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3) or 1)).isoformat()
    return None


def date_from_pdf(created: str | None) -> str | None:
    m = re.match(r"D:(\d{4})(\d{2})(\d{2})", created or "")
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


async def _ocr_page(ctx: AppContext, stats: ResearchStats, title: str, page: int, image_url: str) -> str:
    rendered = ctx.prompts.render("ocr", page=page, doc_title=title)
    system, user = rendered.messages
    req = LLMRequest(
        task="ocr",
        prompt_version=rendered.version,
        messages=[
            system,
            Message(
                role="user", content=[TextPart(text=user.text()), ImagePart(image_url={"url": image_url})]
            ),
        ],
        cache=False,
    )
    res = await ctx.router.complete(req)
    stats.pages_ocr += 1
    stats.cost_rub += res.usage.cost_rub
    return res.content or ""


# Признаки рисунка в распознанном тексте скана: OCR переносит подписи, а точки графика теряются
FIGURE_MARKERS = re.compile(r"\b(рис(унок|\.)|график|диаграмм|источник:|figure|chart)", re.I)
VISION_MAX_CHARS = 400
VISION_MIN_DRAWINGS = 50


def vision_candidate(page: ParsedPage) -> bool:
    """§11.3: векторный график (мало текста, много фигур), страница с картинкой и малым текстом или скан
    с подписью рисунка. Скан — всегда одна картинка, поэтому для сканов нужна подпись: иначе в vision ушли бы
    все страницы."""
    if page.n_chars < VISION_MAX_CHARS and page.n_drawings > VISION_MIN_DRAWINGS:
        return True
    if page.ocr:
        return bool(FIGURE_MARKERS.search(page.text))
    return page.n_chars < VISION_MAX_CHARS and page.n_images > 0


def chart_text(fig: VisionFigure) -> str:
    """Текст чанка `chart`: описание и точки данных строками — так их находит поиск и видит агент."""
    head = f"{fig.title}. " if fig.title else ""
    points = "; ".join(
        f"{p.label}: {p.value}{' ' + p.unit if p.unit else ''}{f' ({p.period})' if p.period else ''}"
        for p in fig.data_points
    )
    return f"{head}{fig.description}" + (f"\nДанные: {points}." if points else "")


async def _vision_page(ctx: AppContext, title: str, page: int, image_url: str) -> tuple[VisionOutput, float]:
    rendered = ctx.prompts.render("vision", page=page, doc_title=title)
    system, user = rendered.messages
    res = await ctx.router.structured(
        task="vision",
        messages=[
            system,
            Message(
                role="user", content=[TextPart(text=user.text()), ImagePart(image_url={"url": image_url})]
            ),
        ],
        schema=VisionOutput,
        prompt_version=rendered.version,
    )
    return res.value, res.raw.usage.cost_rub


async def add_charts(
    ctx: AppContext,
    path: Path,
    doc_id: int,
    slug: str,
    title: str,
    pages: list[ParsedPage],
    stats: ResearchStats,
    *,
    max_cost_rub: float | None,
) -> None:
    """Графики страниц-кандидатов → чанки `kind=chart` (`alfa:{slug}:p{page}:g{n}`); флаг `--vision`."""
    store = ResearchStore(ctx.db)
    for page in pages:
        if not vision_candidate(page):
            continue
        if max_cost_rub is not None and stats.cost_rub >= max_cost_rub:
            raise BudgetExceeded("run", "Достигнут --max-cost")
        out, cost = await _vision_page(ctx, title, page.page, render_page_jpeg(path, page.page))
        stats.cost_rub += cost
        stats.pages_vision += 1
        for n, fig in enumerate((f for f in out.figures if f.kind in ("chart", "table")), 1):
            text = chart_text(fig)
            store.add_chunk(
                doc_id, source_id=f"alfa:{slug}:p{page.page}:g{n}", page=page.page, chunk_no=1000 + n,
                kind="chart", heading=fig.title or page.heading, text=text,
                heading_lemmas=lemmas_str(fig.title or page.heading or ""), text_lemmas=lemmas_str(text),
            )  # fmt: skip
            stats.charts += 1


async def _extract_page(
    ctx: AppContext, title: str, doc_date: str | None, page: int, heading: str | None, chunks: list[Chunk]
) -> tuple[ResearchExtraction, float]:
    rendered = ctx.prompts.render(
        "research_extract",
        doc_title=title,
        doc_date=doc_date,
        page=page,
        heading=heading,
        chunks=chunks,
        **taxonomy_ctx(ctx.taxonomy),
    )
    res = await ctx.router.structured(
        task="research_extract",
        messages=rendered.messages,
        schema=ResearchExtraction,
        prompt_version=rendered.version,
    )
    return res.value, res.raw.usage.cost_rub


async def ingest_doc(
    ctx: AppContext,
    path: Path,
    meta: dict[str, Any],
    stats: ResearchStats,
    *,
    max_cost_rub: float | None,
    vision: bool = False,
) -> None:
    store = ResearchStore(ctx.db)
    slug = slugify(path.name)
    info = meta.get(path.name, {})
    title_hint = info.get("title") or path.stem

    async def ocr(page: int, image_url: str) -> str:
        if max_cost_rub is not None and stats.cost_rub >= max_cost_rub:
            raise BudgetExceeded("run", "Достигнут --max-cost")
        return await _ocr_page(ctx, stats, title_hint, page, image_url)

    doc: ParsedDoc = await parse_pdf(path, ocr=ocr, ocr_cache_dir=ctx.settings.runtime_dir / "research_ocr")
    first = doc.pages[0] if doc.pages else None
    title = (
        info.get("title")
        or (first.headings[0] if first and first.headings else None)
        or doc.title
        or path.stem
    )
    doc_date = (
        info.get("date")
        or date_from_name(path.name)
        or (date_from_text(first.text) if first else None)
        or date_from_pdf(doc.created)
    )
    doc_id = store.create_doc(
        slug=slug,
        title=title,
        published_at=doc_date,
        file_name=path.name,
        sha256=doc.sha256,
        pages=len(doc.pages),
        url=info.get("url"),
    )
    for page in doc.pages:
        chunks = chunk_page(slug, page)
        ids: dict[int, int] = {}
        for ch in chunks:
            ids[ch.chunk_no] = store.add_chunk(
                doc_id,
                source_id=ch.source_id,
                page=ch.page,
                chunk_no=ch.chunk_no,
                kind=ch.kind,
                heading=ch.heading,
                text=ch.text,
                heading_lemmas=lemmas_str(ch.heading or ""),
                text_lemmas=lemmas_str(ch.text),
            )
            stats.chunks += 1
        text_chunks = [c for c in chunks if c.kind in ("text", "table")]
        if sum(len(c.text) for c in text_chunks) < MIN_PAGE_CHARS:
            continue
        if max_cost_rub is not None and stats.cost_rub >= max_cost_rub:
            raise BudgetExceeded("run", "Достигнут --max-cost")
        out, cost = await _extract_page(ctx, title, doc_date, page.page, page.heading, text_chunks)
        stats.cost_rub += cost
        by_chunk: dict[int, list[dict[str, Any]]] = {}
        for item in postprocess_items(out, set(ids), ctx.taxonomy):
            by_chunk.setdefault(item["chunk_no"], []).append(item)
        for chunk_no, items in by_chunk.items():
            store.add_items(ids[chunk_no], items)
            stats.items += len(items)
    if vision:
        await add_charts(ctx, path, doc_id, slug, title, doc.pages, stats, max_cost_rub=max_cost_rub)
    store.set_doc_status(doc_id, "extracted")


async def _cached_only(page: int, image_url: str) -> str:
    """Повторный разбор ради графиков: OCR только из кеша на диске; промах — ошибка, без платного вызова."""
    raise LLMError(f"OCR страницы {page} нет в кеше")


async def ingest_research(
    ctx: AppContext, directory: Path, *, max_cost_rub: float | None = None, vision: bool = False
) -> ResearchStats:
    store = ResearchStore(ctx.db)
    meta = load_meta(ctx.settings.config_path / "research_meta.yaml", directory / "meta.yaml")
    stats = ResearchStats()
    for path in sorted(directory.glob("*.pdf")):
        stats.docs_total += 1
        slug = slugify(path.name)
        existing = store.doc_by_slug(slug)
        sha = sha256_file(path)
        if existing and existing["sha256"] == sha and existing["status"] == "extracted":
            has_charts = any(c["kind"] == "chart" for c in store.chunks(existing["id"]))
            if (
                vision and not has_charts
            ):  # документ уже разобран — только графики (OCR берётся из кеша на диске)
                try:
                    doc = await parse_pdf(
                        path, ocr=_cached_only, ocr_cache_dir=ctx.settings.runtime_dir / "research_ocr"
                    )
                    await add_charts(ctx, path, existing["id"], slug, existing["title"], doc.pages, stats,
                                     max_cost_rub=max_cost_rub)  # fmt: skip
                except BudgetExceeded:
                    break
                except LLMError as exc:
                    stats.errors.append(f"{path.name}: vision {exc.code}")
            stats.docs_skipped += 1
            continue
        if existing:
            store.delete_doc(existing["id"])
        try:
            await ingest_doc(ctx, path, meta, stats, max_cost_rub=max_cost_rub)
            stats.docs_processed += 1
        except BudgetExceeded:
            log.warning("research_budget_stop", doc=path.name)
            failed = store.doc_by_slug(slug)
            if failed:
                store.delete_doc(failed["id"])
            break
        except LLMError as exc:
            stats.errors.append(f"{path.name}: {exc.code}")
            failed = store.doc_by_slug(slug)
            if failed:
                store.set_doc_status(failed["id"], "failed")
    return stats


@fake_handler("vision")
def fake_vision(req: LLMRequest, payload: dict[str, Any]) -> dict[str, Any]:
    """FakeLLM: один график с двумя точками — для офлайн-разработки и тестов."""
    return {
        "figures": [
            {
                "kind": "chart",
                "title": "Ключевая ставка, %",
                "description": "Ключевая ставка снижается с пика прошлого года.",
                "data_points": [
                    {"label": "2025", "value": "16", "unit": "%", "period": "конец года"},
                    {"label": "2026", "value": "14", "unit": "%", "period": "октябрь"},
                ],
            }
        ]
    }
