"""Готовые инсайты: поиск актуального по паре, чтение с проверкой доступа, признак устаревания."""

from __future__ import annotations

from dataclasses import dataclass

from alfa_insight.agent.schemas import Insight
from alfa_insight.appctx import AppContext
from alfa_insight.errors import NotFoundError
from alfa_insight.store.insights import InsightRow, InsightStore


def current_prompt_version(app: AppContext) -> str:
    p = app.prompts
    return f"{p.version('draft')}+{p.version('verify')}"


@dataclass
class InsightView:
    insight: Insight
    stale: bool  # версия промпта или профиля поменялась после генерации


def find_current(app: AppContext, company_id: str, event_id: int) -> InsightRow | None:
    """Инсайт текущих версий промпта и профиля (публикуемый или на проверке)."""
    profile = app.profiles.get(company_id)
    return InsightStore(app.db).latest_for(
        company_id,
        event_id,
        prompt_version=current_prompt_version(app),
        profile_version=profile.profile_version,
    )


def _view(app: AppContext, row: InsightRow) -> InsightView:
    profile = app.profiles.get(row.company_id)
    stale = (
        row.prompt_version != current_prompt_version(app) or row.profile_version != profile.profile_version
    )
    return InsightView(insight=Insight.model_validate(row.payload), stale=stale)


def get_insight(app: AppContext, insight_id: str, company_id: str) -> InsightView:
    row = InsightStore(app.db).get(insight_id)
    if row is None or row.company_id != company_id or row.status == "rejected":
        raise NotFoundError("Инсайт не найден", {"insight_id": insight_id})
    return _view(app, row)


def latest_for_event(app: AppContext, company_id: str, event_id: int) -> InsightView | None:
    """Последний инсайт по событию любых версий (устаревший помечается `stale`)."""
    row = InsightStore(app.db).latest_for(company_id, event_id)
    return _view(app, row) if row else None
