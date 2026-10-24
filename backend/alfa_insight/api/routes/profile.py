"""«Что мы о вас знаем»: профиль, контрагенты, правки клиента (docs/09-api.md §4.2)."""

from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, Query

from alfa_insight.api.deps import current_session, get_ctx
from alfa_insight.api.schemas import (
    CounterpartiesResponse,
    CounterpartyOut,
    OverrideOut,
    OverridesUpdate,
    ProfileResponse,
)
from alfa_insight.api.session import SessionData
from alfa_insight.appctx import AppContext
from alfa_insight.data.profiles import PRODUCT_NAMES
from alfa_insight.errors import ValidationAppError
from alfa_insight.store.profiles import ProfileOverridesRepo

router = APIRouter(tags=["profile"])
FULL_COVERAGE = 0.95


def profile_response(ctx: AppContext, company_id: str) -> ProfileResponse:
    overrides = ProfileOverridesRepo(ctx.db).list(company_id)
    return ProfileResponse(
        profile=ctx.profiles.get(company_id),
        overrides=[OverrideOut(field=o.field, value=o.value, updated_at=o.updated_at) for o in overrides],
    )


@router.get("/me/profile", response_model=ProfileResponse)
async def get_profile(
    s: SessionData = Depends(current_session), ctx: AppContext = Depends(get_ctx)
) -> ProfileResponse:
    return profile_response(ctx, s.company_id)


@router.get("/me/counterparties", response_model=CounterpartiesResponse)
async def get_counterparties(
    direction: Literal["suppliers", "buyers"] = Query(default="suppliers"),
    industry_id: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=10, ge=1, le=50),
    s: SessionData = Depends(current_session),
    ctx: AppContext = Depends(get_ctx),
) -> CounterpartiesResponse:
    if industry_id is not None and industry_id not in ctx.taxonomy.industries:
        raise ValidationAppError("Неизвестная отрасль", {"industry_id": industry_id})
    p = ctx.profiles.get(s.company_id)
    side: Literal["supply", "demand"] = "supply" if direction == "suppliers" else "demand"
    coverage = p.coverage.get(side, 0.0)
    mix = p.suppliers_mix if side == "supply" else p.buyers_mix
    if side == "demand" and p.direction_unknown:
        coverage, mix = 0.0, []
    basis = "prior" if coverage <= 0 or not mix else "payments" if coverage >= FULL_COVERAGE else "blended"
    items = await asyncio.to_thread(ctx.counterparties.top, s.company_id, direction, industry_id, limit)
    return CounterpartiesResponse(
        direction=direction, coverage=coverage, basis=basis, mix=mix,
        items=[CounterpartyOut(name=c.name, industry_id=c.industry_id, industry_name=c.industry_name, share=c.share) for c in items],
    )  # fmt: skip


@router.put("/me/profile/overrides", response_model=ProfileResponse)
async def update_overrides(
    body: OverridesUpdate, s: SessionData = Depends(current_session), ctx: AppContext = Depends(get_ctx)
) -> ProfileResponse:
    """Поле `None` не меняется, поля из `reset` удаляются; затем пересчёт ранжирования компании."""
    tax = ctx.taxonomy
    if body.industry_id is not None and (
        body.industry_id not in tax.industries or body.industry_id == "unknown"
    ):
        raise ValidationAppError("Неизвестная отрасль", {"industry_id": body.industry_id})
    if body.ved is not None:
        bad = [v.country_iso2 for v in body.ved if v.country_iso2.upper() not in tax.countries]
        if bad:
            raise ValidationAppError("Неизвестные страны", {"countries": bad})
    if body.products is not None:
        bad = [k for k in body.products if k not in PRODUCT_NAMES]
        if bad:
            raise ValidationAppError("Неизвестные продукты", {"products": bad})
    repo = ProfileOverridesRepo(ctx.db)
    changes = {
        "industry_id": body.industry_id,
        "ved": [v.model_dump() | {"country_iso2": v.country_iso2.upper()} for v in body.ved]
        if body.ved is not None
        else None,
        "products": body.products,
        "notes": body.notes,
    }
    for field, value in changes.items():
        if value is not None and field not in body.reset:
            repo.upsert(s.company_id, field, value, s.sid)  # type: ignore[arg-type]
    for field in body.reset:
        repo.delete(s.company_id, field)
    ctx.profiles.invalidate(s.company_id)
    await asyncio.to_thread(ctx.ranking.rank_company, s.company_id)
    return profile_response(ctx, s.company_id)
