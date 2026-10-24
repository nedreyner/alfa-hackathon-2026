"""Поиск новостей: bm25 × свежесть, лучший результат на событие (docs/06-ingestion-search.md §13.2)."""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from pydantic import BaseModel

from alfa_insight.db.sqlite import SqliteDB
from alfa_insight.search.fts import build_match
from alfa_insight.store.search import SearchStore
from alfa_insight.timeutil import parse_dt, to_iso, utc_now

HALF_LIFE_DAYS = 7.0


class NewsHit(BaseModel):
    news_id: int
    event_id: int | None
    title: str
    publisher: str
    published_at: datetime
    url: str | None
    snippet: str
    score: float


def freshness(published: datetime, now: datetime, half_life_days: float = HALF_LIFE_DAYS) -> float:
    age_days = max(0.0, (now - published).total_seconds() / 86400)
    return math.exp(-math.log(2) * age_days / half_life_days)


def search_news(
    db: SqliteDB,
    query: str,
    *,
    company_id: str | None,
    days: int = 30,
    industry_ids: list[str] | None = None,
    limit: int = 5,
    now: datetime | None = None,
) -> list[NewsHit]:
    match = build_match(query)
    if match is None:
        return []
    now = now or utc_now()
    rows = SearchStore(db).news(
        match,
        since=to_iso(now - timedelta(days=days)),
        company_id=company_id,
        industry_ids=industry_ids,
        limit=limit * 3,
    )
    hits: dict[int | str, NewsHit] = {}
    for r in rows:
        published = parse_dt(r["published_at"])
        score = -float(r["rank"]) * (0.7 + 0.3 * freshness(published, now))
        hit = NewsHit(
            news_id=r["id"],
            event_id=r["event_id"],
            title=r["title"],
            publisher=r["publisher"],
            published_at=published,
            url=r["url"],
            snippet=(r["snippet"] or "")[:400],
            score=round(score, 6),
        )
        key: int | str = r["event_id"] if r["event_id"] is not None else f"n{r['id']}"
        if key not in hits or hits[key].score < hit.score:
            hits[key] = hit
    return sorted(hits.values(), key=lambda h: -h.score)[:limit]
