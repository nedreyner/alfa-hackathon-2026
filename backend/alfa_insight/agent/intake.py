"""Intake фичи B «Проверить любую новость»: URL или текст → новость → приватное событие (docs/08-agent.md §12)."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, HttpUrl, model_validator

from alfa_insight.agent.context import AgentContext
from alfa_insight.errors import UnsupportedContent
from alfa_insight.ingest.clustering import Clusterer
from alfa_insight.ingest.extract import extract_main_text, extract_title
from alfa_insight.ingest.pipeline import detector
from alfa_insight.ingest.tagging import tag_one
from alfa_insight.net.safe_fetch import safe_fetch
from alfa_insight.store.news import NewsIn, NewsStore
from alfa_insight.store.runs import RunStore
from alfa_insight.text.lemmatizer import lemmas_str
from alfa_insight.text.normalize import normalize_text, normalize_url
from alfa_insight.timeutil import to_iso, utc_now

MIN_TEXT_CHARS = 300  # извлечённый со страницы текст
MIN_PASTED_CHARS = 200  # вставленный текст (как в AnalyzeInput)
WEAK_RELEVANCE = 0.05
USER_TRUST = 0.5
TEXT_PUBLISHER = "Ваш текст"


class AnalyzeInput(BaseModel):
    url: HttpUrl | None = None
    text: str | None = Field(default=None, min_length=200, max_length=20_000)
    title: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def _one_of(self) -> AnalyzeInput:
        if (self.url is None) == (self.text is None):
            raise ValueError("Нужно указать ровно одно: url или text")
        return self


class IntakeResult(BaseModel):
    event_id: int
    news_id: int
    reused: bool
    relevance: float | None = None
    weak_note: str | None = None


def _site(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host.removeprefix("www.") or TEXT_PUBLISHER


def _first_line_title(text: str) -> str:
    line = text.strip().split("\n", 1)[0].strip()
    return (line[:160].rsplit(" ", 1)[0] + "…") if len(line) > 160 else line


async def intake(
    ctx: AgentContext, inp: AnalyzeInput, *, fetch_options: dict[str, Any] | None = None
) -> IntakeResult:
    """`fetch_options` — доп. аргументы safe_fetch (transport, resolver) для тестов."""
    app = ctx.app
    news = NewsStore(app.db)
    url = normalize_url(str(inp.url)) if inp.url else None
    ctx.trace.phase("intake", "Читаю новость")

    # 1. URL уже в базе: публичная размеченная новость или своя прошлая проверка
    if url:
        row = news.by_url(url)
        own = row is not None and row.origin == "user" and row.owner_company_id == ctx.company_id
        public = row is not None and row.origin != "user" and row.status in ("tagged", "clustered")
        if row is not None and row.event_id is not None and (own or public):
            ctx.trace.emit("intake.fetch", "intake", "Эта новость уже есть в базе — беру готовую разметку",
                           payload={"domain": _site(url), "news_id": row.id, "reused": True})  # fmt: skip
            return _finish(ctx, row.event_id, row.id, reused=True)
        if row is not None:
            url_for_row: str | None = None  # чужая приватная или неразмеченная копия: свою пишем без url
        else:
            url_for_row = url
    # 2–3. загрузка и извлечение текста
    if url:
        res = await safe_fetch(url, user_agent=app.sources.user_agent, **(fetch_options or {}))
        ctx.trace.emit("intake.fetch", "intake", f"Загружаю статью: {_site(res.url_final)}",
                       payload={"domain": _site(res.url_final), "bytes": res.bytes, "duration_ms": res.elapsed_ms})  # fmt: skip
        body = await asyncio.to_thread(extract_main_text, res.text, res.url_final)
        title = inp.title or extract_title(res.text) or _first_line_title(body or "")
        publisher = _site(res.url_final)
    else:
        body, publisher, url_for_row = inp.text, TEXT_PUBLISHER, None
        title = inp.title or _first_line_title(body or "")
    body = normalize_text(body or "")
    if len(body) < (MIN_TEXT_CHARS if url else MIN_PASTED_CHARS):
        raise UnsupportedContent("Не удалось извлечь текст статьи", {"chars": len(body)})
    title = normalize_text(title or "")[:300] or _first_line_title(body)
    ctx.trace.emit("intake.extract", "intake", f"Извлёк текст: {len(body):,} знаков".replace(",", " "),
                   payload={"chars": len(body), "title": title})  # fmt: skip

    # 4. детектор инъекций
    flags = detector(app).detect(title, body)
    if flags:
        ctx.trace.emit("intake.security", "intake", "В тексте найдена попытка управлять ИИ — игнорирую её",
                       status="warn", payload={"flags": flags})  # fmt: skip

    # 5–6. новость, разметка, приватное событие, ранжирование
    now = to_iso(utc_now())
    [news_id] = news.insert(
        [
            NewsIn(
                source_id="user", origin="user", external_id=ctx.run_id, url=url_for_row, title=title, body=body,
                body_source="user", publisher=publisher, trust=USER_TRUST, published_at=now, fetched_at=now,
                status="extracted", owner_company_id=ctx.company_id,
            )
        ]
    )  # fmt: skip
    if flags:
        app.db.execute("UPDATE news SET injection_flags = ? WHERE id = ?", (_json(flags), news_id))
    row = news.get(news_id)
    assert row is not None
    clean, model, version, _cost = await tag_one(
        app, row, task="tagging_interactive", priority="interactive", run_id=ctx.run_id
    )
    news.save_tags(
        news_id, clean, model=model, prompt_version=version, title_lemmas=lemmas_str(title),
        body_lemmas=lemmas_str(f"{clean.summary}\n{body}"), status="tagged",
    )  # fmt: skip
    names = [app.taxonomy.industry(i.industry_id).name for i in clean.industries[:3]]
    ctx.trace.emit("intake.tagged", "intake",
                   f"Тема: {app.taxonomy.event_types[clean.event_type].name.lower()}" + (f"; отрасли: {', '.join(n.lower() for n in names)}" if names else ""),
                   payload={"event_type": clean.event_type, "industries": [i.industry_id for i in clean.industries],
                            "factors": [f.factor_id for f in clean.factors], "importance": clean.importance})  # fmt: skip
    tagged = news.get(news_id)
    assert tagged is not None
    event_id, _ = Clusterer(app).assign(tagged)
    news.set_status(news_id, "clustered")
    return _finish(ctx, event_id, news_id, reused=False)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _finish(ctx: AgentContext, event_id: int, news_id: int, *, reused: bool) -> IntakeResult:
    ctx.event_id = event_id
    ctx.allowed_event_ids.add(event_id)
    RunStore(ctx.app.db).set_event(ctx.run_id, event_id)
    res = ctx.app.ranking.rank_private(event_id, ctx.company_id, role=ctx.role)
    relevance = res.exposure.relevance if res is not None else None
    note = None
    if relevance is not None and relevance < WEAK_RELEVANCE:
        note = (
            f"Связь события с компанией слабая (relevance={relevance:.3f}): дай короткий разбор — что произошло, "
            "почему влияние на компанию минимально и за чем следить; impact_level = low"
        )
    return IntakeResult(
        event_id=event_id, news_id=news_id, reused=reused, relevance=relevance, weak_note=note
    )
