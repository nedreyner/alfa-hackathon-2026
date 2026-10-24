"""Брифинг роли: 3 главных события для CFO, казначея или собственника, без LLM (docs/08-agent.md §14)."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from alfa_insight.agent.schemas import Action, Insight, ProductOffer
from alfa_insight.appctx import AppContext
from alfa_insight.ranking.models import Direction, ImpactLevel, Role
from alfa_insight.store.events import EventStore
from alfa_insight.store.insights import InsightStore
from alfa_insight.store.rankings import RankingStore
from alfa_insight.timeutil import utc_now

CANDIDATES = 10
BRIEF_ITEMS = 3
READY_BOOST = (
    1.5  # готовый инсайт уступает pending-событию, только если у того скор выше больше чем в 1.5 раза
)
WORDS_PER_MINUTE = 200


class BriefItem(BaseModel):
    status: Literal["ready", "pending"]
    event_id: int
    insight_id: str | None
    headline: str
    why_you: str | None
    direction: Direction
    impact_level: ImpactLevel
    action: Action | None
    product: ProductOffer | None
    score: float


class Brief(BaseModel):
    role: Role
    items: list[BriefItem]
    reading_time_s: int
    generated_at: datetime


def pick_action(insight: Insight, role: Role) -> tuple[Action | None, ProductOffer | None]:
    """Первое действие с owner_role = роль, иначе первое; продукт — привязанный к этому действию."""
    if not insight.actions:
        return None, None
    idx = next((i for i, a in enumerate(insight.actions) if a.owner_role == role), 0)
    product = next((p for p in insight.products if p.action_index == idx), None)
    return insight.actions[idx], product


def _words(item: BriefItem) -> int:
    parts = [item.headline, item.why_you or ""]
    if item.action is not None:
        parts += [item.action.title, item.action.claim.text]
    return sum(len(p.split()) for p in parts)


def build_brief(app: AppContext, company_id: str, role: Role) -> Brief:
    rows = RankingStore(app.db).top(company_id, role, limit=CANDIDATES)
    insights = InsightStore(app.db).latest_by_events(
        company_id, [r["event_id"] for r in rows], statuses=("published",)
    )
    events = EventStore(app.db)
    items: list[BriefItem] = []
    for r in rows:
        row = insights.get(r["event_id"])
        if row is not None:
            ins = Insight.model_validate(row.payload)
            action, product = pick_action(ins, role)
            items.append(
                BriefItem(
                    status="ready", event_id=r["event_id"], insight_id=ins.id, headline=ins.headline,
                    why_you=ins.why_you, direction=ins.direction, impact_level=ins.impact_level,
                    action=action, product=product, score=r["score"],
                )
            )  # fmt: skip
            continue
        ev = events.get(r["event_id"])
        if ev is None:
            continue
        items.append(
            BriefItem(
                status="pending", event_id=ev.id, insight_id=None, headline=ev.title, why_you=r["chain_preview"],
                direction=r["direction"], impact_level=r["impact_level"], action=None, product=None, score=r["score"],
            )
        )  # fmt: skip
    items.sort(key=lambda i: -(i.score * READY_BOOST if i.status == "ready" else i.score))
    top = items[:BRIEF_ITEMS]
    words = sum(_words(i) for i in top)
    return Brief(
        role=role,
        items=top,
        reading_time_s=max(10, math.ceil(words / WORDS_PER_MINUTE * 60)),
        generated_at=utc_now(),
    )
