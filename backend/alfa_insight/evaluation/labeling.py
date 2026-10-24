"""Предразметка LLM и ручная разметка офлайн-набора (docs/12-quality.md §2.3)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from alfa_insight.agent.render import profile_brief
from alfa_insight.appctx import AppContext
from alfa_insight.evaluation.dataset import Label, seed_events
from alfa_insight.store.events import EventStore


class EvalLabelItem(BaseModel):
    event_id: int
    relevance: int = Field(ge=0, le=3)
    direction: Literal["risk", "opportunity", "mixed", "none"]
    reason: str = Field(default="", max_length=300)


class EvalLabelOutput(BaseModel):
    """Оценки событий для компании."""

    items: list[EvalLabelItem]


async def prelabel_company(
    app: AppContext, company_id: str, seed_ids: list[str]
) -> tuple[list[Label], float]:
    """Одна LLM-оценка всего пула компании; возвращает строки `labeler=llm` и стоимость."""
    by_seed = seed_events(app)
    events = EventStore(app.db)
    rows = [(sid, events.get(by_seed[sid])) for sid in seed_ids if sid in by_seed]
    rows = [(sid, ev) for sid, ev in rows if ev is not None]
    if not rows:
        return [], 0.0
    profile = app.profiles.get(company_id)
    rendered = app.prompts.render(
        "eval_label",
        profile_brief=profile_brief(app.prompts, app.taxonomy, profile),
        events=[{"id": ev.id, "title": ev.title, "summary": ev.summary} for _, ev in rows],  # type: ignore[union-attr]
    )
    res = await app.router.structured(
        task="eval_label", messages=rendered.messages, schema=EvalLabelOutput, prompt_version=rendered.version
    )
    seed_of = {ev.id: sid for sid, ev in rows}  # type: ignore[union-attr]
    out = []
    for it in res.value.items:
        if it.event_id in seed_of:
            direction = "none" if it.relevance == 0 else it.direction
            out.append(
                Label(company_id, seed_of[it.event_id], it.relevance, direction, "llm", it.reason[:200])
            )
    return out, res.raw.usage.cost_rub


def event_card(app: AppContext, seed_id: str) -> str:
    """Что видит разметчик: заголовок, summary и теги события. Наш скор не показывается."""
    eid = seed_events(app).get(seed_id)
    ev = EventStore(app.db).get(eid) if eid is not None else None
    if ev is None:
        return f"{seed_id}: события нет в базе"
    sig = app.ranking.events.load_signals([ev.id])[0]
    inds = (
        ", ".join(f"{app.taxonomy.industry(i.industry_id).name} ({i.effect})" for i in sig.industries[:5])
        or "—"
    )
    facs = ", ".join(f"{app.taxonomy.factor(f.factor_id).name} ({'↑' if f.direction > 0 else '↓'})"
                     for f in sig.factors[:5]) or "—"  # fmt: skip
    return f"{ev.title}\n{ev.summary}\nОтрасли: {inds}\nФакторы: {facs}"
