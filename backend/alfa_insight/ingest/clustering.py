"""Кластеризация новостей в события (docs/06-ingestion-search.md §9, ADR-09)."""

from __future__ import annotations

from collections import Counter
from datetime import timedelta

from alfa_insight.appctx import AppContext
from alfa_insight.store.events import EventStore
from alfa_insight.store.news import NewsRow, NewsStore
from alfa_insight.text.lemmatizer import lemmas_str, lemmatize
from alfa_insight.timeutil import parse_dt, to_iso

KEY_LEMMAS_NEWS = 30
WINDOW = timedelta(hours=72)
TITLE_SIM_MIN = 0.15


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def key_lemmas(title: str, summary: str | None) -> list[str]:
    weights: Counter[str] = Counter()
    for w in lemmatize(title):
        weights[w] += 2
    for w in lemmatize(summary or ""):
        weights[w] += 1
    return [w for w, _ in sorted(weights.items(), key=lambda kv: (-kv[1], kv[0]))[:KEY_LEMMAS_NEWS]]


class Clusterer:
    def __init__(self, ctx: AppContext, threshold: float | None = None):
        self.ctx = ctx
        self.news = NewsStore(ctx.db)
        self.events = EventStore(ctx.db)
        self.threshold = ctx.settings.cluster_sim_threshold if threshold is None else threshold

    def _news_key(self, news_id: int) -> list[str]:
        row = self.news.get(news_id)
        tags = self.news.tags(news_id)
        summary = tags["payload"]["summary"] if tags else None
        return key_lemmas(row.title, summary) if row else []

    def _recompute(self, event_id: int) -> None:
        members = self.events.news_ids(event_id)
        keys = {nid: self._news_key(nid) for nid in members}
        ev = self.events.get(event_id)
        lead = self.news.get(ev.lead_news_id) if ev and ev.lead_news_id else self.news.get(members[0])
        lead_tags = self.news.tags(lead.id) if lead else None
        summary = lead_tags["payload"]["summary"] if lead_tags else (lead.title if lead else "")
        self.events.recompute(event_id, keys, lemmas_str(lead.title if lead else ""), lemmas_str(summary))
        # ведущая новость могла смениться — пересчитать FTS по новой
        ev2 = self.events.get(event_id)
        if ev2 and ev and ev2.lead_news_id != ev.lead_news_id:
            self.events.recompute(event_id, keys, lemmas_str(ev2.title), lemmas_str(ev2.summary))

    def assign(self, row: NewsRow) -> tuple[int, bool]:
        """Присоединить новость к событию или создать новое: (event_id, создано ли новое)."""
        tags = self.news.tags(row.id)
        payload = tags["payload"] if tags else {}
        if row.origin == "user":
            event_id = self.events.create(row.id, visibility="private", owner_company_id=row.owner_company_id)
            self._recompute(event_id)
            return event_id, True
        industries = [i["industry_id"] for i in payload.get("industries", [])]
        factors = [f["factor_id"] for f in payload.get("factors", [])]
        event_type = payload.get("event_type", "other")
        since = to_iso(parse_dt(row.published_at) - WINDOW)
        keys = set(key_lemmas(row.title, payload.get("summary")))
        title_lem = set(lemmatize(row.title))
        entities = {e["name"].lower() for e in payload.get("entities", [])}
        best: tuple[float, int] | None = None
        for ev, _inds, _facs in self.events.candidates(since, event_type, industries, factors):
            sim = jaccard(keys, set(ev.key_lemmas))
            if sim < self.threshold:
                continue
            title_ok = jaccard(title_lem, set(lemmatize(ev.title))) >= TITLE_SIM_MIN
            if not title_ok and not (entities & self.events.entities(ev.id)):
                continue
            if best is None or sim > best[0]:
                best = (sim, ev.id)
        if best is not None:
            self.events.attach(row.id, best[1])
            self._recompute(best[1])
            return best[1], False
        event_id = self.events.create(row.id)
        self._recompute(event_id)
        return event_id, True


def cluster_tagged(ctx: AppContext, *, limit: int = 1000) -> tuple[int, int]:
    """Все новости status='tagged' по порядку публикации: (присоединено к событиям, создано событий)."""
    clusterer = Clusterer(ctx)
    rows = NewsStore(ctx.db).by_status("tagged", limit, newest_first=False)
    joined = created = 0
    for row in rows:
        _, new = clusterer.assign(row)
        created += int(new)
        joined += int(not new)
    return joined, created
