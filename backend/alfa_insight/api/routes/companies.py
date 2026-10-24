"""Компании для входа (docs/09-api.md §3)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from alfa_insight.api.deps import get_ctx
from alfa_insight.api.schemas import CompanySummary
from alfa_insight.appctx import AppContext
from alfa_insight.errors import NotFoundError

router = APIRouter(tags=["companies"])


def company_summary(ctx: AppContext, company_id: str) -> CompanySummary:
    if not ctx.profiles.exists(company_id):
        raise NotFoundError("Компания не найдена", {"company_id": company_id})
    p = ctx.profiles.get(company_id)
    demo = {c.company_id: c for c in ctx.demo.companies}
    d = demo.get(company_id)
    return CompanySummary(
        company_id=p.company_id, name=p.name, industry_id=p.industry_id, industry_name=p.industry_name,
        region_name=p.region_name, revenue_bucket=p.revenue_bucket, is_demo=d is not None,
        story=d.story if d else None, default_role=d.default_role if d else "cfo",
    )  # fmt: skip


@router.get("/demo/companies", response_model=list[CompanySummary])
async def list_companies(
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=20, ge=1, le=200),
    ctx: AppContext = Depends(get_ctx),
) -> list[CompanySummary]:
    """Демо-компании первыми; при DEMO_MODE=false без jury-кода войти можно только в них."""
    demo = {c.company_id: c for c in ctx.demo.companies}
    out = []
    needle = (q or "").strip().lower()
    for s in ctx.profiles.list_targets():
        if needle and needle not in s.name.lower() and needle not in s.company_id.lower():
            continue
        d = demo.get(s.company_id)
        out.append(
            CompanySummary(
                company_id=s.company_id, name=s.name, industry_id=s.industry_id, industry_name=s.industry_name,
                region_name=s.region_name, revenue_bucket=s.revenue_bucket, is_demo=d is not None,
                story=d.story if d else None, default_role=d.default_role if d else "cfo",
            )
        )  # fmt: skip
        if len(out) >= limit:
            break
    return out
