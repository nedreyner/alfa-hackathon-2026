"""Извлечение фактов, прогнозов и позиций банка со страницы (docs/06-ingestion-search.md §11.4)."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from alfa_insight.llm.fake import fake_handler
from alfa_insight.llm.types import LLMRequest
from alfa_insight.reference.taxonomy import Taxonomy
from alfa_insight.text.numbers import extract_numbers

MIN_PAGE_CHARS = 200


class ResearchItemOut(BaseModel):
    chunk_no: int
    kind: Literal["fact", "forecast", "position"]
    statement: str = Field(max_length=300)
    indicator: str | None = None
    value: str | None = None
    unit: str | None = None
    period: str | None = None
    industries: list[str] = Field(default_factory=list, max_length=5)
    factors: list[str] = Field(default_factory=list, max_length=5)
    confidence: float = Field(ge=0, le=1)


class ResearchExtraction(BaseModel):
    """Сведения со страницы отчёта."""

    page_summary: str = Field(max_length=300)
    items: list[ResearchItemOut] = Field(default_factory=list, max_length=12)


class VisionDataPoint(BaseModel):
    label: str
    value: str
    unit: str | None = None
    period: str | None = None


class VisionFigure(BaseModel):
    kind: Literal["chart", "table", "other"]
    title: str | None = None
    description: str = Field(max_length=600)
    data_points: list[VisionDataPoint] = Field(default_factory=list, max_length=12)


class VisionOutput(BaseModel):
    """Графики и таблицы страницы."""

    figures: list[VisionFigure] = Field(default_factory=list, max_length=6)


MIN_STATEMENT_WORDS = 5
MIN_LETTER_SHARE = 0.55


def is_meaningful_statement(text: str) -> bool:
    """Отсекает мусор OCR: подписи осей, столбцы чисел, шапки таблиц — это не тезисы аналитиков."""
    t = text.strip()
    if not t or t.startswith(("|", "-", "•")) or t.count("\n") > 2 or t.count("|") >= 2:
        return False
    letters = sum(ch.isalpha() for ch in t)
    words = [w for w in re.findall(r"[^\W\d_]{2,}", t)]
    return len(words) >= MIN_STATEMENT_WORDS and letters / max(1, len(t.replace(" ", ""))) >= MIN_LETTER_SHARE


def postprocess_items(out: ResearchExtraction, chunk_nos: set[int], tax: Taxonomy) -> list[dict[str, Any]]:
    items = []
    for it in out.items:
        if it.chunk_no not in chunk_nos or not is_meaningful_statement(it.statement):
            continue
        d = it.model_dump()
        d["industries"] = [i for i in it.industries if i in tax.industries and i != "unknown"]
        d["factors"] = [f for f in it.factors if f in tax.factors]
        items.append(d)
    return items


_FORECAST = re.compile(r"ожида|прогноз|полага|считаем|оцениваем|вероятн|риски смещ", re.I)
_CHUNK = re.compile(
    r"Фрагмент chunk_no=(\d+)[^\n]*:\n<untrusted_document[^>]*>\n?(.*?)\n?</untrusted_document>", re.S
)


@fake_handler("research_extract")
def fake_research_extract(req: LLMRequest, payload: dict[str, Any]) -> dict[str, Any]:
    user = next((m.text() for m in reversed(req.messages) if m.role == "user"), "")
    items: list[dict[str, Any]] = []
    summary = ""
    for chunk_no, text in _CHUNK.findall(user):
        for sent in re.split(r"(?<=[.!?])\s+", text):
            sent = sent.strip()
            if len(sent) < 30:
                continue
            summary = summary or sent[:280]
            if _FORECAST.search(sent):
                kind = "forecast" if extract_numbers(sent) else "position"
            elif extract_numbers(sent):
                kind = "fact"
            else:
                continue
            items.append(
                {"chunk_no": int(chunk_no), "kind": kind, "statement": sent[:300], "confidence": 0.7}
            )
            if len(items) >= 12:
                break
    return ResearchExtraction(page_summary=summary or "fake: страница", items=items[:12]).model_dump()  # type: ignore[arg-type]


@fake_handler("ocr")
def fake_ocr(req: LLMRequest, payload: dict[str, Any]) -> dict[str, Any] | None:
    from alfa_insight.llm.fake import FakeReply

    return FakeReply(content="# fake: распознавание недоступно\nТекст страницы недоступен в режиме fake.")  # type: ignore[return-value]
