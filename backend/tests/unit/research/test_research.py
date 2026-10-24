from __future__ import annotations

from pathlib import Path

import pytest
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from alfa_insight.appctx import build_context
from alfa_insight.ingest.research.chunk import chunk_text
from alfa_insight.ingest.research.parse import split_markdown
from alfa_insight.ingest.research.pipeline import date_from_name, date_from_text, ingest_research, slugify
from alfa_insight.llm import build_router
from alfa_insight.llm.fake import FakeBackend
from alfa_insight.settings import Settings
from alfa_insight.store.research import ResearchStore

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
]
PARA = (
    "Мы ожидаем сохранения ключевой ставки на уровне 14,0% до конца года. Инфляция в сентябре составила 7,8% г/г. "
    "Корпоративное кредитование растёт быстрее прогнозов ЦБ РФ. Бюджетный дефицит остаётся высоким. "
)


def _font() -> str:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            pdfmetrics.registerFont(TTFont("DejaVu", path))
            return "DejaVu"
    pytest.skip("нет TTF-шрифта с кириллицей")


def make_pdf(path: Path, extra: str = "") -> None:
    font = _font()
    c = canvas.Canvas(str(path), pagesize=A4)
    for page in range(2):
        y = 800
        c.setFont(font, 20)
        c.drawString(50, y, f"Ключевая ставка ЦБ РФ — раздел {page + 1}")
        c.setFont(font, 10)
        y -= 30
        for line_no in range(14):
            text = (PARA + extra)[line_no * 7 % 60 :][:95] if line_no % 2 else PARA[:95]
            c.drawString(50, y, f"{line_no + 1}. {text}")
            y -= 14
        if page == 1:
            y -= 20
            rows = [
                ["Показатель", "2025", "2026П"],
                ["Ставка, %", "16,0", "14,0"],
                ["Инфляция, %", "5,6", "6,1"],
            ]
            for r, row in enumerate(rows):
                for col, cell in enumerate(row):
                    c.rect(50 + col * 120, y - r * 20, 120, 20)
                    c.drawString(55 + col * 120, y - r * 20 + 6, cell)
        c.showPage()
    c.save()


def test_helpers() -> None:
    assert slugify("FI_Strategy_3Q26_22072026.pdf") == "fi-strategy-3q26-22072026"
    assert slugify("Бонд_Бриф.pdf") == "bond-brif"
    assert date_from_name("Bond_Brief_14092026.pdf") == "2026-09-14"
    assert date_from_name("alfa_macro_2026_09.pdf") == "2026-09-01"
    assert date_from_text("Центр анализа\n11 сентября 2026 г.\nКлючевая ставка") == "2026-09-11"
    text, tables, heads = split_markdown(
        "# Заголовок\nТекст абзаца.\n| a | b |\n| --- | --- |\n| 1 | 2 |\nЕщё текст"
    )
    assert heads == ["Заголовок"] and len(tables) == 1 and "Ещё текст" in text and "|" not in text
    chunks = chunk_text("\n\n".join([PARA * 2] * 5))
    assert all(len(c) <= 1200 for c in chunks) and all(c.rstrip().endswith((".", "!", "?")) for c in chunks)
    assert len(chunks) >= 3


@pytest.fixture
def ctx(settings: Settings):  # type: ignore[no-untyped-def]
    c = build_context(settings)
    c.set_router(build_router(settings, c.db, backend=FakeBackend()))
    return c


async def test_ingest_pdf_fixture(ctx, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    d = tmp_path / "research"
    d.mkdir()
    make_pdf(d / "alfa_rate_2026_09.pdf")
    stats = await ingest_research(ctx, d)
    assert stats.docs_processed == 1 and stats.pages_ocr == 0
    store = ResearchStore(ctx.db)
    doc = store.doc_by_slug("alfa-rate-2026-09")
    assert doc and doc["status"] == "extracted" and doc["pages"] == 2 and doc["published_at"] == "2026-09-01"
    chunks = store.chunks(doc["id"])
    assert chunks[0]["source_id"] == "alfa:alfa-rate-2026-09:p1:c1"
    assert chunks[0]["heading"] and "Ключевая ставка" in chunks[0]["heading"]
    assert any(c["kind"] == "table" and "Инфляция" in c["text"] for c in chunks if c["page"] == 2)
    assert stats.items > 0 and store.counts()["research_items"] == stats.items
    assert ctx.db.scalar("SELECT count(*) FROM research_fts WHERE research_fts MATCH 'ставка'") >= 1
    again = await ingest_research(ctx, d)
    assert again.docs_skipped == 1 and again.docs_processed == 0
    make_pdf(d / "alfa_rate_2026_09.pdf", extra=" Новая оценка рисков.")
    changed = await ingest_research(ctx, d)
    assert changed.docs_processed == 1
    assert store.counts()["research_docs"] == 1


def test_meaningful_statement_filter() -> None:
    from alfa_insight.ingest.research.extract import is_meaningful_statement

    assert is_meaningful_statement("Мы повышаем наш прогноз по инфляции по итогам 2026 г. до 7,5% г/г.")
    assert not is_meaningful_statement("| Выпуск | Рейтинг (Акра/Эксперт РА/ НКР) | Цена на 20.07.2026 г. |")
    assert not is_meaningful_statement("2,500\n3,000\n3,500\n4,000\n4,500")
    assert not is_meaningful_statement("- 36%\n- 17%\n- 8%")
