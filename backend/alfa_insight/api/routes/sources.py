"""Карточка источника (docs/09-api.md §4.7): новость, аналитика банка, данные ЦБ, данные клиента, текст пользователя."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, Depends

from alfa_insight.api.deps import current_session, get_ctx
from alfa_insight.api.schemas import SourceDetail
from alfa_insight.api.session import SessionData
from alfa_insight.appctx import AppContext
from alfa_insight.errors import NotFoundError
from alfa_insight.store.insights import InsightStore
from alfa_insight.store.macro import MacroStore
from alfa_insight.store.news import NewsStore
from alfa_insight.store.research import ResearchStore
from alfa_insight.timeutil import parse_dt

router = APIRouter(tags=["sources"])
NEWS_TEXT_CHARS = 4000


def _client_data(ctx: AppContext, company_id: str, source_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Для срезов закупок и продаж — доли отрасли и крупнейшие контрагенты."""
    parts = source_id.split(":")
    data: dict[str, Any] = dict(payload)
    if len(parts) == 4 and parts[2] in ("supply", "demand"):
        side, industry = parts[2], parts[3]
        p = ctx.profiles.get(company_id)
        mix = p.suppliers_mix if side == "supply" else p.buyers_mix
        data["mix"] = [m.model_dump() for m in mix]
        data["coverage"] = p.coverage.get(side, 0.0)  # type: ignore[call-overload]
        direction: Literal["suppliers", "buyers"] = "suppliers" if side == "supply" else "buyers"
        data["counterparties"] = [
            c.model_dump()
            for c in ctx.counterparties.top(
                company_id, direction, None if industry == "all" else industry, 10
            )
        ]
    return data


def build_source(ctx: AppContext, source_id: str, company_id: str) -> SourceDetail:
    src = InsightStore(ctx.db).source(source_id, company_id=company_id)
    if src is None:
        raise NotFoundError("Источник не найден", {"source_id": source_id})
    text: str | None = None
    doc_title: str | None = None
    page: int | None = None
    data: dict[str, Any] | None = None
    _, _, rest = source_id.partition(":")
    if src.kind in ("news", "user_input") and rest.isdigit():
        row = NewsStore(ctx.db).get(int(rest))
        if row is not None and (row.owner_company_id in (None, company_id)):
            text = (row.body or row.rss_summary or "")[:NEWS_TEXT_CHARS] or None
    elif src.kind == "alfa":
        chunk = ResearchStore(ctx.db).chunk_by_source(source_id)
        if chunk is not None:
            text, doc_title, page = chunk["text"], chunk["doc_title"], chunk["page"]
    elif src.kind == "cbr":
        indicator = rest.rsplit(":", 1)[0]
        summary = MacroStore(ctx.db).summary(indicator, days=90, weekly=True)
        data = summary.model_dump(mode="json") if summary else None
    elif src.kind == "client_data":
        data = _client_data(ctx, company_id, source_id, src.payload)
    return SourceDetail(
        id=src.id, kind=src.kind, title=src.title, publisher=src.publisher, url=src.url,  # type: ignore[arg-type]
        published_at=parse_dt(src.published_at) if src.published_at else None, excerpt=src.excerpt, text=text,
        doc_title=doc_title, page=page, data=data,
    )  # fmt: skip


@router.get("/sources/{source_id:path}", response_model=SourceDetail)
async def get_source(
    source_id: str, s: SessionData = Depends(current_session), ctx: AppContext = Depends(get_ctx)
) -> SourceDetail:
    return await asyncio.to_thread(build_source, ctx, source_id, s.company_id)
