"""Справочники для UI (docs/09-api.md §4.1): кешируются клиентом по `version`."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from alfa_insight.api.deps import get_ctx
from alfa_insight.api.routes.system import role_infos
from alfa_insight.api.schemas import ReferenceResponse, RefItem
from alfa_insight.appctx import AppContext
from alfa_insight.reference.taxonomy import UNKNOWN

router = APIRouter(tags=["reference"])


@router.get("/reference", response_model=ReferenceResponse)
async def reference(ctx: AppContext = Depends(get_ctx)) -> ReferenceResponse:
    tax = ctx.taxonomy
    catalog = ctx.products
    return ReferenceResponse(
        version=f"tx{tax.version}-p{catalog.data.version}",
        industries=[RefItem(id=i.id, name=i.name) for i in tax.industries.values() if i.id != UNKNOWN],
        factors=[RefItem(id=f.id, name=f.name) for f in tax.factors.values()],
        countries=[RefItem(id=c.iso2, name=c.names[0]) for c in tax.countries.values()],
        event_types=[RefItem(id=e.id, name=e.name) for e in tax.event_types.values()],
        roles=role_infos(ctx),
        products=[RefItem(id=p.id, name=p.name) for p in catalog.data.products],
        products_disclaimer=catalog.disclaimer,
    )
