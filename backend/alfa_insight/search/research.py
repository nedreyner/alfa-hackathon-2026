"""Поиск по аналитике Альфа-Банка (docs/06-ingestion-search.md §13.3)."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from alfa_insight.db.sqlite import SqliteDB
from alfa_insight.search.fts import build_match
from alfa_insight.store.search import SearchStore

TAG_BOOST = 1.3
MAX_TEXT = 1200


class ResearchItemBrief(BaseModel):
    kind: str
    statement: str


class ResearchHit(BaseModel):
    source_id: str
    doc_title: str
    doc_date: date | None
    page: int
    heading: str | None
    text: str
    items: list[ResearchItemBrief]
    score: float


def search_research(
    db: SqliteDB,
    query: str,
    *,
    industry_ids: list[str] | None = None,
    factor_ids: list[str] | None = None,
    limit: int = 4,
) -> list[ResearchHit]:
    match = build_match(query)
    if match is None:
        return []
    store = SearchStore(db)
    rows = store.research(match, limit=limit * 3)
    items = store.research_items([r["id"] for r in rows])
    wanted_i, wanted_f = set(industry_ids or []), set(factor_ids or [])
    hits = []
    for r in rows:
        its = items.get(r["id"], [])
        score = -float(r["rank"])
        if any(set(i["industries"]) & wanted_i or set(i["factors"]) & wanted_f for i in its):
            score *= TAG_BOOST
        hits.append(
            ResearchHit(
                source_id=r["source_id"],
                doc_title=r["title"],
                doc_date=date.fromisoformat(r["published_at"]) if r["published_at"] else None,
                page=r["page"],
                heading=r["heading"],
                text=r["text"][:MAX_TEXT],
                items=[ResearchItemBrief(kind=i["kind"], statement=i["statement"]) for i in its],
                score=round(score, 6),
            )
        )
    return sorted(hits, key=lambda h: -h.score)[:limit]
