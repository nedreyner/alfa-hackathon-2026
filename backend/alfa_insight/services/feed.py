"""Лента событий компании и роли: ранжирование + статусы инсайтов и прогонов (docs/09-api.md §4.3)."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from typing import Any

from alfa_insight.agent.finalize import event_publishers
from alfa_insight.appctx import AppContext
from alfa_insight.errors import ValidationAppError
from alfa_insight.ranking.diversity import diversify_rows
from alfa_insight.services.insights import current_prompt_version
from alfa_insight.store.events import EventStore
from alfa_insight.store.insights import InsightStore
from alfa_insight.store.rankings import RankingStore
from alfa_insight.store.runs import RunStore
from alfa_insight.timeutil import parse_dt

IMPACT_ORDER = ["low", "medium", "high", "critical"]
MAX_ROWS = 2000


def encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(f"o:{offset}".encode()).decode().rstrip("=")


def decode_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        if not raw.startswith("o:"):
            raise ValueError(raw)
        return max(0, int(raw[2:]))
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise ValidationAppError("Некорректный курсор", {"cursor": cursor}) from exc


@dataclass
class FeedPage:
    items: list[dict[str, Any]]
    next_cursor: str | None
    total: int


def build_feed(
    app: AppContext,
    company_id: str,
    role: str,
    *,
    limit: int = 20,
    cursor: str | None = None,
    direction: str | None = None,
    min_impact: str | None = None,
) -> FeedPage:
    cfg = app.ranking_config.feed
    rows = RankingStore(app.db).top(company_id, role, min_score=cfg.min_score, limit=MAX_ROWS)
    rows = diversify_rows([r for r in rows if r["relevance"] >= cfg.min_relevance])
    version = current_prompt_version(app)
    profile_version = app.profiles.get(company_id).profile_version
    insights = {
        eid: row
        for eid, row in InsightStore(app.db)
        .latest_by_events(company_id, [r["event_id"] for r in rows])
        .items()
        if row.prompt_version == version
    }

    def shown(r: dict[str, Any], key: str) -> str:
        """Фильтры — по тому, что видит пользователь: у готовых карточек значения из инсайта."""
        ins = insights.get(r["event_id"])
        return str(ins.payload.get(key) if ins is not None else r[key])

    if direction:
        rows = [r for r in rows if shown(r, "direction") == direction]
    if min_impact:
        floor = IMPACT_ORDER.index(min_impact)
        rows = [r for r in rows if IMPACT_ORDER.index(shown(r, "impact_level")) >= floor]
    total = len(rows)
    offset = decode_cursor(cursor)
    page = rows[offset : offset + limit]
    ids = [r["event_id"] for r in page]
    runs = RunStore(app.db).latest_by_events(company_id, ids)
    events = EventStore(app.db)
    items = []
    for r in page:
        ev = events.get(r["event_id"])
        if ev is None:
            continue
        ins = insights.get(ev.id)
        run = runs.get(ev.id)
        publishers = event_publishers(app.db, ev.id)
        status, run_id = "pending", None
        if ins is not None:
            status = "ready"
        elif run is not None and run.status in ("queued", "running"):
            status, run_id = "generating", run.id
        elif run is not None and run.status == "failed":
            status, run_id = "failed", run.id
        payload = ins.payload if ins is not None else {}
        items.append(
            {
                "event_id": ev.id, "status": status, "insight_id": ins.id if ins else None, "run_id": run_id,
                "headline": payload.get("headline") or ev.title,
                "why_you": payload.get("why_you") or r["chain_preview"],
                "chain_preview": payload.get("chain_preview") or r["chain_preview"],
                "direction": payload.get("direction") or r["direction"],
                "impact_level": payload.get("impact_level") or r["impact_level"],
                "score": round(r["score"], 4),
                "confidence_level": ins.confidence_level if ins else None,
                "event_title": ev.title, "event_type": ev.event_type, "published_at": parse_dt(ev.first_seen_at),
                "publishers": publishers,
                "source_count": len(payload.get("sources", [])) if ins else max(1, len(publishers)),
                "stale": bool(ins and ins.profile_version != profile_version),
                "needs_review": bool(ins and ins.status == "needs_review"),
            }
        )  # fmt: skip
    next_cursor = encode_cursor(offset + limit) if offset + limit < total else None
    return FeedPage(items=items, next_cursor=next_cursor, total=total)
