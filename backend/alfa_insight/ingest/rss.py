"""Сбор RSS (docs/06-ingestion-search.md §3)."""

from __future__ import annotations

import asyncio
import calendar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import feedparser
import httpx

from alfa_insight.ingest.sources import Source, SourcesConfig
from alfa_insight.log import get_logger
from alfa_insight.store.kv import KVStore
from alfa_insight.store.news import NewsIn, NewsStore
from alfa_insight.text.normalize import normalize_text, normalize_url, strip_html
from alfa_insight.timeutil import to_iso, utc_now

log = get_logger("ingest.rss")
MAX_FEED_BYTES = 5_000_000


@dataclass
class SourceResult:
    source_id: str
    ok: bool
    items_total: int = 0
    items_new: int = 0
    error: str | None = None
    not_modified: bool = False


def _entry_dt(entry: Any) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        value = entry.get(key)
        if value:
            return datetime.fromtimestamp(calendar.timegm(value), tz=UTC)
    return None


def parse_feed(source: Source, content: bytes, *, now: datetime, max_age_days: int) -> list[NewsIn]:
    feed = feedparser.parse(content)
    cutoff = now - timedelta(days=max_age_days)
    fetched_at = to_iso(now)
    items: list[NewsIn] = []
    for entry in feed.entries[: source.max_items or 100]:
        link = normalize_url(entry.get("link"))
        title = normalize_text(strip_html(entry.get("title")))
        if not title:
            continue
        published = _entry_dt(entry) or now
        if published < cutoff:
            continue
        summary = normalize_text(strip_html(entry.get("summary") or entry.get("description"))) or None
        categories = [normalize_text(t.get("term")) for t in entry.get("tags", []) if t.get("term")]
        external_id = entry.get("id") or entry.get("guid") or link or None
        items.append(
            NewsIn(
                source_id=source.id,
                origin="rss",
                external_id=external_id,
                url=link or None,
                title=title,
                rss_summary=summary,
                publisher=source.publisher,
                trust=source.trust,
                published_at=to_iso(published),
                fetched_at=fetched_at,
                rss_categories=categories,
            )
        )
    return items


async def fetch_source(
    client: httpx.AsyncClient, source: Source, kv: KVStore, user_agent: str
) -> tuple[bytes | None, dict[str, str]]:
    """Скачать ленту с условными заголовками. None — 304 (нового нет)."""
    cache = kv.get(f"rss_etag:{source.id}", {}) or {}
    headers = {"User-Agent": user_agent}
    if cache.get("etag"):
        headers["If-None-Match"] = cache["etag"]
    if cache.get("last_modified"):
        headers["If-Modified-Since"] = cache["last_modified"]
    async with client.stream("GET", source.url, headers=headers, timeout=source.timeout_s) as resp:
        if resp.status_code == 304:
            return None, cache
        resp.raise_for_status()
        chunks, size = [], 0
        async for chunk in resp.aiter_bytes():
            size += len(chunk)
            if size > MAX_FEED_BYTES:
                raise ValueError("лента больше 5 МБ")
            chunks.append(chunk)
        meta = {
            k: v
            for k, v in {
                "etag": resp.headers.get("etag"),
                "last_modified": resp.headers.get("last-modified"),
            }.items()
            if v
        }
        return b"".join(chunks), meta


async def collect_rss(
    sources: SourcesConfig,
    news: NewsStore,
    kv: KVStore,
    *,
    ingest_geo: str = "any",
    max_age_days: int = 7,
    only: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    now: datetime | None = None,
) -> list[SourceResult]:
    active = [s for s in sources.active(ingest_geo) if only is None or s.id == only]
    results: list[SourceResult] = []
    client_kw: dict[str, Any] = {"follow_redirects": True, "max_redirects": 3}
    if transport is not None:
        client_kw["transport"] = transport
    async with httpx.AsyncClient(**client_kw) as client:

        async def one(src: Source) -> SourceResult:
            status_key = f"source_status:{src.id}"
            prev = kv.get(status_key, {}) or {}
            try:
                content, meta = await fetch_source(client, src, kv, sources.user_agent)
                if content is None:
                    res = SourceResult(src.id, True, not_modified=True)
                else:
                    items = parse_feed(src, content, now=now or utc_now(), max_age_days=max_age_days)
                    new_ids = news.insert(items)
                    kv.set(f"rss_etag:{src.id}", meta)
                    res = SourceResult(src.id, True, len(items), len(new_ids))
                kv.set(
                    status_key,
                    {
                        "ok": True,
                        "last_success_at": to_iso(utc_now()),
                        "last_error": None,
                        "items_total": res.items_total,
                        "items_new": res.items_new,
                    },
                )
                return res
            except Exception as exc:  # ошибка одного источника не мешает остальным
                err = f"{type(exc).__name__}: {exc}"[:300]
                log.warning("rss_source_failed", source=src.id, error=err)
                kv.set(
                    status_key, {**prev, "ok": False, "last_error": err, "last_error_at": to_iso(utc_now())}
                )
                return SourceResult(src.id, False, error=err)

        results = list(await asyncio.gather(*(one(s) for s in active)))
    return results
