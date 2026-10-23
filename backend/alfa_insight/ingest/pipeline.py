"""Стадии конвейера новостей (docs/06-ingestion-search.md §1). Каждая стадия идемпотентна."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import timedelta
from urllib.parse import urlsplit

from pydantic import BaseModel

from alfa_insight.appctx import AppContext
from alfa_insight.errors import AppError
from alfa_insight.ingest.dedup import Deduper, DedupIndex
from alfa_insight.ingest.extract import choose_body, content_hash
from alfa_insight.ingest.prefilter import Prefilter
from alfa_insight.log import get_logger
from alfa_insight.net.safe_fetch import safe_fetch
from alfa_insight.store.news import NewsRow, NewsStore
from alfa_insight.text.injection import InjectionDetector
from alfa_insight.text.simhash import to_signed
from alfa_insight.timeutil import to_iso, utc_now

log = get_logger("ingest.pipeline")
MAX_EXTRACT_ATTEMPTS = 3
EXTRACT_CONCURRENCY = 4
PER_HOST_INTERVAL_S = 1.0


class PipelineStats(BaseModel):
    fetched: int = 0
    extracted: int = 0
    filtered_out: int = 0
    duplicates: int = 0
    tagged: int = 0
    clustered: int = 0
    failed: int = 0
    cost_rub: float = 0.0

    def add(self, other: PipelineStats) -> None:
        for name in type(self).model_fields:
            setattr(self, name, getattr(self, name) + getattr(other, name))


class _HostLimiter:
    """Не больше одного запроса в секунду на хост."""

    def __init__(self, interval_s: float):
        self.interval = interval_s
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._last: dict[str, float] = {}

    async def wait(self, host: str) -> None:
        async with self._locks[host]:
            loop = asyncio.get_running_loop()
            delay = self._last.get(host, 0.0) + self.interval - loop.time()
            if delay > 0:
                await asyncio.sleep(delay)
            self._last[host] = loop.time()


def detector(ctx: AppContext) -> InjectionDetector:
    return InjectionDetector(ctx.taxonomy.injection)


async def stage_extract(ctx: AppContext, *, max_extract: int = 50, fetch: bool = True) -> PipelineStats:
    """new → extracted: полный текст (или RSS-анонс после 3 неудачных попыток)."""
    store = NewsStore(ctx.db)
    stats = PipelineStats()
    rows = store.by_status("new", max_extract)
    boiler = ctx.taxonomy.prefilter.boilerplate
    det = detector(ctx)
    limiter = _HostLimiter(PER_HOST_INTERVAL_S)
    sem = asyncio.Semaphore(EXTRACT_CONCURRENCY)

    async def one(row: NewsRow) -> None:
        source = ctx.sources.get(row.source_id)
        want_full = fetch and row.url and (source is None or source.full_text)
        html: str | None = None
        if want_full and row.attempts < MAX_EXTRACT_ATTEMPTS:
            assert row.url is not None
            async with sem:
                await limiter.wait(urlsplit(row.url).hostname or "")
                try:
                    result = await safe_fetch(row.url, user_agent=ctx.sources.user_agent)
                    html = result.text
                except AppError as exc:
                    attempts = await asyncio.to_thread(
                        store.bump_attempt, row.id, f"{exc.code}: {exc.message}"
                    )
                    if attempts < MAX_EXTRACT_ATTEMPTS:
                        return
        extracted = choose_body(html, row.url, row.title, row.rss_summary, boiler)
        flags = det.detect(row.title, extracted.body)
        store.set_extracted(
            row.id,
            body=extracted.body,
            body_source=extracted.body_source,
            content_hash=content_hash(row.title, extracted.body),
            injection_flags=flags,
        )
        stats.extracted += 1

    await asyncio.gather(*(one(r) for r in rows))
    return stats


def stage_prefilter_dedup(ctx: AppContext, rows: list[NewsRow]) -> tuple[list[NewsRow], PipelineStats]:
    """extracted → filtered_out | duplicate | (остаётся extracted для разметки)."""
    store = NewsStore(ctx.db)
    stats = PipelineStats()
    pf = Prefilter(ctx.taxonomy, min_score=ctx.settings.prefilter_min_score)
    dd = Deduper(max_distance=ctx.settings.simhash_max_distance)
    now = utc_now()
    sims, hashes = store.dedup_index_rows(to_iso(now - timedelta(hours=72)), to_iso(now - timedelta(days=7)))
    index = DedupIndex(simhashes=[(i, s) for i, s in sims], content_hashes=hashes)
    survivors: list[NewsRow] = []
    for row in sorted(rows, key=lambda r: (r.published_at, r.id)):
        if row.prefilter_score is not None and row.simhash is not None:
            survivors.append(row)  # уже проверена в прошлом тике
            continue
        source = ctx.sources.get(row.source_id)
        result = pf.score(row.title, row.body, row.rss_categories, source, row.trust)
        fp = dd.fingerprint(row.title, row.body)
        store.set_prefilter(row.id, result.score, to_signed(fp))
        if not result.passed:
            store.set_status(row.id, "filtered_out")
            stats.filtered_out += 1
            continue
        dup = dd.find_duplicate(index, row.id, row.content_hash, fp)
        if dup is not None:
            store.set_status(row.id, "duplicate", duplicate_of=dup)
            stats.duplicates += 1
            continue
        dd.remember(index, row.id, row.content_hash, fp)
        survivors.append(row)
    return survivors, stats
