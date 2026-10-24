"""Брифинг роли: 3 главных события для CFO, казначея или собственника, без LLM (docs/08-agent.md §14)."""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from alfa_insight.agent.schemas import Action, Insight, ProductOffer
from alfa_insight.appctx import AppContext
from alfa_insight.ranking.diversity import diversify, main_path_key
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


ROLE_FOCUS_BONUS = 1.5
FOCUS_MIN_MULTIPLIER = 1.15


def role_focus(app: AppContext, role: Role) -> set[str]:
    """Главные пути, которые роль видит в первую очередь: каналы и факторы с множителем роли > 1.15.

    Скоры насыщаются (у компании с кредитом экспозиция к ставке 1.0), и множители ранжирования порядок
    почти не меняют; поэтому брифинг дополнительно поднимает темы роли (07-ranking.md §7).
    """
    cfg = app.ranking_config.roles[role]
    keys = {f"{ch}:*" for ch, w in cfg.channels.items() if ch != "factor" and w >= FOCUS_MIN_MULTIPLIER}
    keys |= {f"factor:{f}" for f, w in cfg.factors.items() if w >= FOCUS_MIN_MULTIPLIER}
    return keys


def in_focus(key: str, focus: set[str]) -> bool:
    return key in focus or f"{key.split(':', 1)[0]}:*" in focus


def distinct_themes[T](items: list[T], tags: Callable[[T], set[str]], n: int) -> list[T]:
    """Первые n по порядку, но без повторов темы (тип события или главный путь влияния); не хватило — добор.

    Одно решение ЦБ часто приходит несколькими событиями (решение, пресс-конференция, комментарии),
    и без этого брифинг из трёх пунктов превращается в три пересказа ставки.
    """
    picked: list[T] = []
    seen: set[str] = set()
    for it in items:
        if not tags(it) & seen:
            picked.append(it)
            seen |= tags(it)
        if len(picked) == n:
            return picked
    rest = [it for it in items if it not in picked]
    return picked + rest[: n - len(picked)]


def build_brief(app: AppContext, company_id: str, role: Role) -> Brief:
    focus = role_focus(app, role)

    def bonus(key: str) -> float:
        return ROLE_FOCUS_BONUS if in_focus(key, focus) else 1.0

    rows = diversify(
        RankingStore(app.db).top(company_id, role, limit=CANDIDATES * 5),
        score=lambda r: float(r["score"]) * bonus(main_path_key(r)),
        key=main_path_key,
    )[:CANDIDATES]
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
    keys = {r["event_id"]: main_path_key(r) for r in rows}
    ordered = diversify(
        items,
        score=lambda i: (i.score * READY_BOOST if i.status == "ready" else i.score) * bonus(keys[i.event_id]),
        key=lambda i: keys[i.event_id],
    )
    themes = {r["event_id"]: (ev.event_type if (ev := events.get(r["event_id"])) else "") for r in rows}
    top = distinct_themes(
        ordered, lambda i: {f"type:{themes.get(i.event_id, '')}", keys[i.event_id]}, BRIEF_ITEMS
    )
    words = sum(_words(i) for i in top)
    return Brief(
        role=role,
        items=top,
        reading_time_s=max(10, math.ceil(words / WORDS_PER_MINUTE * 60)),
        generated_at=utc_now(),
    )
