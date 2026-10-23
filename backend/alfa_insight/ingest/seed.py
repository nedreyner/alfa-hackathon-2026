"""Seed-набор новостей (`data/seed/news.jsonl`, docs/06-ingestion-search.md §10)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from alfa_insight.appctx import AppContext
from alfa_insight.ingest.extract import content_hash
from alfa_insight.store.news import NewsIn, NewsStore
from alfa_insight.text.injection import InjectionDetector
from alfa_insight.text.normalize import normalize_text
from alfa_insight.timeutil import parse_dt, to_iso, utc_now

SEED_BODY_CHARS = 3000
SHIFT_GAP = timedelta(hours=2)
SEED_SHIFT_KEY = "seed_shift_s"


class SeedItem(BaseModel):
    seed_id: str
    source_id: str
    publisher: str
    url: str | None = None
    title: str
    published_at: str
    categories: list[str] = Field(default_factory=list)
    summary: str | None = None
    body: str | None = None
    synthetic_test: bool = False
    story: str | None = None
    expect_relevant: bool | None = None


def read_seed(path: Path) -> list[SeedItem]:
    if not path.exists():
        return []
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            items.append(SeedItem.model_validate_json(line))
    return items


def write_seed(path: Path, items: list[SeedItem]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for it in items:
            fh.write(json.dumps(it.model_dump(mode="json"), ensure_ascii=False) + "\n")


def shift_delta(items: list[SeedItem], now: datetime) -> timedelta:
    """Сдвиг, после которого самая свежая новость seed окажется в `now − 2ч`."""
    if not items:
        return timedelta(0)
    latest = max(parse_dt(i.published_at) for i in items)
    return (now - SHIFT_GAP) - latest


def load_seed(
    ctx: AppContext, path: Path, *, shift_to_now: bool = False, now: datetime | None = None
) -> dict[str, int]:
    """Загрузить seed в `news` (origin=seed, status=extracted). Повторная загрузка не создаёт дублей.

    При `shift_to_now` даты всех seed-новостей (и уже загруженных) пересчитываются от исходных.
    """
    items = read_seed(path)
    store = NewsStore(ctx.db)
    det = InjectionDetector(ctx.taxonomy.injection)
    now = now or utc_now()
    delta = shift_delta(items, now) if shift_to_now else timedelta(0)
    rows: list[NewsIn] = []
    for it in items:
        published = parse_dt(it.published_at) + delta
        body = normalize_text(it.body or it.summary or it.title, limit=SEED_BODY_CHARS)
        rows.append(
            NewsIn(
                source_id=it.source_id,
                origin="seed",
                external_id=it.seed_id,
                url=it.url,
                title=normalize_text(it.title),
                rss_summary=normalize_text(it.summary) or None,
                body=body,
                body_source="seed",
                publisher=it.publisher,
                trust=ctx.sources.trust(it.source_id),
                published_at=to_iso(published),
                fetched_at=to_iso(published),
                rss_categories=it.categories,
                content_hash=content_hash(normalize_text(it.title), body),
                status="extracted",
            )
        )
    new_ids = set(store.insert(rows))
    for news_id in new_ids:
        row = store.get(news_id)
        if row is not None:
            flags = det.detect(row.title, row.body)
            if flags:
                store.set_status(news_id, row.status, injection_flags=flags)
    shifted = 0
    if shift_to_now:
        shifts: dict[int, tuple[str, str]] = {}
        for it, r in zip(items, rows, strict=True):
            existing = store.by_external(it.source_id, it.seed_id)
            if (
                existing is not None
                and existing.id not in new_ids
                and existing.published_at != r.published_at
            ):
                shifts[existing.id] = (r.published_at, r.fetched_at)
        store.update_dates(shifts)
        shifted = len(shifts)
        ctx.kv.set(SEED_SHIFT_KEY, delta.total_seconds())
    return {"total": len(items), "inserted": len(new_ids), "shifted": shifted}


def seed_item_from_row(row: Any, seed_id: str) -> SeedItem:
    body = (row.body or "")[:SEED_BODY_CHARS]
    return SeedItem(
        seed_id=seed_id,
        source_id=row.source_id,
        publisher=row.publisher,
        url=row.url,
        title=row.title,
        published_at=row.published_at,
        categories=row.rss_categories,
        summary=row.rss_summary,
        body=body,
    )
