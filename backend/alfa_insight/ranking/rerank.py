"""LLM-переранжирование топа событий компании (docs/07-ranking.md §10, P2).

Модель задачи `rerank` оценивает 20 лучших событий компании в её роли по умолчанию: 0–3. Оценки хранятся
в kv (`rerank:{company_id}`) вместе с версией профиля: пересчёт ранжирования перезаписывает строки `rankings`,
а оценки переживают его и применяются в `RankingService` при каждом пересчёте, пока включён `rerank.enabled`.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from alfa_insight.agent.render import profile_brief
from alfa_insight.appctx import AppContext
from alfa_insight.llm.fake import fake_handler
from alfa_insight.llm.types import LLMRequest
from alfa_insight.store.events import EventStore
from alfa_insight.store.kv import KVStore
from alfa_insight.store.rankings import RankingStore


class RerankItem(BaseModel):
    event_id: int
    relevance: Literal[0, 1, 2, 3]
    reason: str = Field(default="", max_length=200)


class RerankOutput(BaseModel):
    """Оценки событий для компании."""

    items: list[RerankItem]


def kv_key(company_id: str) -> str:
    return f"rerank:{company_id}"


def judgments(kv: KVStore, company_id: str, profile_version: str) -> dict[int, int]:
    """event_id → оценка 0–3; оценки устаревшей версии профиля не применяются."""
    raw = kv.get(kv_key(company_id)) or {}
    if raw.get("profile_version") != profile_version:
        return {}
    return {int(k): int(v) for k, v in (raw.get("items") or {}).items()}


def multiplier(relevance: int, alpha: float) -> float:
    """`score' = score · (1 − alpha + alpha · relevance / 3)` (§10)."""
    return 1 - alpha + alpha * relevance / 3


async def rerank_company(app: AppContext, company_id: str) -> int:
    """Оценить топ событий роли по умолчанию, сохранить оценки и пересчитать ранжирование компании."""
    cfg = app.ranking_config.rerank
    profile = app.profiles.get(company_id)
    role = next((c.default_role for c in app.demo.companies if c.company_id == company_id), "cfo")
    rows = RankingStore(app.db).top(company_id, role, limit=cfg.top_n)
    events = EventStore(app.db)
    items = [ev for ev in (events.get(r["event_id"]) for r in rows) if ev is not None]
    if not items:
        return 0
    rendered = app.prompts.render(
        "rerank",
        profile_brief=profile_brief(app.prompts, app.taxonomy, profile),
        events=[{"id": ev.id, "title": ev.title, "summary": ev.summary} for ev in items],
    )
    res = await app.router.structured(
        task="rerank", messages=rendered.messages, schema=RerankOutput, prompt_version=rendered.version,
        priority="precompute",
    )  # fmt: skip
    known = {ev.id for ev in items}
    scored = {str(it.event_id): it.relevance for it in res.value.items if it.event_id in known}
    kv = KVStore(app.db)
    prev = kv.get(kv_key(company_id)) or {}
    merged: dict[str, Any] = {}
    if prev.get("profile_version") == profile.profile_version:
        merged.update(prev.get("items") or {})
    merged.update(scored)
    kv.set(kv_key(company_id), {"profile_version": profile.profile_version, "items": merged})
    app.ranking.rank_company(company_id)
    return len(scored)


_EVENT = re.compile(r"\[event_id=(\d+)\](.*?)(?=\[event_id=|\Z)", re.S)


@fake_handler("rerank")
def fake_rerank(req: LLMRequest, payload: dict[str, Any]) -> dict[str, Any] | None:
    """FakeLLM: оценка 2 каждому событию, 0 — событию с маркером [[IRRELEVANT]] в тексте."""
    user = next((m.text() for m in reversed(req.messages) if m.role == "user"), "")
    found = _EVENT.findall(user)
    if not found:
        return None
    return {"items": [{"event_id": int(i), "relevance": 0 if "[[IRRELEVANT]]" in t else 2, "reason": "fake"}
                      for i, t in found]}  # fmt: skip
